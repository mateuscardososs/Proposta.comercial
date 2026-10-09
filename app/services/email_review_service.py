from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.assistant.dates import normalize_text
from app.assistant.email.contracts import EmailMessageRecord
from app.assistant.email.extraction import extract_operational_fields
from app.models import Client, EmailActionDraft, EmailTaskLink, InboxEmail
from app.schemas import LancamentoCreate, TaskCreate
from app.services import board_service, lancamento_service

TASK_DRAFT_CATEGORIES = {
    "customer_quote_request": "task_customer_quote",
    "purchase_order": "task_purchase_order",
    "service_request": "task_service_request",
    "pending_reply": "task_pending_reply",
}
PAYABLE_DRAFT_CATEGORIES = {"accounts_payable", "invoice_received"}


def _draft_type(email: InboxEmail) -> str | None:
    task_action = TASK_DRAFT_CATEGORIES.get(email.category)
    if task_action and email.confidence_band == "high":
        return task_action
    if email.category in PAYABLE_DRAFT_CATEGORIES and email.confidence_band in {"medium", "high"}:
        return "payable_entry"
    return None


def ensure_email_action_draft(
    db: Session, email: InboxEmail, *, reopen_cancelled: bool = False
) -> EmailActionDraft | None:
    """Create one structured review proposal per supported message action."""
    if email.review_status == "reviewed" and not reopen_cancelled:
        return None
    action_type = _draft_type(email)
    if action_type is None:
        return None
    draft = (
        db.query(EmailActionDraft)
        .filter_by(inbox_email_id=email.id, action_type=action_type)
        .one_or_none()
    )
    if draft is not None:
        if reopen_cancelled and draft.status == "cancelled":
            draft.status = "pending"
            draft.payload = _draft_payload(db, email, action_type)
        if draft.status == "pending":
            email.review_status = "pending"
        return draft

    payload = _draft_payload(db, email, action_type)
    existing_link = None
    if action_type.startswith("task_"):
        existing_link = (
            db.query(EmailTaskLink)
            .filter_by(
                provider=email.provider,
                mailbox_key=email.mailbox_key,
                reference=email.reference,
                action_type=f"email:{email.category}",
            )
            .one_or_none()
        )
    status_value = "pending"
    linked_task_id = None
    if existing_link is not None:
        status_value = "linked" if existing_link.task_id is not None else "linked_deleted"
        linked_task_id = existing_link.task_id
    draft = EmailActionDraft(
        inbox_email_id=email.id,
        action_type=action_type,
        status=status_value,
        payload=payload,
        task_id=linked_task_id,
    )
    db.add(draft)
    db.flush()
    if draft.status == "pending":
        email.review_status = "pending"
    return draft


def _draft_payload(db: Session, email: InboxEmail, action_type: str) -> dict[str, object]:
    fields = dict(email.extracted_fields or {})
    subject = email.subject.strip() or "Mensagem sem assunto"
    if action_type.startswith("task_"):
        client_name = (
            str(fields.get("party_name") or "").strip()
            if fields.get("party_role") == "client"
            else ""
        )
        if client_name:
            _, resolved_name, client_status = _match_client(db, client_name)
            client_name = resolved_name or client_name
            if client_status == "needs_confirmation":
                fields["uncertainty"] = [
                    *list(fields.get("uncertainty", [])),
                    "O nome informado corresponde a mais de um cadastro; a tarefa ficará sem vínculo definitivo.",
                ]
            elif client_status == "pending_review":
                fields["uncertainty"] = [
                    *list(fields.get("uncertainty", [])),
                    "O nome informado não corresponde claramente a um cadastro; o vínculo ficará pendente de revisão.",
                ]
        task_title = f"Revisar pedido: {subject}"[:255]
        payload: dict[str, object] = {
            "task_title": task_title,
            "client_name": client_name or None,
            "extracted_fields": fields,
        }
    else:
        invoice_number = fields.get("invoice_number")
        description = f"Conferir conta: {subject}"
        if invoice_number:
            description = f"{description} (NF {invoice_number})"
        payload = {
            "description": description[:255],
            "supplier": fields.get("party_name") if fields.get("party_role") == "supplier" else None,
            "extracted_fields": fields,
            "requires_payable_confirmation": True,
        }
        if email.category == "invoice_received":
            uncertainty = list(fields.get("uncertainty", []))
            uncertainty.append(
                "Receber uma nota não confirma, por si só, uma obrigação a pagar; valide a natureza antes do lançamento."
            )
            fields["uncertainty"] = uncertainty
            payload["extracted_fields"] = fields
    return payload


