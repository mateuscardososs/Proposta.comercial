from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.assistant.capabilities import CapabilityRegistry
from app.assistant.contracts import (
    ConversationCommand,
    EmailQueryCommand,
    TaskCreateCommand,
    TaskQueryCommand,
)
from app.assistant.email.synthetic import SyntheticEmailReader, synthetic_messages
from app.assistant.email.contracts import EmailQueryResult
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
        self.queries = []

    def query(self, query):
        self.query_count += 1
        self.queries.append(query)
        return super().query(query)


class FilteredEmptyReader:
    def query(self, query):
        return EmailQueryResult(
            state="empty",
            provider="test",
            interval_start=query.start_at,
            interval_end=query.end_at,
            candidate_count=2,
            applied_filters=["attention"],
        )


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
    assert provider.calls[0]["tool_results"][0].state == "success"
    stored = db.query(AssistantMessage).filter_by(reply_to_request_id="email-today-1").one()
    assert stored.details_json["email_items"][0]["reference"] == "syn-in-001"
    assert "secret" not in stored.details_json


def test_email_query_retry_reuses_completed_response_without_reading_again(db):
    reader = CountingReader(messages=synthetic_messages(NOW))
    provider = QueueProvider(
        ConversationCommand(message="Há dois e-mails não lidos hoje."),
    )
    assistant = service(db, provider, reader)

    first = assistant.handle_message(message="Quais ainda não li?", request_id="email-retry-1")
    second = assistant.handle_message(message="Quais ainda não li?", request_id="email-retry-1")

    assert second == first
    assert first.kind == "text"
    assert reader.query_count == 1


def test_email_provider_failure_is_not_reported_as_empty_or_success(db):
    from app.assistant.email.provider import EmailTimeoutError

    reader = CountingReader(messages=synthetic_messages(NOW), failure=EmailTimeoutError("secret"))
    provider = QueueProvider()

    reply = service(db, provider, reader).handle_message(
        message="Quais e-mails chegaram hoje?",
        request_id="email-timeout-1",
    )

    assert reply.kind == "error"
    assert "tempo limite" in reply.message
    assert "não significa" in reply.message
    assert len(provider.calls) == 0
    stored = db.query(AssistantMessage).filter_by(reply_to_request_id="email-timeout-1").one()
    assert stored.details_json["executed_tools"] == ["consultar_emails"]
    assert stored.details_json["tool_results"][0]["state"] == "failed"
    assert stored.details_json["tool_results"][0]["evidence_id"].startswith("email:")


def test_filtered_empty_result_does_not_claim_the_mailbox_has_no_messages(db):
    provider = QueueProvider(
        ConversationCommand(
            message="Há mensagens no período, mas nenhuma correspondeu ao filtro de atenção."
        )
    )
    assistant = service(db, provider, FilteredEmptyReader())

    reply = assistant.handle_message(
        message="Tem algo no meu e-mail que eu precise resolver?",
        request_id="email-filtered-empty-1",
    )

    assert reply.kind == "text"
    result = provider.calls[0]["tool_results"][0]
    assert result.payload["count"] == 0
    assert result.payload["candidate_count"] == 2
    assert result.payload["returned_count"] == 0
    assert result.payload["applied_filters"] == ["attention"]
    assert "sem mensagens" not in reply.message.casefold()


def test_filtered_empty_result_rejects_false_claim_that_period_has_no_messages(db):
    provider = QueueProvider(
        ConversationCommand(message="Não encontrei nenhuma mensagem no período consultado.")
    )
    assistant = service(db, provider, FilteredEmptyReader())

    reply = assistant.handle_message(
        message="Tem algo urgente na caixa de entrada?",
        request_id="email-filtered-false-empty-1",
    )

    assert reply.kind == "error"
    assert "nenhuma mensagem" not in reply.message.casefold()


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


