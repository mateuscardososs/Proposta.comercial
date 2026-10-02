from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.assistant.dates import normalize_text
from app.assistant.email.contracts import EmailQuery, EmailQueryResult
from app.assistant.email.provider import EmailReader
from app.models import Client, EmailSyncState, EmailTaskLink, InboxEmail
from app.schemas import TaskCreate
from app.services.board_service import create_task


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
        self.auto_task_creation_enabled = auto_task_creation_enabled

    def sync_once(self, *, now: datetime | None = None) -> SyncSummary:
        local_now = now or datetime.now(self.zone)
        if local_now.tzinfo is None:
            local_now = local_now.replace(tzinfo=self.zone)
        naive_now = local_now.astimezone(self.zone).replace(tzinfo=None)
        state = self._state()
        state.last_attempt_at = naive_now
        if state.paused:
            self.db.commit()
            return SyncSummary(state="paused")
        try:
            last_success = state.last_success_at
            start_at = (
                (last_success.replace(tzinfo=self.zone) - timedelta(days=1))
                if last_success
                else local_now - timedelta(days=self.lookback_days)
            )
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
            if message.destination == "review" or (
                message.confidence_band != "high" and not waiting_for_reply
            ):
                stored.review_status = "pending"
                review += 1
                continue
            eligible = message.auto_task_eligible or waiting_for_reply
            if not eligible:
                stored.review_status = "classified"
                continue
            created += self._ensure_task(result.provider, stored, message)

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
                ):
                    values.pop(key, None)
            for key, value in values.items():
                setattr(stored, key, value)
        return stored

    def _ensure_task(self, provider: str, message: InboxEmail, result) -> int:
        action_type = f"email:{result.category}"
        existing = (
            self.db.query(EmailTaskLink)
            .filter_by(
                provider=provider,
                mailbox_key=self.mailbox_key,
                reference=message.reference,
                action_type=action_type,
            )
            .one_or_none()
        )
        if existing:
            message.review_status = (
                "task_created" if existing.task_id else "task_created_deleted"
            )
            return 0
        if not self.auto_task_creation_enabled:
            message.review_status = "pending"
            return 0

        searchable = normalize_text(
            f"{message.sender}\n{message.subject}\n{message.summary}"
        )
        generic_name_tokens = {
            "empresa",
            "industria",
            "servicos",
            "comercio",
            "ltda",
            "eireli",
            "epp",
            "me",
            "companhia",
            "grupo",
        }
        clients = self.db.query(Client).order_by(Client.id.asc()).all()
        exact_matches = [
            client
            for client in clients
            if normalize_text(client.razao_social) in searchable
        ]
        matches = exact_matches
        for client in clients if not exact_matches else []:
            tokens = {
                token
                for token in re.findall(
                    r"[a-z0-9]+", normalize_text(client.razao_social)
                )
                if len(token) >= 3 and token not in generic_name_tokens
            }
            if tokens and any(
                re.search(rf"\b{re.escape(token)}\b", searchable) for token in tokens
            ):
                matches.append(client)
        named_client = re.search(
            r"\b(?:empresa|cliente)\s+([a-z0-9][a-z0-9.-]{1,40})\b", searchable
        )
        explicit_client_name = bool(
            named_client
            and named_client.group(1)
            not in {
                "pede",
                "solicita",
                "solicitou",
                "solicitamos",
                "informa",
                "informou",
                "autoriza",
            }
        )
        if explicit_client_name and not matches:
            message.review_status = "pending"
            message.classification_reason = (
                message.classification_reason
                + "; cliente citado não encontrado no cadastro"
            )[:2000]
            return 0
        if len(matches) > 1:
            message.review_status = "pending"
            message.classification_reason = (
                message.classification_reason
                + "; nome de cliente corresponde a mais de um cadastro"
            )[:2000]
            return 0
        client_id = matches[0].id if matches else None

        title = f"{result.action_suggested or 'Revisar e-mail'}: {message.subject}"[
            :255
        ]
        deadline: date | None = None
        if result.explicit_deadline:
            try:
                day, month, year = (
                    int(part) for part in result.explicit_deadline.split("/")
                )
                deadline = date(year, month, day)
            except ValueError:
                deadline = None
        task = create_task(
            self.db,
            TaskCreate(
                titulo=title,
                descricao=(
                    f"Origem: e-mail {provider}, referência {message.reference}. "
                    f"Classificação: {result.category}. Motivo: {result.classification_reason}"
                )[:4000],
                status="a_fazer",
                client_id=client_id,
                prazo=deadline,
            ),
            commit=False,
        )
        self.db.flush()
        self.db.add(
            EmailTaskLink(
                provider=provider,
                mailbox_key=self.mailbox_key,
                reference=message.reference,
                action_type=action_type,
                task_id=task.id,
                task_title_snapshot=title,
            )
        )
        message.review_status = "task_created"
        return 1
