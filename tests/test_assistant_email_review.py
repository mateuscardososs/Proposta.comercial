from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.assistant.email.contracts import (
    EmailMessageRecord,
    EmailQuery,
    EmailQueryResult,
)
from app.assistant.email.sync import EmailSyncService
from app.config import get_settings
from app.main import app
from app.models import (
    EmailActionDraft,
    EmailTaskLink,
    InboxEmail,
    Lancamento,
    LancamentoHistorico,
    Task,
)
from app.services.email_review_service import (
    EmailReviewService,
    backfill_existing_email_drafts,
)

ZONE = ZoneInfo("America/Recife")


class SyntheticReader:
    def __init__(self, message):
        self.message = message

    def query(self, query: EmailQuery) -> EmailQueryResult:
        from app.assistant.email.classification import to_result

        return EmailQueryResult(
            state="success",
            provider="synthetic",
            interval_start=query.start_at,
            interval_end=query.end_at,
            messages=[to_result(self.message)],
        )


def _message(subject: str, text: str, *, reference: str = "synthetic-review-1"):
    return EmailMessageRecord(
        reference=reference,
        thread_reference="synthetic-thread",
        folder_role="inbox",
        sender="Fornecedor Exemplo <financeiro@example.test>",
        recipients=("ad@example.test",),
        subject=subject,
        received_at=datetime(2026, 10, 6, 10, tzinfo=ZONE),
        seen=False,
        text=text,
    )


def _sync(db, message):
    return EmailSyncService(
        db,
        SyntheticReader(message),
        mailbox_key="synthetic-review",
        timezone="America/Recife",
        auto_task_creation_enabled=True,
    ).sync_once(now=datetime(2026, 10, 6, 12, tzinfo=ZONE))


def test_quote_sync_creates_review_draft_not_task_and_retry_is_idempotent(db):
    message = _message(
        "Pedido de orçamento da empresa Alfa",
        "Solicito orçamento para calibrar a balança da empresa Alfa até 12/10/2026.",
    )

    first = _sync(db, message)
    second = _sync(db, message)

    assert first.created_tasks == second.created_tasks == 0
    assert db.query(Task).count() == 0
    assert db.query(EmailActionDraft).count() == 1
    draft = db.query(EmailActionDraft).one()
    assert draft.action_type == "task_customer_quote"
    assert draft.status == "pending"
    assert draft.payload["task_title"]
    assert draft.payload["extracted_fields"]["party_name"] == "Alfa"


def test_customer_quote_creates_task_only_after_confirmation_and_retry_reuses_it(db):
    _sync(db, _message("Pedido de orçamento", "Solicito orçamento para calibrar a balança."))
    draft = db.query(EmailActionDraft).one()
    service = EmailReviewService(db)

    first = service.confirm_draft(draft.id, {"task_title": "Avaliar pedido de orçamento", "client_name": ""})
    retry = service.confirm_draft(draft.id, {"task_title": "Outro título ignorado no retry", "client_name": ""})

    assert first.task_id == retry.task_id
    assert first.status == "confirmed"
    assert db.query(Task).count() == 1
    assert db.query(EmailTaskLink).count() == 1
    task = db.query(Task).one()
    assert task.client_id is None
    assert task.client_name == "Cliente a identificar"
    assert task.status == "a_fazer"


def test_confirmation_does_not_recreate_previously_deleted_linked_task(db):
    _sync(db, _message("Pedido de orçamento", "Solicito orçamento para calibrar a balança."))
    draft = db.query(EmailActionDraft).one()
    email = db.get(InboxEmail, draft.inbox_email_id)
    db.add(
        EmailTaskLink(
            provider=email.provider,
            mailbox_key=email.mailbox_key,
            reference=email.reference,
            action_type=f"email:{email.category}",
            task_id=None,
            task_title_snapshot="Tarefa original removida",
        )
    )
    db.commit()

    result = EmailReviewService(db).confirm_draft(
        draft.id,
        {"task_title": "Não recriar", "client_name": ""},
    )

    assert result.status == "linked_deleted"
    assert result.task_id is None
    assert db.query(Task).count() == 0


