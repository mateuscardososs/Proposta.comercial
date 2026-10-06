from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.assistant.email.classification import to_result
from app.assistant.email.contracts import (
    EmailMessageRecord,
    EmailQuery,
    EmailQueryResult,
)
from app.assistant.email.sync import EmailSyncService
from app.models import (
    Client,
    EmailActionDraft,
    EmailSyncState,
    EmailTaskLink,
    InboxEmail,
    Lancamento,
    Task,
)

TEST_ZONE = ZoneInfo("America/Recife")


class FakeReader:
    def __init__(self, messages, *, sent_available=False, awaiting_reply=False):
        self.messages = messages
        self.calls = 0
        self.queries = []
        self.sent_available = sent_available
        self.awaiting_reply = awaiting_reply

    def query(self, query: EmailQuery) -> EmailQueryResult:
        self.calls += 1
        self.queries.append(query)
        return EmailQueryResult(
            state="success" if self.messages else "empty",
            provider="synthetic",
            interval_start=query.start_at,
            interval_end=query.end_at,
            messages=[
                to_result(m, awaiting_reply="yes" if self.awaiting_reply else "unknown")
                for m in self.messages
            ],
            candidate_count=len(self.messages),
            sent_available=self.sent_available,
        )


class FailedReader:
    def query(self, query: EmailQuery) -> EmailQueryResult:
        return EmailQueryResult(
            state="failed",
            provider="synthetic",
            interval_start=query.start_at,
            interval_end=query.end_at,
            user_message="falhou",
        )


class RaisingReader:
    def query(self, query: EmailQuery) -> EmailQueryResult:
        raise RuntimeError("sensitive-body-and-password-must-not-persist")


class CountingReader(FakeReader):
    pass


def _quote(reference="synthetic-quote-1"):
    return EmailMessageRecord(
        reference=reference,
        thread_reference="synthetic-thread",
        folder_role="inbox",
        sender="cliente@example.test",
        recipients=("ad@example.test",),
        subject="Pedido de orçamento",
        received_at=datetime(2026, 10, 2, 10, tzinfo=TEST_ZONE),
        seen=False,
        text="Solicito orçamento para calibrar a balança.",
    )


def test_sync_creates_one_linked_task_and_retry_is_idempotent(db):
    reader = FakeReader([_quote()])
    sync = EmailSyncService(
        db,
        reader,
        mailbox_key="synthetic-fixture",
        timezone="America/Recife",
        auto_task_creation_enabled=True,
    )

    first = sync.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))
    second = sync.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))

    assert first.created_tasks == 0
    assert second.created_tasks == 0
    assert db.query(Task).count() == 0
    assert db.query(InboxEmail).count() == 1
    assert db.query(InboxEmail).one().review_status == "pending"
    assert db.query(EmailActionDraft).one().status == "pending"


def test_unique_existing_client_is_retained_in_quote_draft_until_confirmation(db):
    client = Client(razao_social="Cliente Alfa")
    db.add(client)
    db.commit()
    message = _quote("synthetic-known-client").model_copy(update={
        "subject": "Pedido de orçamento da Cliente Alfa",
        "text": "Solicito orçamento para calibrar a balança da Cliente Alfa.",
    })
    service = EmailSyncService(
        db, FakeReader([message]), mailbox_key="known-client",
        timezone="America/Recife", auto_task_creation_enabled=True,
    )

    result = service.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))

    assert result.created_tasks == 0
    assert db.query(Task).count() == 0
    draft = db.query(EmailActionDraft).one()
    assert draft.payload["client_name"] == client.razao_social
    from app.services.email_review_service import EmailReviewService
    task_draft = EmailReviewService(db).confirm_draft(
        draft.id,
        {"task_title": "Revisar orçamento Alfa", "client_name": client.razao_social},
    )
    task = db.query(Task).one()
    assert task.client_id == client.id
    assert task.client_name == client.razao_social
    assert task.client_link_status == "linked"
    assert task_draft.task_id == task.id


