from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.assistant.capabilities import CapabilityRegistry
from app.assistant.contracts import ConversationCommand, EmailQueryCommand, TaskCreateCommand
from app.assistant.email.synthetic import SyntheticEmailReader, synthetic_messages
from app.assistant.service import AssistantService
from app.models import AssistantAction, AssistantEmailTaskLink, AssistantMessage, Task


NOW = datetime(2026, 10, 1, 10, 0, tzinfo=ZoneInfo("America/Recife"))


class QueueProvider:
    def __init__(self, *commands):
        self.commands = list(commands)
        self.calls = []

    def interpret(self, messages, **context):
        self.calls.append({"messages": list(messages), **context})
        return self.commands.pop(0)


class CountingReader(SyntheticEmailReader):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.query_count = 0

    def query(self, query):
        self.query_count += 1
        return super().query(query)


def service(db, provider, reader):
    return AssistantService(
        db,
        provider,
        now=lambda: NOW,
        email_reader=reader,
        capabilities=CapabilityRegistry(email_provider="synthetic"),
    )


def test_email_query_executes_reader_before_natural_reply_and_persists_visual_items(db):
    reader = CountingReader(messages=synthetic_messages(NOW))
    provider = QueueProvider(
        EmailQueryCommand(period="today"),
        ConversationCommand(
            message=(
                "O e-mail da Alfa Indústria merece atenção primeiro: há autorização, prazo em "
                "02/10/2026 e pedido de confirmação. Também chegou uma publicidade sem ação sugerida."
            )
        ),
    )

    reply = service(db, provider, reader).handle_message(
        message="Quais e-mails chegaram hoje?",
        request_id="email-today-1",
    )

    assert reply.kind == "text"
    assert reader.query_count == 1
    assert reply.consulted_interval == "01/10/2026 00:00 a 01/10/2026 10:00"
    assert [item["reference"] for item in reply.email_items] == ["syn-in-001", "syn-in-003"]
    assert provider.calls[1]["tool_results"][0].state == "success"
    stored = db.query(AssistantMessage).filter_by(reply_to_request_id="email-today-1").one()
    assert stored.details_json["email_items"][0]["reference"] == "syn-in-001"
    assert "secret" not in stored.details_json


def test_email_query_retry_reuses_completed_response_without_reading_again(db):
    reader = CountingReader(messages=synthetic_messages(NOW))
    provider = QueueProvider(
        EmailQueryCommand(period="today", unread_only=True),
        ConversationCommand(message="Há dois e-mails não lidos hoje."),
    )
    assistant = service(db, provider, reader)

    first = assistant.handle_message(message="Quais ainda não li?", request_id="email-retry-1")
    second = assistant.handle_message(message="Quais ainda não li?", request_id="email-retry-1")

    assert second == first
    assert reader.query_count == 1


def test_email_provider_failure_is_not_reported_as_empty_or_success(db):
    from app.assistant.email.provider import EmailTimeoutError

    reader = CountingReader(messages=synthetic_messages(NOW), failure=EmailTimeoutError("secret"))
    provider = QueueProvider(EmailQueryCommand(period="today"))

    reply = service(db, provider, reader).handle_message(
        message="Quais e-mails chegaram hoje?",
        request_id="email-timeout-1",
    )

    assert reply.kind == "error"
    assert "tempo limite" in reply.message
    assert "não significa" in reply.message
    assert len(provider.calls) == 1


def test_false_email_claim_from_conversation_command_is_rejected_in_service(db):
    reader = CountingReader(messages=synthetic_messages(NOW))
    provider = QueueProvider(ConversationCommand(message="Conferi os e-mails e não chegou nada."))

    reply = service(db, provider, reader).handle_message(
        message="Você conferiu os e-mails?",
        request_id="email-false-claim-1",
    )

    assert reply.kind == "error"
    assert "Nada foi alterado" in reply.message
    assert reader.query_count == 0


def test_task_from_second_email_uses_confirmation_and_persists_reference_once(db):
    reader = CountingReader(messages=synthetic_messages(NOW))
    provider = QueueProvider(
        EmailQueryCommand(period="week"),
        ConversationCommand(message="Mostrei os e-mails da semana."),
        TaskCreateCommand(title="Responder"),
    )
    assistant = service(db, provider, reader)
    first = assistant.handle_message(
        message="Mostre os e-mails desta semana.", request_id="email-link-list"
    )
    draft = assistant.handle_message(
        message="Cria uma tarefa para responder o segundo.",
        request_id="email-link-task",
        conversation_id=first.conversation_id,
    )

    assert draft.kind == "confirmation"
    assert "Pedido de orçamento" in draft.fields["titulo"]
    action = db.get(AssistantAction, draft.action_id)
    assert action.arguments_json["source_email_reference"] == "syn-in-002"

    saved = assistant.confirm_action(draft.action_id, draft.confirmation_token)
    repeated = assistant.confirm_action(draft.action_id, draft.confirmation_token)

    assert saved.task_id == repeated.task_id
    assert db.query(Task).count() == 1
    link = db.query(AssistantEmailTaskLink).one()
    assert link.task_id == saved.task_id
    assert link.email_reference == "syn-in-002"


def test_ambiguous_email_reference_asks_instead_of_inventing_link(db):
    reader = CountingReader(messages=synthetic_messages(NOW))
    provider = QueueProvider(
        EmailQueryCommand(period="today"),
        ConversationCommand(message="Há duas mensagens hoje."),
        TaskCreateCommand(title="Responder"),
    )
    assistant = service(db, provider, reader)
    first = assistant.handle_message(
        message="Quais e-mails chegaram hoje?", request_id="email-ambiguous-list"
    )
    reply = assistant.handle_message(
        message="Cria uma tarefa para responder esse.",
        request_id="email-ambiguous-task",
        conversation_id=first.conversation_id,
    )

    assert reply.kind == "clarification"
    assert "Qual e-mail" in reply.message
    assert db.query(AssistantAction).count() == 0