def test_payable_draft_requires_explicit_complete_fields_then_creates_pending_entry_once(db):
    _sync(
        db,
        _message(
            "Conta a pagar do fornecedor Acme",
            "Fornecedor: Acme Instrumentos. Total R$ 1.234,56. Vencimento em 20/10/2026. "
            "Nota fiscal nº NF-4821 emitida em 15/10/2026.",
        ),
    )
    draft = db.query(EmailActionDraft).one()
    service = EmailReviewService(db)

    assert db.query(Lancamento).count() == 0
    with pytest.raises(ValueError, match="confirmação explícita"):
        service.confirm_draft(draft.id, {"confirm_payable": "", "amount": "1234.56"})
    assert db.query(Lancamento).count() == 0

    values = {
        "confirm_payable": "yes",
        "description": "Conta Acme NF-4821",
        "supplier": "Acme Instrumentos",
        "amount": "1234.56",
        "issue_date": "2026-10-15",
        "due_date": "2026-10-20",
    }
    first = service.confirm_draft(draft.id, values)
    retry = service.confirm_draft(draft.id, values)

    assert first.lancamento_id == retry.lancamento_id
    assert first.status == "confirmed"
    entry = db.query(Lancamento).one()
    assert entry.tipo == "pagar"
    assert entry.status == "pendente"
    assert entry.valor.as_tuple().exponent == -2
    assert db.query(LancamentoHistorico).count() == 1


def test_missing_financial_fields_are_reported_and_block_confirmation(db):
    _sync(db, _message("Conta a pagar", "Fornecedor: Acme Instrumentos. Boleto disponível."))
    draft = db.query(EmailActionDraft).one()

    assert {"valor", "vencimento", "data de emissão"}.issubset(
        set(draft.payload["extracted_fields"]["missing_fields"])
    )
    with pytest.raises(ValueError, match="campos obrigatórios"):
        EmailReviewService(db).confirm_draft(
            draft.id,
            {"confirm_payable": "yes", "description": "Boleto", "supplier": "Acme"},
        )
    assert db.query(Lancamento).count() == 0


def test_cancelled_quote_draft_never_creates_task_and_vendor_quote_is_not_tasked(db):
    _sync(db, _message("Pedido de orçamento", "Solicito orçamento para calibração."))
    draft = db.query(EmailActionDraft).one()
    EmailReviewService(db).cancel_draft(draft.id)
    assert db.query(Task).count() == 0
    assert db.query(EmailActionDraft).one().status == "cancelled"

    _sync(
        db,
        _message(
            "Cotação recebida do fornecedor Acme",
            "Fornecedor: Acme Instrumentos. Segue nossa cotação comercial.",
            reference="synthetic-vendor-quotation",
        ),
    )
    vendor_email = db.query(InboxEmail).filter_by(reference="synthetic-vendor-quotation").one()
    assert vendor_email.category == "vendor_quotation"
    assert db.query(EmailActionDraft).count() == 1
    assert db.query(Task).count() == 0


def test_messages_queue_shows_structured_preview_and_confirms_email_task_route(db):
    settings = get_settings()
    message = _message(
        "Pedido de orçamento da empresa Alfa",
        "Solicito orçamento para calibração da empresa Alfa.",
    )
    from app.assistant.email.classification import to_result

    result = to_result(message)
    email = InboxEmail(
        provider=settings.email_provider,
        mailbox_key=settings.email_sync_mailbox_key,
        reference=message.reference,
        thread_reference=message.thread_reference,
        sender=message.sender,
        subject=message.subject,
        received_at=message.received_at.replace(tzinfo=None),
        seen=False,
        awaiting_reply="unknown",
        sent_coverage=False,
        summary=result.summary,
        category=result.category,
        confidence_band=result.confidence_band,
        destination=result.destination,
        classification_reason=result.classification_reason,
        priority=result.priority,
        explicit_deadline=result.explicit_deadline,
        extracted_fields=result.extracted_fields,
        review_status="pending",
        last_seen_at=message.received_at.replace(tzinfo=None),
    )
    db.add(email)
    db.flush()
    draft = EmailActionDraft(
        inbox_email_id=email.id,
        action_type="task_customer_quote",
        status="pending",
        payload={"task_title": "Revisar orçamento Alfa", "client_name": "Alfa", "extracted_fields": result.extracted_fields},
    )
    db.add(draft)
    db.commit()

    with TestClient(app, follow_redirects=False) as client:
        page = client.get("/web/mensagens")
        response = client.post(
            f"/web/mensagens/action-drafts/{draft.id}/confirm",
            data={"task_title": "Revisar orçamento Alfa", "client_name": "Alfa"},
        )

    assert page.status_code == 200
    assert "Prévia para conferência" in page.text
    assert "Cliente/fornecedor" in page.text
    assert "Confirmar e criar tarefa" in page.text
    assert "Cotação de fornecedor" in page.text
    assert response.status_code == 303
    assert db.query(Task).count() == 1
    assert db.query(EmailTaskLink).count() == 1


