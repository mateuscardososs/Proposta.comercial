from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.assistant.contracts import (
    ConversationCommand,
    ConfirmActionCommand,
    TaskCreateCommand,
    TaskDraftCorrectionCommand,
    TaskQueryCommand,
)
from app.assistant.dates import normalize_text
from app.assistant.provider import (
    ProviderInferenceTrace,
    ProviderInterpretation,
    ProviderMessage,
    ProviderResponseError,
    ProviderUnavailableError,
)
from app.assistant.service import AssistantService
from app.db import SessionLocal
from app.models import (
    AssistantAction,
    AssistantConversation,
    AssistantMessage,
    AssistantRequest,
    Client,
    Task,
    User,
)


class QueueProvider:
    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[dict[str, object]] = []

    def interpret(
        self,
        messages,
        *,
        today,
        timezone,
        tool_results=(),
        pending_action=None,
        allowed_tools=None,
    ):
        self.calls.append(
            {
                "messages": list(messages),
                "tool_results": list(tool_results),
                "pending_action": pending_action,
                "allowed_tools": allowed_tools,
            }
        )
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class TracedProvider(QueueProvider):
    def interpret_with_trace(self, messages, **context):
        command = super().interpret(messages, **context)
        return ProviderInterpretation(
            command=command,
            inferences=[
                ProviderInferenceTrace(
                    attempt=1,
                    queue_wait_seconds=0.01,
                    request_seconds=0.2,
                    context_messages=2,
                    context_characters=300,
                    tool_schema_characters=400,
                    tool_result_count=0,
                    outcome=command.tool,
                )
            ],
        )


def test_service_persists_safe_provider_metrics_and_executed_tools(db):
    db.add(Task(titulo="Relatorio", status="a_fazer", prazo=date(2026, 9, 30), ordem=0))
    db.commit()
    provider = TracedProvider(
        TaskQueryCommand(priorities=True),
        ConversationCommand(message="Comece pelo Relatorio, que vence hoje, 30/09/2026."),
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="Consulte e recomende uma prioridade.",
        request_id="trace-query-1",
    )

    stored = (
        db.query(AssistantMessage)
        .filter(AssistantMessage.reply_to_request_id == "trace-query-1")
        .one()
    )
    assert reply.kind == "text"
    assert len(stored.details_json["provider_inferences"]) == 2
    assert stored.details_json["provider_inferences"][0]["prompt_tokens"] is None
    assert stored.details_json["executed_tools"] == ["consultar_tarefas"]
    assert "messages" not in stored.details_json["provider_inferences"][0]


def _now() -> datetime:
    return datetime(2026, 9, 30, 22, 30, tzinfo=ZoneInfo("America/Recife"))


def test_query_reads_real_tasks_and_persists_conversation(db):
    db.add_all(
        [
            Task(titulo="Relatorio da balanca Alfa", status="a_fazer", prazo=date(2026, 10, 1), ordem=0),
            Task(titulo="Servico concluido", status="concluido", prazo=date(2026, 9, 20), ordem=0),
        ]
    )
    db.commit()
    provider = QueueProvider(
        TaskQueryCommand(include_completed=False, limit=10),
        ConversationCommand(
            message="A prioridade agora é Relatorio da balanca Alfa, com prazo em 01/10/2026."
        ),
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="Quais tarefas e prazos eu tenho?",
        request_id="query-1",
    )

    assert reply.kind == "text"
    assert "Relatorio da balanca Alfa" in reply.message
    assert "01/10/2026" in reply.message
    assert "Servico concluido" not in reply.message
    assert db.query(AssistantConversation).count() == 1
    assert db.query(AssistantMessage).count() == 2