@pytest.mark.parametrize(
    ("subject", "body", "category"),
    [
        ("Ordem de compra", "Pedido de compra aprovado para revisão.", "purchase_order"),
        ("Chamado técnico", "Solicitamos atendimento técnico para a balança.", "service_request"),
    ],
)
def test_high_confidence_order_and_service_requests_create_review_drafts(
    db, subject, body, category
):
    message = _quote(f"synthetic-{category}").model_copy(
        update={"subject": subject, "text": body}
    )
    service = EmailSyncService(
        db, FakeReader([message]), mailbox_key=f"auto-{category}",
        timezone="America/Recife", auto_task_creation_enabled=True,
    )

    result = service.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))

    assert result.created_tasks == 0
    assert db.query(Task).count() == 0
    draft = db.query(EmailActionDraft).one()
    assert draft.action_type in {"task_purchase_order", "task_service_request"}
    assert draft.status == "pending"


def test_legacy_deleted_task_link_is_not_recreated_by_email_retry(db):
    email = InboxEmail(
        provider="synthetic", mailbox_key="synthetic-deletion", reference="synthetic-deleted-link",
        sender="client@example.test", subject="Pedido de orçamento", received_at=datetime(2026, 10, 2, 10, tzinfo=TEST_ZONE).replace(tzinfo=None),
        seen=False, summary="Solicito orçamento", category="customer_quote_request", confidence_band="high",
        destination="task", classification_reason="pedido explícito", priority="normal", review_status="pending",
        last_seen_at=datetime(2026, 10, 2, 10, tzinfo=TEST_ZONE).replace(tzinfo=None),
    )
    db.add(email)
    db.flush()
    db.add(EmailTaskLink(
        provider="synthetic", mailbox_key="synthetic-deletion", reference="synthetic-deleted-link",
        action_type="email:customer_quote_request", task_id=None, task_title_snapshot="Tarefa removida",
    ))
    db.commit()
    reader = FakeReader([_quote("synthetic-deleted-link")])
    sync = EmailSyncService(db, reader, mailbox_key="synthetic-deletion", timezone="America/Recife")

    retry = sync.sync_once(now=datetime(2026, 10, 2, 12, 15, tzinfo=TEST_ZONE))

    assert retry.created_tasks == 0
    assert db.query(Task).count() == 0
    assert db.query(EmailTaskLink).one().task_id is None
    assert db.query(EmailActionDraft).one().status == "linked_deleted"


def test_existing_task_link_remains_authoritative_if_automation_is_later_disabled(db):
    reader = FakeReader([_quote("synthetic-flag-off")])
    existing = Task(titulo="Tarefa existente", descricao="", status="a_fazer", ordem=0)
    db.add(existing)
    db.flush()
    db.add(EmailTaskLink(
        provider="synthetic", mailbox_key="synthetic-flag-off", reference="synthetic-flag-off",
        action_type="email:customer_quote_request", task_id=existing.id, task_title_snapshot=existing.titulo,
    ))
    db.commit()
    enabled = EmailSyncService(
        db, reader, mailbox_key="synthetic-flag-off", timezone="America/Recife",
        auto_task_creation_enabled=True,
    )
    enabled.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))
    disabled = EmailSyncService(
        db, reader, mailbox_key="synthetic-flag-off", timezone="America/Recife",
        auto_task_creation_enabled=False,
    )

    retry = disabled.sync_once(now=datetime(2026, 10, 2, 12, 15, tzinfo=TEST_ZONE))

    assert retry.created_tasks == 0
    assert db.query(Task).count() == 1
    assert db.query(EmailActionDraft).one().status == "linked"


def test_manual_classification_survives_repeated_sync(db):
    reader = FakeReader([_quote("synthetic-reviewed")])
    service = EmailSyncService(
        db, reader, mailbox_key="synthetic-reviewed", timezone="America/Recife",
        auto_task_creation_enabled=True,
    )
    service.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))
    email = db.query(InboxEmail).one()
    email.category = "informational"
    email.review_status = "reviewed"
    email.classification_reason = "Revisado manualmente"
    db.commit()

    service.sync_once(now=datetime(2026, 10, 2, 12, 15, tzinfo=TEST_ZONE))

    db.refresh(email)
    assert email.category == "informational"
    assert email.review_status == "reviewed"
    assert email.classification_reason == "Revisado manualmente"