def test_messages_queue_marks_financial_data_absent_and_never_creates_entry_on_view(db):
    settings = get_settings()
    email = InboxEmail(
        provider=settings.email_provider,
        mailbox_key=settings.email_sync_mailbox_key,
        reference="synthetic-financial-preview",
        thread_reference="synthetic-financial-thread",
        sender="Fornecedor Exemplo <financeiro@example.test>",
        subject="Nota fiscal recebida",
        received_at=datetime(2026, 10, 6, 10, tzinfo=ZONE).replace(tzinfo=None),
        seen=True,
        summary="Segue nota fiscal para conferência.",
        category="invoice_received",
        confidence_band="high",
        destination="review",
        classification_reason="Nota fiscal recebida.",
        priority="normal",
        review_status="pending",
        last_seen_at=datetime(2026, 10, 6, 10, tzinfo=ZONE).replace(tzinfo=None),
    )
    db.add(email)
    db.flush()
    draft = EmailActionDraft(
        inbox_email_id=email.id,
        action_type="payable_entry",
        status="pending",
        payload={
            "description": "Conferir nota fiscal recebida",
            "supplier": None,
            "extracted_fields": {
                "party_name": None,
                "party_role": "supplier",
                "amount": None,
                "due_date": None,
                "issue_date": None,
                "invoice_number": None,
                "missing_fields": ["fornecedor", "valor", "vencimento", "data de emissão", "número da nota"],
                "uncertainty": ["Receber uma nota não confirma, por si só, uma obrigação a pagar."],
            },
            "requires_payable_confirmation": True,
        },
    )
    db.add(draft)
    db.commit()

    with TestClient(app) as client:
        response = client.get("/web/mensagens")

    assert response.status_code == 200
    assert "Não identificado" in response.text
    assert "Campos ausentes" in response.text
    assert "Confirmo que os dados correspondem a uma conta a pagar" in response.text
    assert db.query(Lancamento).count() == 0


def test_startup_backfill_uses_only_stored_summary_and_is_idempotent(db):
    email = InboxEmail(
        provider="synthetic",
        mailbox_key="synthetic-backfill",
        reference="synthetic-old-quote",
        thread_reference="synthetic-old-thread",
        sender="Cliente Exemplo <cliente@example.test>",
        subject="Pedido de orçamento",
        received_at=datetime(2026, 10, 6, 10, tzinfo=ZONE).replace(tzinfo=None),
        seen=False,
        summary="Solicito orçamento da empresa Ômega.",
        category="customer_quote_request",
        confidence_band="high",
        destination="task",
        classification_reason="Pedido explícito.",
        priority="normal",
        review_status="pending",
        last_seen_at=datetime(2026, 10, 6, 10, tzinfo=ZONE).replace(tzinfo=None),
    )
    db.add(email)
    db.commit()

    first = backfill_existing_email_drafts(db)
    second = backfill_existing_email_drafts(db)

    assert first == 1
    assert second == 0
    assert db.query(EmailActionDraft).count() == 1
    fields = db.query(EmailActionDraft).one().payload["extracted_fields"]
    assert fields["party_name"] == "Ômega"
    assert any("corpo completo não está retido" in note for note in fields["uncertainty"])
    assert db.query(Task).count() == 0


def test_manual_category_correction_reuses_same_queue_and_opens_only_a_draft(db):
    settings = get_settings()
    email = InboxEmail(
        provider=settings.email_provider,
        mailbox_key=settings.email_sync_mailbox_key,
        reference="synthetic-manual-review",
        thread_reference="synthetic-manual-thread",
        sender="Cliente Exemplo <cliente@example.test>",
        subject="Cotação para revisão",
        received_at=datetime(2026, 10, 6, 10, tzinfo=ZONE).replace(tzinfo=None),
        seen=True,
        summary="Solicitamos orçamento para calibrar a balança da empresa Alfa.",
        category="other_review",
        confidence_band="low",
        destination="review",
        classification_reason="Contexto insuficiente.",
        priority="low",
        review_status="pending",
        last_seen_at=datetime(2026, 10, 6, 10, tzinfo=ZONE).replace(tzinfo=None),
    )
    db.add(email)
    db.commit()

    with TestClient(app, follow_redirects=False) as client:
        response = client.post(
            f"/web/mensagens/{email.id}/review",
            data={"category": "customer_quote_request"},
        )

    db.refresh(email)
    assert response.status_code == 303
    assert email.category == "customer_quote_request"
    assert email.review_status == "pending"
    assert db.query(EmailActionDraft).count() == 1
    assert db.query(Task).count() == 0