def test_natural_conversation_reply_is_returned_and_persisted(db):
    provider = QueueProvider(
        ConversationCommand(
            message="Boa tarde! Posso consultar o quadro e ajudar a preparar uma nova tarefa."
        )
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(message="Oi, boa tarde.", request_id="talk-1")

    assert reply.kind == "text"
    assert reply.message.startswith("Boa tarde")
    assert reply.action_id is None
    assert reply.task_id is None
    assert db.query(Task).count() == 0


def test_natural_clarifying_question_about_user_tasks_is_not_a_false_data_claim(db):
    provider = QueueProvider(
        ConversationCommand(message="Quais tarefas você tem em mente para organizar primeiro?")
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(message="Meu dia está desorganizado.", request_id="talk-question-1")

    assert reply.kind == "text"
    assert reply.message.startswith("Quais tarefas")


@pytest.mark.parametrize("placeholder", ["none", "Nao especificado", "não definida"])
def test_model_placeholder_for_optional_responsible_does_not_create_false_ambiguity(
    db, placeholder
):
    provider = QueueProvider(
        TaskCreateCommand(
            title="Revisar relatorio",
            due_date="amanha",
            responsible=placeholder,
            client="null",
        )
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="Crie uma tarefa para revisar o relatorio amanha.",
        request_id="optional-placeholder-1",
    )

    assert reply.kind == "confirmation"
    assert reply.fields["responsavel"] == "Sem responsavel"
    assert reply.fields["cliente"] == "Sem cliente"


def test_model_cannot_invent_optional_client_or_responsible_for_task_draft(db):
    provider = QueueProvider(
        TaskCreateCommand(
            title="Telefonar",
            client="Cliente imaginado",
            responsible="Você",
        )
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="Por favor, crie uma tarefa para telefonar.",
        request_id="invented-optional-fields-1",
    )

    assert reply.kind == "confirmation"
    assert reply.fields["responsavel"] == "Sem responsavel"
    assert reply.fields["cliente"] == "Sem cliente"


def test_question_about_previous_answer_reaches_provider_with_history(db):
    provider = QueueProvider(
        ConversationCommand(message="Posso consultar e criar tarefas no quadro."),
        ConversationCommand(
            message="Eu quis dizer que consulto tarefas reais e preparo novas tarefas para sua confirmação."
        ),
    )
    service = AssistantService(db, provider, now=_now)

    first = service.handle_message(message="O que você faz?", request_id="talk-history-1")
    second = service.handle_message(
        message="O que você quis dizer?",
        request_id="talk-history-2",
        conversation_id=first.conversation_id,
    )

    assert "consulto tarefas reais" in second.message
    assert [item.content for item in provider.calls[1]["messages"]] == [
        "O que você faz?",
        first.message,
        "O que você quis dizer?",
    ]


def test_query_result_returns_to_provider_for_a_grounded_natural_answer(db):
    db.add(
        Task(
            titulo="Enviar relatorio Alfa",
            status="a_fazer",
            prazo=date(2026, 9, 30),
            ordem=0,
        )
    )
    db.commit()
    provider = QueueProvider(
        TaskQueryCommand(priorities=True),
        ConversationCommand(
            message="Eu começaria por Enviar relatorio Alfa, porque vence hoje, 30/09/2026."
        ),
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="Veja minhas tarefas e sugira por onde começar.",
        request_id="query-synthesis-1",
    )

    assert reply.message.startswith("Eu começaria")
    assert len(provider.calls) == 2
    result = provider.calls[1]["tool_results"][0]
    assert result.tool == "consultar_tarefas"
    assert result.payload["tasks"][0]["title"] == "Enviar relatorio Alfa"
    assert provider.calls[1]["allowed_tools"] == {
        "responder_conversa",
        "consultar_tarefas",
    }


def test_recommendation_request_applies_real_priority_order_even_if_model_omits_flag(db):
    db.add_all(
        [
            Task(titulo="Tarefa comum", status="a_fazer", prazo=date(2026, 9, 30), ordem=0),
            Task(
                titulo="Documento de servico feito",
                status="servico_feito_falta_nota_pedido",
                prazo=date(2026, 10, 2),
                ordem=0,
            ),
        ]
    )
    db.commit()
    provider = QueueProvider(
        TaskQueryCommand(priorities=False),
        ConversationCommand(message="Comece por Documento de servico feito."),
    )
    service = AssistantService(db, provider, now=_now)

    service.handle_message(
        message="Analise minhas tarefas e recomende qual devo fazer primeiro.",
        request_id="priority-grounding-1",
    )

    tasks = provider.calls[1]["tool_results"][0].payload["tasks"]
    assert tasks[0]["title"] == "Documento de servico feito"
    assert tasks[0]["priority_position"] == 1


def test_explicit_broad_board_recommendation_skips_classification_inference(db):
    db.add_all(
        [
            Task(titulo="Documento pendente", status="servico_feito_falta_nota_pedido", ordem=0),
            Task(titulo="Tarefa secundaria", status="a_fazer", ordem=0),
        ]
    )
    db.commit()
    provider = QueueProvider(
        ConversationCommand(message="Comece por Documento pendente."),
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="Analise as pendências do quadro e recomende qual devo atacar primeiro.",
        request_id="direct-board-recommendation-1",
    )

    assert reply.message == "Comece por Documento pendente."
    assert len(provider.calls) == 1
    result = provider.calls[0]["tool_results"][0].payload
    assert result["criteria"]["priorities"] is True
    assert result["tasks_considered"] == 2
    assert [task["title"] for task in result["tasks"]] == ["Documento pendente"]
    assert result["tasks"][0]["priority_position"] == 1


def test_two_distinct_queries_can_ground_one_answer(db):
    alfa = Client(razao_social="Alfa Industria")
    beta = Client(razao_social="Beta Comercio")
    db.add_all([alfa, beta])
    db.flush()
    db.add_all(
        [
            Task(titulo="Relatorio Alfa", client_id=alfa.id, status="a_fazer", ordem=0),
            Task(titulo="Ligar Beta", client_id=beta.id, status="a_fazer", ordem=0),
        ]
    )
    db.commit()
    provider = QueueProvider(
        TaskQueryCommand(client="Alfa Industria"),
        TaskQueryCommand(client="Beta Comercio"),
        ConversationCommand(message="A Alfa tem Relatorio Alfa e a Beta tem Ligar Beta."),
    )
    service = AssistantService(db, provider, now=_now, max_tool_rounds=2)

    reply = service.handle_message(
        message="Compare o que ficou para Alfa e Beta.",
        request_id="two-queries-1",
    )

    assert reply.message == "A Alfa tem Relatorio Alfa e a Beta tem Ligar Beta."
    assert len(provider.calls) == 3
    assert len(provider.calls[2]["tool_results"]) == 2
    assert provider.calls[2]["allowed_tools"] == {
        "responder_conversa",
    }


def test_repeated_query_is_stopped_without_an_unbounded_model_loop(db):
    db.add(Task(titulo="Unica tarefa", status="a_fazer", ordem=0))
    db.commit()
    repeated = TaskQueryCommand(limit=10)
    provider = QueueProvider(
        repeated,
        repeated,
        ConversationCommand(
            message="Comece por Unica tarefa; ela é a única pendência aberta encontrada."
        ),
    )
    service = AssistantService(db, provider, now=_now, max_tool_rounds=2)

    reply = service.handle_message(
        message="Liste e explique minhas tarefas.", request_id="loop-query-1"
    )

    assert reply.message.startswith("Comece por Unica tarefa")
    assert len(provider.calls) == 3
    assert provider.calls[2]["allowed_tools"] == {
        "responder_conversa",
    }


def test_pending_task_is_provided_as_structured_conversation_state(db):
    provider = QueueProvider(
        TaskCreateCommand(title="Preparar proposta"),
        ConversationCommand(message="O rascunho ainda aguarda sua confirmação."),
    )
    service = AssistantService(db, provider, now=_now)

    preview = service.handle_message(
        message="Crie uma tarefa para preparar a proposta.",
        request_id="pending-state-1",
    )
    service.handle_message(
        message="O que falta fazer com isso?",
        request_id="pending-state-2",
        conversation_id=preview.conversation_id,
    )

    pending = provider.calls[1]["pending_action"]
    assert pending.action_type == "create_task"
    assert pending.status == "pending"
    assert pending.arguments["titulo"] == "Preparar proposta"
    assert "confirmation_token" not in pending.arguments


def test_conversation_reply_cannot_claim_an_unexecuted_action(db):
    provider = QueueProvider(
        ConversationCommand(message="Criei a tarefa no quadro para você.")
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(message="Oi", request_id="unsafe-talk-1")

    assert reply.kind == "error"
    assert "Nada foi alterado" in reply.message
    assert db.query(Task).count() == 0


def test_conversation_reply_cannot_promise_a_future_unexecuted_action(db):
    provider = QueueProvider(
        ConversationCommand(message="A tarefa será criada no quadro.")
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(message="Oi", request_id="unsafe-future-talk-1")

    assert reply.kind == "error"
    assert db.query(Task).count() == 0


def test_conversation_reply_cannot_expose_internal_context_markers(db):
    provider = QueueProvider(
        ConversationCommand(
            message="HISTORICO_JSON=[] ACAO_PENDENTE_JSON=null resposta interna"
        )
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(message="Oi", request_id="unsafe-envelope-1")

    assert reply.kind == "error"
    assert "HISTORICO_JSON" not in reply.message


def test_unavailable_operation_cannot_be_silently_converted_into_a_task(db):
    provider = QueueProvider(
        TaskCreateCommand(
            title="Registrar atendimento",
            client="Cliente inventado",
        )
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="Registre um atendimento de inspeção sem conserto.",
        request_id="scope-boundary-1",
    )

    assert reply.kind == "error"
    assert "nao executo" in reply.message.lower()
    assert db.query(AssistantAction).count() == 0
    assert db.query(Task).count() == 0


def test_unavailable_operation_requires_an_explicit_limitation(db):
    provider = QueueProvider(
        ConversationCommand(message="Qual cliente devo usar para o atendimento?")
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="Cadastre um atendimento de inspeção.",
        request_id="scope-boundary-conversation-1",
    )

    assert reply.kind == "error"
    assert "nao esta disponivel" in normalize_text(reply.message)
    assert db.query(AssistantAction).count() == 0


def test_invalid_model_reply_for_unavailable_operation_has_a_safe_useful_fallback(db):
    provider = QueueProvider(ProviderResponseError("invalid"))
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="Registre um atendimento de inspeção.",
        request_id="scope-fallback-1",
    )

    assert reply.kind == "error"
    assert "nao esta disponivel" in normalize_text(reply.message)
    assert "nada foi executado" in normalize_text(reply.message)


def test_empty_query_explicitly_reports_empty_board_and_offers_help(db):
    provider = QueueProvider(
        TaskQueryCommand(),
        ConversationCommand(
            message="Não há tarefas cadastradas com esses critérios. Se quiser, posso ajudar a criar uma."
        ),
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="O que tenho para fazer hoje?", request_id="empty-query-1"
    )

    assert "Não há tarefas cadastradas" in reply.message
    assert "criar" in reply.message.lower()


def test_create_does_not_accept_a_due_date_invented_by_the_model(db):
    provider = QueueProvider(
        TaskCreateCommand(title="Testar cancelamento", due_date="amanha")
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="Crie uma tarefa temporária para testar o cancelamento.",
        request_id="invented-date-1",
    )

    assert reply.kind == "confirmation"
    assert reply.fields["prazo"] == "Sem prazo"


def test_create_resolves_relative_date_and_only_saves_after_confirmation(db):
    client = Client(razao_social="Cliente Recife")
    user = User(nome="Carlos", email="carlos@example.com", senha_hash="hash")
    db.add_all([client, user])
    db.commit()
    provider = QueueProvider(
        TaskCreateCommand(
            title="Preparar relatorio",
            due_date="amanha",
            client="Cliente Recife",
            responsible="Carlos",
        )
    )
    service = AssistantService(db, provider, now=_now)

    preview = service.handle_message(
        message="Crie para amanha a tarefa de preparar o relatorio do Cliente Recife para o Carlos",
        request_id="create-1",
    )

    assert preview.kind == "confirmation"
    assert preview.action_id is not None
    assert preview.confirmation_token
    assert preview.fields["prazo"] == "01/10/2026"
    assert db.query(Task).count() == 0

    created = service.confirm_action(preview.action_id, preview.confirmation_token)
    repeated = service.confirm_action(preview.action_id, preview.confirmation_token)

    assert created.kind == "success"
    assert created.task_id is not None
    assert created.task_id == repeated.task_id
    assert created.task_url == f"/web/board/{created.task_id}/edit"
    assert db.query(Task).count() == 1
    task = db.get(Task, created.task_id)
    assert task is not None
    assert task.prazo == date(2026, 10, 1)
    assert task.client_id == client.id
    assert task.user_id == user.id
    action = db.get(AssistantAction, preview.action_id)
    assert action is not None
    assert action.status == "executed"
    assert action.task_id == task.id


def test_ambiguous_client_asks_and_followup_keeps_context(db):
    db.add_all([Client(razao_social="Acme Norte"), Client(razao_social="Acme Sul")])
    db.commit()
    provider = QueueProvider(
        TaskCreateCommand(title="Fazer vistoria", client="Acme"),
        TaskCreateCommand(title="Fazer vistoria", client="Acme Norte"),
    )
    service = AssistantService(db, provider, now=_now)

    question = service.handle_message(
        message="Crie uma tarefa de vistoria para a Acme",
        request_id="ambiguous-1",
    )
    preview = service.handle_message(
        message="E a Acme Norte",
        request_id="ambiguous-2",
        conversation_id=question.conversation_id,
    )

    assert question.kind == "clarification"
    assert "Acme Norte" in question.message
    assert "Acme Sul" in question.message
    assert preview.kind == "confirmation"
    assert [message.content for message in provider.calls[1]["messages"]] == [
        "Crie uma tarefa de vistoria para a Acme",
        question.message,
        "E a Acme Norte",
    ]


def test_correction_can_complete_a_draft_that_needs_clarification(db):
    db.add_all([Client(razao_social="Alfa Norte"), Client(razao_social="Alfa Sul")])
    db.commit()
    provider = QueueProvider(
        TaskCreateCommand(title="Preparar relatorio", client="Alfa", due_date="amanha"),
        TaskDraftCorrectionCommand(client="Alfa Sul", due_date="depois de amanha"),
    )
    service = AssistantService(db, provider, now=_now)

    question = service.handle_message(
        message="Crie para amanha o relatorio da Alfa",
        request_id="clarification-correction-1",
    )
    preview = service.handle_message(
        message="Use Alfa Sul e, na verdade, depois de amanha",
        request_id="clarification-correction-2",
        conversation_id=question.conversation_id,
    )

    assert preview.kind == "confirmation"
    assert preview.fields["cliente"] == "Alfa Sul"
    assert preview.fields["prazo"] == "02/10/2026"
    assert db.query(Task).count() == 0
    actions = db.query(AssistantAction).order_by(AssistantAction.id).all()
    assert [action.status for action in actions] == ["cancelled", "pending"]


def test_explicit_date_correction_of_pending_draft_does_not_depend_on_model(db):
    provider = QueueProvider(TaskCreateCommand(title="Revisar relatorio", due_date="amanha"))
    service = AssistantService(db, provider, now=_now)

    preview = service.handle_message(
        message="Crie para amanha a tarefa revisar relatorio",
        request_id="direct-date-correction-1",
    )
    corrected = service.handle_message(
        message="Na verdade, o prazo e depois de amanha.",
        request_id="direct-date-correction-2",
        conversation_id=preview.conversation_id,
    )

    assert corrected.kind == "confirmation"
    assert corrected.fields["prazo"] == "02/10/2026"
    assert len(provider.calls) == 1
    assert db.query(Task).count() == 0


def test_cancel_can_discard_a_draft_that_needs_clarification(db):
    db.add_all([Client(razao_social="Beta Norte"), Client(razao_social="Beta Sul")])
    db.commit()
    provider = QueueProvider(TaskCreateCommand(title="Visitar", client="Beta"))
    service = AssistantService(db, provider, now=_now)

    question = service.handle_message(
        message="Crie a tarefa visitar a Beta",
        request_id="clarification-cancel-1",
    )
    cancelled = service.handle_message(
        message="Cancela",
        request_id="clarification-cancel-2",
        conversation_id=question.conversation_id,
    )

    assert cancelled.message == "Criacao cancelada. Nenhuma tarefa foi adicionada ao quadro."
    assert db.query(AssistantAction).one().status == "cancelled"
    assert db.query(Task).count() == 0
    assert db.query(Task).count() == 0


def test_repeated_message_request_reuses_same_pending_action(db):
    provider = QueueProvider(TaskCreateCommand(title="Telefonar para o cliente"))
    service = AssistantService(db, provider, now=_now)

    first = service.handle_message(
        message="Crie a tarefa telefonar para o cliente",
        request_id="same-request",
    )
    repeated = service.handle_message(
        message="Crie a tarefa telefonar para o cliente",
        request_id="same-request",
    )

    assert first.action_id == repeated.action_id
    assert first.confirmation_token != repeated.confirmation_token
    assert len(provider.calls) == 1
    assert db.query(AssistantAction).count() == 1
    stored_reply = (
        db.query(AssistantMessage)
        .filter(AssistantMessage.reply_to_request_id == "same-request")
        .one()
    )
    assert "confirmation_token" not in stored_reply.details_json
    created = service.confirm_action(repeated.action_id, repeated.confirmation_token)
    assert created.task_id is not None


def test_request_already_in_progress_does_not_call_provider_again(db):
    conversation = AssistantConversation()
    db.add(conversation)
    db.flush()
    message = AssistantMessage(
        conversation_id=conversation.id,
        role="user",
        kind="text",
        content="Crie uma tarefa",
        request_id="in-progress-1",
        details_json={},
    )
    db.add(message)
    db.flush()
    db.add(
        AssistantRequest(
            request_id="in-progress-1",
            conversation_id=conversation.id,
            user_message_id=message.id,
            status="processing",
            lease_expires_at=datetime(2026, 10, 1, 1, 35),
            attempts=1,
        )
    )
    db.commit()
    provider = QueueProvider(TaskCreateCommand(title="Duplicada"))
    service = AssistantService(db, provider, now=_now)

    with pytest.raises(ValueError, match="processada"):
        service.handle_message(
            message="Crie uma tarefa",
            request_id="in-progress-1",
        )

    assert provider.calls == []
    assert db.query(AssistantConversation).count() == 1


def test_expired_request_is_reclaimed_and_completed_without_duplicate_user_message(db):
    conversation = AssistantConversation()
    db.add(conversation)
    db.flush()
    message = AssistantMessage(
        conversation_id=conversation.id,
        role="user",
        kind="text",
        content="Mostre as tarefas",
        request_id="expired-request-1",
        details_json={},
    )
    db.add(message)
    db.flush()
    db.add(
        AssistantRequest(
            request_id="expired-request-1",
            conversation_id=conversation.id,
            user_message_id=message.id,
            status="processing",
            lease_expires_at=datetime(2026, 10, 1, 1, 29),
            attempts=1,
        )
    )
    db.commit()
    provider = QueueProvider(
        TaskQueryCommand(),
        ConversationCommand(message="Não há tarefas cadastradas com esses critérios."),
    )
    service = AssistantService(db, provider, now=_now, request_lease_seconds=120)

    reply = service.handle_message(
        message="Mostre as tarefas",
        request_id="expired-request-1",
        conversation_id=conversation.id,
    )

    request = db.query(AssistantRequest).filter_by(request_id="expired-request-1").one()
    assert reply.kind == "text"
    assert len(provider.calls) == 2
    assert request.status == "completed"
    assert request.attempts == 2
    assert request.reply_message_id is not None
    assert db.query(AssistantMessage).filter_by(request_id="expired-request-1").count() == 1


def test_confirmation_retry_in_new_session_reconciles_saved_task(db):
    provider = QueueProvider(TaskCreateCommand(title="Reconciliar retorno"))
    service = AssistantService(db, provider, now=_now)
    preview = service.handle_message(
        message="Crie a tarefa reconciliar retorno",
        request_id="reconcile-1",
    )
    saved = service.confirm_action(preview.action_id, preview.confirmation_token)

    retry_db = SessionLocal()
    try:
        retried = AssistantService(retry_db, QueueProvider(), now=_now).confirm_action(
            preview.action_id,
            preview.confirmation_token,
        )
        assert retried.task_id == saved.task_id
        assert retry_db.query(Task).count() == 1
    finally:
        retry_db.close()


def test_provider_unavailable_is_clear_and_does_not_mutate_tasks(db):
    provider = QueueProvider(ProviderUnavailableError("connection refused"))
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="Crie uma tarefa urgente",
        request_id="offline-1",
    )

    assert reply.kind == "error"
    assert "Ollama" in reply.message
    assert "disponivel" in reply.message
    assert db.query(Task).count() == 0
    assert db.query(AssistantMessage).count() == 2


def test_confirmation_rejects_wrong_token(db):
    service = AssistantService(
        db,
        QueueProvider(TaskCreateCommand(title="Protegida")),
        now=_now,
    )
    preview = service.handle_message(
        message="Crie uma tarefa protegida",
        request_id="protected-1",
    )

    with pytest.raises(ValueError, match="confirmacao"):
        service.confirm_action(preview.action_id, "token-incorreto")

    assert db.query(Task).count() == 0


def test_cancel_does_not_overwrite_action_already_being_executed(db):
    service = AssistantService(
        db,
        QueueProvider(TaskCreateCommand(title="Em processamento")),
        now=_now,
    )
    preview = service.handle_message(
        message="Crie uma tarefa em processamento",
        request_id="executing-1",
    )
    action = db.get(AssistantAction, preview.action_id)
    action.status = "executing"
    db.commit()

    with pytest.raises(ValueError, match="processada"):
        service.cancel_action(preview.action_id, preview.confirmation_token)

    db.refresh(action)
    assert action.status == "executing"
    assert db.query(Task).count() == 0


def test_text_confirmation_creates_once_and_repeated_confirmation_reconciles(db):
    provider = QueueProvider(TaskCreateCommand(title="Preparar relatorio"))
    service = AssistantService(db, provider, now=_now)
    preview = service.handle_message(
        message="Crie a tarefa preparar relatorio",
        request_id="text-confirm-preview",
    )

    created = service.handle_message(
        message="Pode criar",
        request_id="text-confirm-first",
        conversation_id=preview.conversation_id,
    )
    repeated = service.handle_message(
        message="Pode criar",
        request_id="text-confirm-repeat",
        conversation_id=preview.conversation_id,
    )

    assert created.kind == "success"
    assert repeated.task_id == created.task_id
    assert db.query(Task).count() == 1
    assert len(provider.calls) == 1


def test_model_cannot_turn_unrecognized_text_into_confirmation(db):
    provider = QueueProvider(
        TaskCreateCommand(title="Preparar relatorio"),
        ConfirmActionCommand(),
    )
    service = AssistantService(db, provider, now=_now)
    preview = service.handle_message(
        message="Crie a tarefa preparar relatorio",
        request_id="guard-preview",
    )

    reply = service.handle_message(
        message="Ojectiva",
        request_id="guard-ambiguous-audio",
        conversation_id=preview.conversation_id,
    )

    assert reply.kind == "clarification"
    assert "Pode criar" in reply.message
    assert db.query(Task).count() == 0


def test_text_cancellation_cancels_pending_draft_without_creating_task(db):
    provider = QueueProvider(TaskCreateCommand(title="Ligar para Beta"))
    service = AssistantService(db, provider, now=_now)
    preview = service.handle_message(
        message="Crie a tarefa ligar para Beta",
        request_id="text-cancel-preview",
    )

    cancelled = service.handle_message(
        message="Nao, cancela",
        request_id="text-cancel-action",
        conversation_id=preview.conversation_id,
    )

    assert cancelled.kind == "text"
    assert "cancelada" in cancelled.message.lower()
    assert db.query(Task).count() == 0
    action = db.get(AssistantAction, preview.action_id)
    assert action.status == "cancelled"
    assert len(provider.calls) == 1


def test_draft_correction_updates_fields_and_invalidates_old_confirmation(db):
    alpha_services = Client(razao_social="Alfa Servicos")
    alpha_industry = Client(razao_social="Alfa Industria")
    carlos = User(nome="Carlos", email="carlos@teste.local", senha_hash="hash")
    db.add_all([alpha_services, alpha_industry, carlos])
    db.commit()
    provider = QueueProvider(
        TaskCreateCommand(
            title="Revisar proposta",
            due_date="amanha",
            client="Alfa Servicos",
        ),
        TaskDraftCorrectionCommand(
            title="Revisar relatorio",
            due_date="depois de amanha",
            client="Alfa Industria",
            responsible="Carlos",
        ),
        ConfirmActionCommand(),
    )
    service = AssistantService(db, provider, now=_now)
    original = service.handle_message(
        message="Crie para amanha revisar proposta da Alfa Servicos",
        request_id="correct-preview",
    )

    corrected = service.handle_message(
        message="Mude o titulo para revisar relatorio, use Alfa Industria, Carlos e depois de amanha",
        request_id="correct-draft",
        conversation_id=original.conversation_id,
    )

    assert corrected.kind == "confirmation"
    assert corrected.action_id == original.action_id
    assert corrected.confirmation_token != original.confirmation_token
    assert corrected.fields == {
        "titulo": "Revisar relatorio",
        "status": "A fazer",
        "prazo": "02/10/2026",
        "cliente": "Alfa Industria",
        "responsavel": "Carlos",
    }
    with pytest.raises(ValueError, match="Token"):
        service.confirm_action(original.action_id, original.confirmation_token)

    created = service.handle_message(
        message="Pode criar",
        request_id="correct-confirm",
        conversation_id=original.conversation_id,
    )

    task = db.get(Task, created.task_id)
    assert task.titulo == "Revisar relatorio"
    assert task.prazo == date(2026, 10, 2)
    assert task.client_id == alpha_industry.id
    assert task.user_id == carlos.id