def backfill_existing_email_drafts(db: Session) -> int:
    """Backfill review-only drafts from already stored message summaries, without IMAP access."""
    candidates = (
        db.query(InboxEmail)
        .filter(
            InboxEmail.category.in_(
                (*TASK_DRAFT_CATEGORIES, *PAYABLE_DRAFT_CATEGORIES)
            ),
            InboxEmail.review_status != "reviewed",
        )
        .order_by(InboxEmail.id.asc())
        .yield_per(100)
    )
    created = 0
    for email in candidates:
        if not email.extracted_fields:
            record = EmailMessageRecord(
                reference=email.reference,
                thread_reference=email.thread_reference,
                folder_role="inbox",
                sender=email.sender,
                subject=email.subject,
                recipients=(),
                received_at=email.received_at.replace(tzinfo=ZoneInfo("America/Recife")),
                seen=email.seen,
                text=email.summary,
            )
            fields = extract_operational_fields(record, email.category)
            uncertainty = list(fields.get("uncertainty", []))
            uncertainty.append(
                "O corpo completo não está retido; os campos disponíveis vieram apenas do resumo já armazenado."
            )
            fields["uncertainty"] = uncertainty
            email.extracted_fields = fields
        before = db.query(EmailActionDraft.id).filter_by(inbox_email_id=email.id).first()
        draft = ensure_email_action_draft(db, email)
        if draft is not None and before is None:
            created += 1
    if created:
        db.commit()
    return created