def test_financial_message_is_review_only_and_sync_failure_is_not_empty(db):
    invoice = _quote("synthetic-invoice").model_copy(
        update={
            "subject": "Nota fiscal recebida",
            "text": "Segue nota fiscal para pagamento até 12/10/2026.",
        }
    )
    reader = FakeReader([invoice])
    service = EmailSyncService(
        db, reader, mailbox_key="synthetic-fixture", timezone="America/Recife",
        auto_task_creation_enabled=True,
    )
    result = service.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))
    state = db.query(EmailSyncState).one()
    assert result.created_tasks == 0
    assert state.last_success_at is not None
    assert state.last_error is None
    assert db.query(Task).count() == 0
    assert db.query(Lancamento).count() == 0
    assert db.query(InboxEmail).one().review_status == "pending"


def test_promotional_email_is_classified_without_creating_a_task(db):
    advertisement = _quote("synthetic-advertisement").model_copy(
        update={
            "subject": "Newsletter: promoção de outubro",
            "text": "Oferta especial. Descadastre-se para deixar de receber novidades.",
        }
    )
    service = EmailSyncService(
        db,
        FakeReader([advertisement]),
        mailbox_key="synthetic-advertisement",
        timezone="America/Recife",
        auto_task_creation_enabled=True,
    )

    result = service.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))

    stored = db.query(InboxEmail).one()
    assert result.created_tasks == 0
    assert db.query(Task).count() == 0
    assert db.query(EmailTaskLink).count() == 0
    assert stored.category == "informational"
    assert stored.review_status == "classified"


@pytest.mark.parametrize(
    ("subject", "body", "expected_category"),
    [
        (
            "Cotação recebida do fornecedor",
            "Segue a cotação para conferência.",
            "vendor_quotation",
        ),
        (
            "Cotação",
            "Segue a cotação para avaliação, sem pedido especificado.",
            "other_review",
        ),
    ],
)
def test_vendor_or_ambiguous_quote_is_never_auto_tasked(
    db, subject, body, expected_category
):
    message = _quote(f"synthetic-{expected_category}").model_copy(
        update={"subject": subject, "text": body}
    )
    service = EmailSyncService(
        db,
        FakeReader([message]),
        mailbox_key=f"synthetic-{expected_category}",
        timezone="America/Recife",
        auto_task_creation_enabled=True,
    )

    result = service.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))

    assert result.created_tasks == 0
    assert db.query(Task).count() == 0
    assert db.query(EmailTaskLink).count() == 0
    assert db.query(InboxEmail).one().category == expected_category


def test_provider_failure_is_recorded_as_failure_not_empty(db):
    service = EmailSyncService(
        db, FailedReader(), mailbox_key="synthetic-failure", timezone="America/Recife"
    )
    result = service.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))

    assert result.state == "failed"
    assert db.query(EmailSyncState).one().last_error == "failed"
    assert db.query(InboxEmail).count() == 0
    assert db.query(Task).count() == 0


def test_reader_exception_persists_only_error_type_and_does_not_leak_details(db):
    service = EmailSyncService(
        db,
        RaisingReader(),
        mailbox_key="synthetic-redaction",
        timezone="America/Recife",
    )

    result = service.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))

    assert result.state == "failed"
    assert db.query(EmailSyncState).one().last_error == "RuntimeError"
    assert "sensitive-body-and-password" not in str(
        db.query(EmailSyncState).one().last_error
    )


def test_paused_sync_does_not_query_provider(db):
    reader = CountingReader([_quote()])
    db.add(
        EmailSyncState(
            provider="synthetic", mailbox_key="synthetic-paused", paused=True
        )
    )
    db.commit()
    service = EmailSyncService(
        db, reader, mailbox_key="synthetic-paused", timezone="America/Recife"
    )

    result = service.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))

    assert result.state == "paused"
    assert reader.calls == 0
    assert db.query(InboxEmail).count() == 0


def test_similar_customer_names_stay_unlinked_in_review_draft(db):
    db.add_all(
        [Client(razao_social="Alfa Serviços"), Client(razao_social="Alfa Indústria")]
    )
    db.commit()
    quote = _quote()
    quote = quote.model_copy(
        update={
            "subject": "Pedido de orçamento da empresa Alfa",
            "text": "Solicitamos orçamento para calibração da empresa Alfa.",
        }
    )
    service = EmailSyncService(
        db,
        FakeReader([quote]),
        mailbox_key="synthetic-ambiguous",
        timezone="America/Recife",
        auto_task_creation_enabled=True,
    )

    result = service.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))

    assert result.created_tasks == 0
    assert db.query(Task).count() == 0
    draft = db.query(EmailActionDraft).one()
    from app.services.email_review_service import EmailReviewService
    confirmed = EmailReviewService(db).confirm_draft(
        draft.id, {"task_title": "Revisar orçamento Alfa", "client_name": "Alfa"}
    )
    task = db.query(Task).one()
    assert task.client_id is None
    assert task.client_name == "Alfa"
    assert task.client_link_status == "needs_confirmation"
    assert confirmed.task_id == task.id
    stored = db.query(InboxEmail).one()
    assert stored.review_status == "reviewed"
    assert "mais de um cadastro" in " ".join(
        db.query(EmailActionDraft).one().payload["extracted_fields"]["uncertainty"]
    )


