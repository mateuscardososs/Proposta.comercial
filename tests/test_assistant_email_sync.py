from datetime import datetime
from zoneinfo import ZoneInfo

from app.assistant.email.classification import to_result
from app.assistant.email.contracts import (
    EmailMessageRecord,
    EmailQuery,
    EmailQueryResult,
)
from app.assistant.email.sync import EmailSyncService
from app.models import (
    Client,
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
        self.sent_available = sent_available
        self.awaiting_reply = awaiting_reply

    def query(self, query: EmailQuery) -> EmailQueryResult:
        self.calls += 1
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

    assert first.created_tasks == 1
    assert second.created_tasks == 0
    assert db.query(Task).count() == 1
    task = db.query(Task).one()
    assert task.status == "a_fazer"
    assert db.query(InboxEmail).count() == 1
    assert db.query(EmailTaskLink).count() == 1
    assert db.query(EmailTaskLink).one().task_id == task.id


def test_origin_idempotency_link_survives_task_deletion(db):
    reader = FakeReader([_quote("synthetic-deleted-link")])
    sync = EmailSyncService(
        db,
        reader,
        mailbox_key="synthetic-deletion",
        timezone="America/Recife",
        auto_task_creation_enabled=True,
    )
    sync.sync_once(now=datetime(2026, 10, 2, 12, tzinfo=TEST_ZONE))
    task = db.query(Task).one()
    db.delete(task)
    db.commit()

    retry = sync.sync_once(now=datetime(2026, 10, 2, 12, 15, tzinfo=TEST_ZONE))

    assert retry.created_tasks == 0
    assert db.query(Task).count() == 0
    assert db.query(EmailTaskLink).one().task_id is None
    assert db.query(InboxEmail).one().review_status == "task_created_deleted"


def test_existing_task_link_remains_authoritative_if_automation_is_later_disabled(db):
    reader = FakeReader([_quote("synthetic-flag-off")])
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
    assert db.query(InboxEmail).one().review_status == "task_created"


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


def test_similar_customer_names_route_quote_to_review_without_guessing(db):
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
    stored = db.query(InboxEmail).one()
    assert stored.review_status == "pending"
    assert "mais de um cadastro" in stored.classification_reason


def test_unknown_explicit_customer_name_routes_quote_to_review(db):
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
    stored = db.query(InboxEmail).one()
    assert stored.review_status == "pending"
    assert "não encontrado no cadastro" in stored.classification_reason


def test_pending_reply_task_requires_complete_sent_coverage(db):
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

    assert result.created_tasks == 1
    stored = db.query(InboxEmail).one()
    assert stored.category == "pending_reply"
    assert stored.sent_coverage is True
    assert stored.awaiting_reply == "yes"