def test_structured_email_history_is_pruned_after_configured_retention(db):
    from app.models import AssistantConversation

    conversation = AssistantConversation()
    db.add(conversation)
    db.flush()
    old = AssistantMessage(
        conversation_id=conversation.id,
        role="assistant",
        kind="text",
        content="Resumo antigo permanece como parte da conversa.",
        details_json={
            "email_items": [{"reference": "old", "subject": "Assunto sensível"}],
            "tool_results": [
                {
                    "tool": "consultar_emails",
                    "state": "success",
                    "payload": {"count": 1, "messages": [{"subject": "Assunto sensível"}]},
                }
            ],
        },
        created_at=(NOW - timedelta(days=15)).replace(tzinfo=None),
    )
    db.add(old)
    db.commit()
    assistant = AssistantService(
        db,
        QueueProvider(ConversationCommand(message="Tudo bem.")),
        now=lambda: NOW,
        email_reader=CountingReader(messages=synthetic_messages(NOW)),
        capabilities=CapabilityRegistry(email_provider="synthetic"),
        email_history_retention_days=14,
    )

    history = assistant.get_history(conversation.id)
    db.refresh(old)

    assert history[0].details.get("email_items") is None
    assert "email_items" not in old.details_json
    assert "messages" not in old.details_json["tool_results"][0]["payload"]
    assert old.content.startswith("Resumo antigo")


def test_email_content_cannot_trigger_a_second_tool(db):
    from app.models import Task

    db.add(Task(titulo="Dado do quadro que não deve ser exposto", status="a_fazer", ordem=0))
    db.commit()
    reader = CountingReader(messages=synthetic_messages(NOW))
    provider = QueueProvider(
        EmailQueryCommand(period="week", sender="desconhecido"),
        TaskQueryCommand(),
    )
    assistant = service(db, provider, reader)

    reply = assistant.handle_message(
        message="Mostre o e-mail do remetente desconhecido.",
        request_id="email-injection-tool-1",
    )

    assert reply.kind == "error"
    stored = db.query(AssistantMessage).filter_by(reply_to_request_id="email-injection-tool-1").one()
    assert stored.details_json["executed_tools"] == ["consultar_emails"]


def test_email_results_sent_to_model_are_bounded(db):
    many = []
    base = synthetic_messages(NOW)[0]
    for index in range(20):
        many.append(
            base.model_copy(
                update={
                    "reference": f"many-{index}",
                    "thread_reference": f"thread-{index}",
                    "subject": f"Mensagem {index} " + ("x" * 300),
                    "text": "Texto longo " + ("y" * 1000),
                }
            )
        )
    reader = CountingReader(messages=many)
    provider = QueueProvider(
        ConversationCommand(message="Foram apresentadas três mensagens prioritárias."),
    )

    reply = service(db, provider, reader).handle_message(
        message="Quais e-mails chegaram hoje?", request_id="email-bounded-1"
    )

    assert reply.kind == "text"
    assert len(provider.calls[0]["tool_results"][0].payload["messages"]) == 3


def test_historical_email_reply_requires_an_explicit_previous_result_label(db):
    reader = CountingReader(messages=synthetic_messages(NOW))
    provider = QueueProvider(
        ConversationCommand(message="No resultado atual, há duas mensagens."),
        ConversationCommand(message="Foi Marina - Alfa Indústria."),
    )
    assistant = service(db, provider, reader)
    first = assistant.handle_message(
        message="Quais e-mails chegaram hoje?", request_id="email-history-list"
    )

    reply = assistant.handle_message(
        message="Quem enviou o primeiro?",
        request_id="email-history-follow-up",
        conversation_id=first.conversation_id,
    )

    assert reply.kind == "error"
    assert "Nada foi alterado" in reply.message