def test_unknown_explicit_customer_name_stays_in_review_draft_until_confirmation(db):
    quote = _quote("synthetic-unknown-customer").model_copy(
        update={"subject": "Pedido de orçamento da empresa Ômega"}
    )
    service = EmailSyncService(
        db,
        FakeReader([quote]),
        mailbox_key="synthetic-unknown-customer",
        timezone="America/Recife",
        auto_task_creation_enabled=True,
    )

    result = service.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))

    assert result.created_tasks == 0
    assert db.query(Task).count() == 0
    draft = db.query(EmailActionDraft).one()
    assert draft.payload["client_name"] == "Ômega"
    from app.services.email_review_service import EmailReviewService
    EmailReviewService(db).confirm_draft(
        draft.id, {"task_title": "Revisar orçamento Ômega", "client_name": "Ômega"}
    )
    task = db.query(Task).one()
    assert task.client_id is None
    assert task.client_name == "Ômega"
    assert task.client_link_status == "pending_review"
    stored = db.query(InboxEmail).one()
    assert stored.review_status == "reviewed"
    assert "não corresponde claramente" in " ".join(
        db.query(EmailActionDraft).one().payload["extracted_fields"]["uncertainty"]
    )

    repeated = service.sync_once(now=datetime(2026, 10, 2, 12, 15, tzinfo=TEST_ZONE))
    assert repeated.created_tasks == 0
    assert db.query(Task).count() == 1
    assert db.query(InboxEmail).one().review_status == "reviewed"


def test_first_sync_starts_at_activation_and_never_imports_older_messages(db):
    reader = FakeReader([_quote("synthetic-after-activation")])
    service = EmailSyncService(
        db, reader, mailbox_key="activation-boundary", timezone="America/Recife",
        auto_task_creation_enabled=True,
    )
    activation = datetime(2026, 10, 2, 11, 30, tzinfo=TEST_ZONE)
    service.activate(now=activation)

    service.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))

    assert reader.queries[0].start_at == activation
    assert db.query(EmailSyncState).one().activation_at == activation.replace(tzinfo=None)


def test_sync_retry_overlap_is_clamped_to_activation(db):
    reader = FakeReader([_quote("synthetic-clamp")])
    service = EmailSyncService(
        db, reader, mailbox_key="activation-clamp", timezone="America/Recife",
        auto_task_creation_enabled=True,
    )
    activation = datetime(2026, 10, 2, 11, 30, tzinfo=TEST_ZONE)
    service.activate(now=activation)
    state = db.query(EmailSyncState).one()
    state.last_success_at = datetime(2026, 10, 2, 11, 45, tzinfo=TEST_ZONE).replace(tzinfo=None)
    db.commit()

    service.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))

    assert reader.queries[0].start_at == activation


def test_pending_reply_is_classified_but_not_tasked_automatically(db):
    message = _quote("synthetic-pending-reply").model_copy(
        update={
            "subject": "Aguardamos retorno",
            "text": "Aguardamos retorno sobre a visita técnica.",
        }
    )
    reader = FakeReader([message], sent_available=True, awaiting_reply=True)
    service = EmailSyncService(
        db,
        reader,
        mailbox_key="synthetic-sent-coverage",
        timezone="America/Recife",
        auto_task_creation_enabled=True,
    )

    result = service.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))

    assert result.created_tasks == 0
    assert db.query(Task).count() == 0
    assert db.query(EmailActionDraft).one().action_type == "task_pending_reply"
    stored = db.query(InboxEmail).one()
    assert stored.category == "pending_reply"
    assert stored.sent_coverage is True
    assert stored.awaiting_reply == "yes"