class EmailReviewService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def confirm_draft(
        self, draft_id: int, values: Mapping[str, object]
    ) -> EmailActionDraft:
        draft = (
            self.db.query(EmailActionDraft)
            .filter(EmailActionDraft.id == draft_id)
            .with_for_update()
            .one_or_none()
        )
        if draft is None:
            raise ValueError("Rascunho de e-mail não encontrado.")
        if draft.status in {"confirmed", "linked", "linked_deleted"}:
            return draft
        if draft.status == "cancelled":
            raise ValueError("Este rascunho foi cancelado e não pode ser confirmado.")

        email = self.db.get(InboxEmail, draft.inbox_email_id)
        if email is None:
            raise ValueError("A mensagem de origem não está disponível.")
        if draft.action_type.startswith("task_"):
            already_linked = self._confirm_task(draft, email, values)
            if already_linked:
                self.db.commit()
                return draft
        elif draft.action_type == "payable_entry":
            self._confirm_payable(draft, email, values)
        else:
            raise ValueError("Tipo de ação de e-mail não permitido.")
        draft.status = "confirmed"
        draft.confirmed_at = datetime.now(UTC).replace(tzinfo=None)
        email.review_status = "reviewed"
        self.db.commit()
        return draft

    def _confirm_task(
        self, draft: EmailActionDraft, email: InboxEmail, values: Mapping[str, object]
    ) -> bool:
        title = str(values.get("task_title") or "").strip()
        if not title or len(title) > 255:
            raise ValueError("Informe um título de tarefa entre 1 e 255 caracteres.")
        category = email.category
        action_type = f"email:{category}"
        prior_link = (
            self.db.query(EmailTaskLink)
            .filter_by(
                provider=email.provider,
                mailbox_key=email.mailbox_key,
                reference=email.reference,
                action_type=action_type,
            )
            .with_for_update()
            .one_or_none()
        )
        if prior_link is not None:
            if prior_link.task_id is None:
                draft.status = "linked_deleted"
                return True
            draft.task_id = prior_link.task_id
            draft.status = "linked"
            return True

        supplied_name = str(values.get("client_name") or "").strip()[:255]
        if not supplied_name:
            supplied_name = str(draft.payload.get("client_name") or "").strip()[:255]
        client_id, client_name, link_status = _match_client(self.db, supplied_name)
        task = board_service.create_task(
            self.db,
            TaskCreate(
                titulo=title,
                descricao=(
                    f"Criada após confirmação de pendência de e-mail. "
                    f"Origem: {email.provider}/{email.reference}; categoria: {email.category}."
                ),
                status="a_fazer",
                client_id=client_id,
                client_name=client_name,
                client_link_status=link_status,
            ),
            commit=False,
        )
        self.db.flush()
        self.db.add(
            EmailTaskLink(
                provider=email.provider,
                mailbox_key=email.mailbox_key,
                reference=email.reference,
                action_type=action_type,
                task_id=task.id,
                task_title_snapshot=title,
            )
        )
        draft.task_id = task.id
        return False

    def _confirm_payable(
        self, draft: EmailActionDraft, email: InboxEmail, values: Mapping[str, object]
    ) -> None:
        if values.get("confirm_payable") not in {"yes", "on", True}:
            raise ValueError("É necessária confirmação explícita da obrigação a pagar.")
        required = {
            "description": str(values.get("description") or "").strip(),
            "supplier": str(values.get("supplier") or "").strip(),
            "amount": str(values.get("amount") or "").strip(),
            "issue_date": str(values.get("issue_date") or "").strip(),
            "due_date": str(values.get("due_date") or "").strip(),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError("Preencha os campos obrigatórios antes de confirmar o lançamento.")
        try:
            amount_text = required["amount"]
            amount = Decimal(
                amount_text.replace(".", "").replace(",", ".")
                if "," in amount_text
                else amount_text
            )
            issue_date = date.fromisoformat(required["issue_date"])
            due_date = date.fromisoformat(required["due_date"])
            payload = LancamentoCreate(
                tipo="pagar",
                descricao=required["description"],
                fornecedor=required["supplier"],
                valor=amount,
                data_emissao=issue_date,
                data_vencimento=due_date,
                status="pendente",
            )
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("Valor ou data inválida; revise a proposta de lançamento.") from exc

        entry = lancamento_service.create_lancamento(
            self.db,
            payload,
            commit=False,
            action="email_review_confirmed",
            observation=f"Origem confirmada na revisão de e-mail {email.provider}/{email.reference}",
        )
        draft.lancamento_id = entry.id

    def cancel_draft(self, draft_id: int) -> EmailActionDraft:
        draft = (
            self.db.query(EmailActionDraft)
            .filter(EmailActionDraft.id == draft_id)
            .with_for_update()
            .one_or_none()
        )
        if draft is None:
            raise ValueError("Rascunho de e-mail não encontrado.")
        if draft.status in {"confirmed", "linked", "linked_deleted"}:
            return draft
        draft.status = "cancelled"
        self.db.commit()
        return draft


def _match_client(db: Session, supplied_name: str) -> tuple[int | None, str | None, str]:
    if not supplied_name:
        return None, "Cliente a identificar", "pending_review"
    normalized = normalize_text(supplied_name)
    clients = db.query(Client).order_by(Client.id.asc()).all()
    matches = [
        client
        for client in clients
        if normalize_text(client.razao_social) == normalized
    ]
    if len(matches) == 1:
        return matches[0].id, matches[0].razao_social, "linked"
    if len(matches) > 1:
        return None, supplied_name, "needs_confirmation"
    generic = {"empresa", "servicos", "industria", "ltda", "eireli", "epp", "me", "grupo"}
    supplied_tokens = {token for token in normalized.split() if len(token) >= 3 and token not in generic}
    possible = []
    for client in clients:
        client_tokens = {token for token in normalize_text(client.razao_social).split() if len(token) >= 3 and token not in generic}
        if supplied_tokens and client_tokens.intersection(supplied_tokens):
            possible.append(client)
    if len(possible) > 1:
        return None, supplied_name, "needs_confirmation"
    if len(possible) == 1:
        return possible[0].id, possible[0].razao_social, "linked"
    return None, supplied_name, "pending_review"