def test_email_history_allows_an_unrelated_change_of_subject(db):
    reader = CountingReader(messages=synthetic_messages(NOW))
    provider = QueueProvider(
        ConversationCommand(message="No resultado atual, há duas mensagens."),
        ConversationCommand(message="Por nada! Posso ajudar em outro assunto."),
    )
    assistant = service(db, provider, reader)
    first = assistant.handle_message(
        message="Quais e-mails chegaram hoje?", request_id="email-history-topic-list"
    )

    reply = assistant.handle_message(
        message="Obrigado.",
        request_id="email-history-topic-change",
        conversation_id=first.conversation_id,
    )

    assert reply.kind == "text"
    assert reply.message.startswith("Por nada")


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "Tem algo no meu e-mail que eu precise resolver?",
            {"period": "week", "attention_only": True},
        ),
        (
            "Ficou alguém esperando meu retorno?",
            {"period": "week", "awaiting_reply": True},
        ),
        ("O que chegou hoje?", {"period": "today"}),
        ("Quais mensagens chegaram hoje?", {"period": "today"}),
        ("O que eu ainda não vi?", {"period": "week", "unread_only": True}),
        ("Tem mensagens não lidas?", {"period": "week", "unread_only": True}),
        (
            "Tem algo urgente na caixa de entrada?",
            {"period": "week", "attention_only": True},
        ),
    ],
)
def test_natural_email_paraphrases_execute_email_tool_before_reply(db, message, expected):
    reader = CountingReader(messages=synthetic_messages(NOW))
    provider = QueueProvider(ConversationCommand(message="Resultado da consulta disponível."))
    assistant = service(db, provider, reader)

    request_id = f"email-natural-{abs(hash(message))}"
    reply = assistant.handle_message(
        message=message,
        request_id=request_id,
    )

    assert reply.kind == "text"
    assert reader.query_count == 1
    query = reader.queries[0]
    for field, value in expected.items():
        if field == "period":
            expected_date = (
                NOW.date()
                if value == "today"
                else NOW.date() - timedelta(days=NOW.weekday())
            )
            assert query.start_at.date() == expected_date
        else:
            assert getattr(query, field) == value
    assert len(provider.calls) == 1
    assert provider.calls[0]["allowed_tools"] == {"responder_conversa"}
    assert provider.calls[0]["tool_results"][0].tool == "consultar_emails"
    stored = db.query(AssistantMessage).filter_by(reply_to_request_id=request_id).one()
    assert stored.details_json["executed_tools"] == ["consultar_emails"]


@pytest.mark.parametrize(
    ("message", "clarification"),
    [
        ("O que chegou?", "Você está perguntando sobre e-mails ou sobre uma entrega?"),
        ("Tem algo urgente?", "Você quer consultar tarefas ou e-mails?"),
        ("O que eu ainda não vi no quadro?", "Qual parte do quadro você quer consultar?"),
        ("Eu ainda não vi o relatório.", "Quer ajuda para organizar a revisão do relatório?"),
    ],
)
def test_ambiguous_or_non_email_paraphrases_do_not_read_mailbox(db, message, clarification):
    reader = CountingReader(messages=synthetic_messages(NOW))
    provider = QueueProvider(ConversationCommand(message=clarification))

    reply = service(db, provider, reader).handle_message(
        message=message,
        request_id=f"email-ambiguous-{abs(hash(message))}",
    )

    assert reply.kind == "text"
    assert reply.message == clarification
    assert reader.query_count == 0
    assert provider.calls[0]["tool_results"] == ()


def test_indirect_email_intent_reports_unavailable_without_calling_provider_or_reader(db):
    reader = CountingReader(messages=synthetic_messages(NOW))
    provider = QueueProvider()
    assistant = AssistantService(
        db,
        provider,
        now=lambda: NOW,
        email_reader=reader,
        capabilities=CapabilityRegistry(email_provider="disabled"),
    )

    reply = assistant.handle_message(
        message="Ficou alguém esperando meu retorno?",
        request_id="email-natural-disabled",
    )

    assert reply.kind == "error"
    assert "não está configurada" in reply.message
    assert "Nenhuma caixa foi consultada" in reply.message
    assert reader.query_count == 0
    assert provider.calls == []
