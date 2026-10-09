from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.assistant.email.contracts import EmailQuery, EmailQueryResult
from app.assistant.email.provider import EmailReader
from app.models import EmailSyncState, InboxEmail
from app.services.email_review_service import ensure_email_action_draft


@dataclass(frozen=True)
class SyncSummary:
    state: str
    examined: int = 0
    created_tasks: int = 0
    review_items: int = 0
    error_code: str | None = None


class EmailSyncService:
    """Bounded one-shot sync. A caller must explicitly inject a provider."""

    def __init__(
        self,
        db: Session,
        reader: EmailReader,
        *,
        mailbox_key: str,
        timezone: str = "America/Recife",
        lookback_days: int = 30,
        batch_size: int = 30,
        provider_name: str = "synthetic",
        auto_task_creation_enabled: bool = False,
    ) -> None:
        self.db = db
        self.reader = reader
        self.mailbox_key = mailbox_key
        self.zone = ZoneInfo(timezone)
        self.lookback_days = max(1, min(90, lookback_days))
        self.batch_size = max(1, min(100, batch_size))
        self.provider_name = provider_name
        # Kept for constructor compatibility. Email sync now creates only review drafts;
        # operational records always require a separate human confirmation.
        self.auto_task_creation_enabled = auto_task_creation_enabled

    def sync_once(self, *, now: datetime | None = None) -> SyncSummary:
        local_now = now or datetime.now(self.zone)
        if local_now.tzinfo is None:
            local_now = local_now.replace(tzinfo=self.zone)
        naive_now = local_now.astimezone(self.zone).replace(tzinfo=None)
        state = self._state()
        if state.activation_at is None:
            state.activation_at = naive_now
        state.last_attempt_at = naive_now
        if state.paused:
            self.db.commit()
            return SyncSummary(state="paused")
        try:
            last_success = state.last_success_at
            activation_at = state.activation_at.replace(tzinfo=self.zone)
            overlap_start = (
                last_success.replace(tzinfo=self.zone) - timedelta(days=1)
                if last_success else activation_at
            )
            start_at = max(activation_at, overlap_start)
            result = self.reader.query(
                EmailQuery(
                    start_at=start_at,
                    end_at=local_now,
                    limit=self.batch_size,
                )
            )
        except Exception as exc:  # noqa: BLE001 - sanitize all provider failures; never leak exception text
            # Exception text may contain server responses or credentials. Persist only its class.
            state.last_error = type(exc).__name__[:200]
            self.db.commit()
            return SyncSummary(state="failed", error_code=state.last_error)

        if result.state in {"failed", "not_configured", "not_implemented"}:
            state.last_error = result.state
            self.db.commit()
            return SyncSummary(state=result.state, error_code=result.state)

        created = review = 0
        for message in result.messages:
            stored = self._upsert_message(result, message, naive_now)
            if stored.review_status == "reviewed":
                continue
            waiting_for_reply = (
                message.awaiting_reply == "yes"
                and result.sent_available
                and result.state == "success"
                and not result.partial
                and not result.stale
            )
            if waiting_for_reply:
                stored.category = "pending_reply"
                stored.confidence_band = "high"
                stored.destination = "task"
                stored.classification_reason = (
                    stored.classification_reason
                    + "; resposta possivelmente pendente: Entrada e Enviados consultados sem resposta posterior"
                )[:2000]
            draft = ensure_email_action_draft(self.db, stored)
            if draft is not None:
                if draft.status == "pending":
                    stored.review_status = "pending"
                review += 1
                continue
            if message.destination == "review" or (
                message.confidence_band != "high" and not waiting_for_reply
            ):
                stored.review_status = "pending"
                review += 1
                continue
            stored.review_status = "classified"

        incomplete = (
            result.partial or result.stale or result.state in {"partial", "stale"}
        )
        if not incomplete:
            state.last_success_at = naive_now
        state.last_error = "partial" if incomplete else None
        state.last_count = len(result.messages)
        self.db.commit()
        normalized_state = (
            "partial"
            if state.last_error
            else ("empty" if result.state == "empty" else "success")
        )
        return SyncSummary(
            state=normalized_state,
            examined=len(result.messages),
            created_tasks=created,
            review_items=review,
        )

    def activate(self, *, now: datetime | None = None) -> datetime:
        """Persist the pilot's first-read boundary without querying the mailbox."""
        local_now = now or datetime.now(self.zone)
        if local_now.tzinfo is None:
            local_now = local_now.replace(tzinfo=self.zone)
        activation_at = local_now.astimezone(self.zone).replace(tzinfo=None)
        state = self._state()
        if state.activation_at is None:
            state.activation_at = activation_at
            self.db.commit()
        return state.activation_at.replace(tzinfo=self.zone)

    def _state(self) -> EmailSyncState:
        state = (
            self.db.query(EmailSyncState)
            .filter_by(provider=self.provider_name, mailbox_key=self.mailbox_key)
            .one_or_none()
        )
        if state is None:
            state = EmailSyncState(
                provider=self.provider_name, mailbox_key=self.mailbox_key
            )
            self.db.add(state)
            self.db.flush()
        return state

    def _upsert_message(
        self, result: EmailQueryResult, message, observed_at: datetime
    ) -> InboxEmail:
        stored = (
            self.db.query(InboxEmail)
            .filter_by(
                provider=result.provider,
                mailbox_key=self.mailbox_key,
                reference=message.reference,
            )
            .one_or_none()
        )
        values = {
            "thread_reference": "",
            "sender": message.sender[:500],
            "subject": message.subject[:500],
            "received_at": message.received_at.replace(tzinfo=None),
            "seen": message.seen,
            "awaiting_reply": message.awaiting_reply,
            "sent_coverage": (
                result.sent_available
                and result.state == "success"
                and not result.partial
                and not result.stale
            ),
            "summary": message.summary[:400],
            "category": message.category,
            "confidence_band": message.confidence_band,
            "destination": message.destination,
            "classification_reason": message.classification_reason[:2000],
            "priority": message.priority,
            "explicit_deadline": message.explicit_deadline,
            "extracted_fields": message.extracted_fields,
            "last_seen_at": observed_at,
        }
        # Keep thread identifiers opaque; query contracts intentionally expose only references.
        if stored is None:
            stored = InboxEmail(
                provider=result.provider,
                mailbox_key=self.mailbox_key,
                reference=message.reference[:160],
                **values,
            )
            self.db.add(stored)
            self.db.flush()
        else:
            if stored.review_status == "reviewed":
                for key in (
                    "category",
                    "confidence_band",
                    "destination",
                    "classification_reason",
                    "priority",
                    "explicit_deadline",
                    "extracted_fields",
                ):
                    values.pop(key, None)
            for key, value in values.items():
                setattr(stored, key, value)
        return stored
