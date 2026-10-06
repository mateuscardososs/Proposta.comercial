from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.assistant.capabilities import CapabilityRegistry
from app.assistant.contracts import (
    ConfirmActionCommand,
    ConversationCommand,
    TaskCreateCommand,
    TaskDraftCorrectionCommand,
    TaskQueryCommand,
)
from app.assistant.dates import normalize_text
from app.assistant.email.synthetic import SyntheticEmailReader, synthetic_messages
from app.assistant.provider import (
    ProviderInferenceTrace,
    ProviderInterpretation,
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


@pytest.mark.parametrize(
    ("phrase", "category", "period"),
    [
        ("Quais e-mails pedem orçamento?", "customer_quote_request", "week"),
        ("Me diga quais emails tem solicitação de orçamento", "customer_quote_request", "week"),
        ("Tem alguma solicitação de cotação na caixa?", "customer_quote_request", "week"),
        ("Chegou hoje algum pedido de orçamento?", "customer_quote_request", "today"),
        ("Tem conta a pagar nos e-mails?", "accounts_payable", "week"),
        ("Recebi alguma nota fiscal por e-mail?", "invoice_received", "week"),
    ],
)
def test_known_email_category_queries_route_without_relying_on_model_tool_choice(
    db, phrase, category, period
):
    command = AssistantService(db, QueueProvider(ConversationCommand(message="ok")), now=_now)
    routed = command._direct_email_query(phrase)

    assert routed is not None
    assert routed.category == category
    assert routed.period == period


@pytest.mark.parametrize(
    "phrase",
    [
        "Quais e-mails pedem emissão de nota fiscal?",
        "Tem algum e-mail sobre conta a pagar?",
        "Me diga quais emails têm solicitação de orçamento.",
    ],
)
def test_email_read_category_is_not_mapped_to_an_unavailable_write(phrase):
    assert AssistantService._request_targets_email_read(phrase)
    assert not AssistantService._request_targets_unavailable_operation(phrase)


@pytest.mark.parametrize(
    ("phrase", "period"),
    [
        ("O que chegou hoje?", "today"),
        ("O que chegou nesta semana?", "week"),
        ("O que recebi no e-mail durante a semana?", "week"),
        ("Quais mensagens chegaram esta semana?", "week"),
    ],
)
def test_indirect_incoming_message_period_queries_route_to_email_reader(db, phrase, period):
    service = AssistantService(db, QueueProvider(), now=_now)
    routed = service._direct_email_query(phrase)

    assert routed is not None
    assert routed.period == period


def test_retry_reuses_prior_email_result_and_updates_same_conversation_message(db):
    class CountingReader(SyntheticEmailReader):
        calls = 0

        def query(self, query):
            self.calls += 1
            return super().query(query)

    reader = CountingReader(messages=synthetic_messages(_now()))
    provider = QueueProvider(
        ProviderResponseError("invalid response"),
        ConversationCommand(message="Consultei a caixa e encontrei mensagens no período."),
    )
    service = AssistantService(
        db, provider, now=_now, email_reader=reader,
        capabilities=CapabilityRegistry(email_provider="synthetic"),
    )
    request = {"message": "Quais e-mails chegaram hoje?", "request_id": "email-retry-1"}

    first = service.handle_message(**request)
    message_count = db.query(AssistantMessage).count()
    retried = service.handle_message(**request, retry=True)

    assert first.kind == "error"
    assert first.retryable is True
    assert retried.kind == "text"
    assert reader.calls == 1
    assert db.query(AssistantMessage).count() == message_count
    assert db.query(AssistantRequest).filter_by(request_id="email-retry-1").one().attempts == 2


def test_email_query_logs_only_safe_metadata_not_message_content(db, caplog):
    from app.assistant.email.contracts import EmailMessageRecord

    private_marker = "BODY-MUST-NOT-APPEAR-IN-LOGS"
    message = EmailMessageRecord(
        reference="synthetic-log-check", thread_reference="synthetic-log-thread",
        folder_role="inbox", sender="Remetente sintético", subject="Assunto sintético",
        received_at=_now(), seen=False, text=private_marker,
    )
    service = AssistantService(
        db, QueueProvider(), now=_now,
        email_reader=SyntheticEmailReader(messages=[message]),
        capabilities=CapabilityRegistry(email_provider="synthetic"),
    )

    with caplog.at_level("INFO", logger="app.assistant.service"):
        execution = service._execute_email_query(
            1, service._direct_email_query("Quais e-mails chegaram hoje?")
        )

    assert execution.reply.kind == "text"
    assert "assistant_email stage=read outcome=success" in caplog.text
    assert private_marker not in caplog.text
    assert "Assunto sintético" not in caplog.text


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


def test_known_task_recommendation_returns_a_grounded_complete_order_without_model(db):
    db.add(
        Task(
            titulo="Enviar relatorio Alfa",
            status="a_fazer",
            prazo=date(2026, 9, 30),
            ordem=0,
        )
    )
    db.commit()
    provider = QueueProvider()
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="Veja minhas tarefas e sugira por onde começar.",
        request_id="query-synthesis-1",
    )

    assert "Enviar relatorio Alfa" in reply.message
    assert "Prazo: 30/09/2026" in reply.message
    assert "Prioridade sugerida: Não definida" in reply.message
    assert provider.calls == []


def test_recommendation_order_uses_real_status_and_deadline_without_model(db):
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
    provider = QueueProvider()
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="Analise minhas tarefas e recomende qual devo fazer primeiro.",
        request_id="priority-grounding-1",
    )

    assert reply.message.index("Tarefa comum") < reply.message.index("Documento de servico feito")
    assert "etapa documental pendente" in normalize_text(reply.message)
    assert provider.calls == []


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

    assert "Documento pendente" in reply.message
    assert "Tarefa secundaria" in reply.message
    assert provider.calls == []
    assert "Prioridade sugerida" in reply.message


@pytest.mark.parametrize(
    "phrase",
    [
        "Organize minha agenda",
        "Olhe o quadro de tarefas e diga o que devo fazer hoje",
        "Mostre minhas tarefas abertas",
        "O que devo fazer hoje?",
    ],
)
def test_known_agenda_intent_queries_the_board_without_model_tool_choice(db, phrase):
    db.add(Task(titulo="Pendência sintética", status="a_fazer", ordem=0))
    db.commit()
    service = AssistantService(db, provider=None, now=_now)

    reply = service.handle_message(message=phrase, request_id=f"agenda-direct-{len(phrase)}")

    assert reply.kind == "text"
    assert "Pendência sintética" in reply.message
    assert "consultei" in normalize_text(reply.message)
    assert "quadro" in normalize_text(reply.message)


def test_agenda_includes_all_open_task_states_and_never_truncates_at_fifty(db):
    client = Client(razao_social="Cliente sintético agenda")
    db.add(client)
    db.flush()
    tasks = [
        Task(titulo="Urgência explícita", descricao="Marcada como urgente", status="a_fazer", ordem=0),
        Task(titulo="Tarefa atrasada sintética", status="a_fazer", prazo=date(2026, 9, 29), client_id=client.id, ordem=0),
        Task(titulo="Tarefa para hoje sintética", status="em_andamento", prazo=date(2026, 9, 30), ordem=0),
        Task(titulo="Tarefa próxima sintética", status="a_fazer", prazo=date(2026, 10, 2), client_id=client.id, ordem=0),
        Task(titulo="Tarefa sem prazo sintética", status="a_fazer", ordem=0),
        Task(titulo="Tarefa aguardando cliente sintética", status="aguardando_cliente", ordem=0),
        Task(titulo="Tarefa concluída sintética", status="concluido", ordem=0),
    ]
    tasks.extend(
        Task(titulo=f"Tarefa aberta #{index:02d}", status="a_fazer", ordem=index)
        for index in range(55)
    )
    db.add_all(tasks)
    db.commit()
    original_task_count = db.query(Task).count()
    service = AssistantService(db, provider=None, now=_now)

    reply = service.handle_message(
        message="Olhe o quadro de tarefas e diga o que devo fazer hoje",
        request_id="agenda-complete-board-1",
    )

    assert reply.kind == "text"
    assert "Tarefa atrasada sintética" in reply.message
    assert "Tarefa para hoje sintética" in reply.message
    assert "Tarefa próxima sintética" in reply.message
    assert "Tarefa sem prazo sintética" in reply.message
    assert "Tarefa aguardando cliente sintética" in reply.message
    assert "Tarefa aberta #54" in reply.message
    assert "Tarefa concluída sintética" not in reply.message
    assert "Cliente sintético agenda" in reply.message
    assert "sem prazo" in normalize_text(reply.message)
    assert "atrasada" in normalize_text(reply.message)
    assert "Prioridade sugerida" in reply.message
    assert reply.message.index("Tarefa atrasada sintética") < reply.message.index("Tarefa para hoje sintética")
    assert reply.message.index("Tarefa para hoje sintética") < reply.message.index("Tarefa próxima sintética")
    assert "dependências formais" in reply.message
    assert db.query(Task).count() == original_task_count


def test_agenda_says_nothing_is_due_today_but_lists_open_upcoming_tasks(db):
    db.add(Task(titulo="Próxima tarefa aberta", status="a_fazer", prazo=date(2026, 10, 2), ordem=0))
    db.commit()
    service = AssistantService(db, provider=None, now=_now)

    reply = service.handle_message(
        message="Organize minha agenda para hoje",
        request_id="agenda-no-today-deadline-1",
    )

    assert "não há tarefa com prazo hoje" in reply.message.lower()
    assert "Próxima tarefa aberta" in reply.message
    assert "02/10/2026" in reply.message


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
        message="Estou avaliando a situação da operação e quero uma análise.", request_id="loop-query-1"
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
        message="Preciso de uma tarefa para preparar a proposta.",
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


def test_empty_query_reports_empty_only_after_real_open_task_query(db):
    service = AssistantService(db, provider=None, now=_now)

    reply = service.handle_message(
        message="O que tenho para fazer hoje?", request_id="empty-query-1"
    )

    assert "Consultei o quadro" in reply.message
    assert "não há tarefas abertas" in reply.message.lower()


def test_voice_agenda_uses_the_same_real_task_query_and_keeps_transcript_visible(db):
    db.add(Task(titulo="Tarefa sintética para voz", status="a_fazer", prazo=date(2026, 9, 30), ordem=0))
    db.commit()
    service = AssistantService(db, provider=None, now=_now)

    reply = service.handle_message(
        message="Organize minha agenda",
        request_id="voice-agenda-synthetic-1",
        source="voice",
    )
    history = service.get_history(reply.conversation_id)

    assert "Tarefa sintética para voz" in reply.message
    assert history[0].role == "user"
    assert history[0].content == "Organize minha agenda"


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


def test_ambiguous_client_keeps_draft_and_marks_client_to_confirm(db):
    db.add_all([Client(razao_social="Acme Norte"), Client(razao_social="Acme Sul")])
    db.commit()
    provider = QueueProvider(TaskCreateCommand(title="Fazer vistoria", client="Acme"))
    service = AssistantService(db, provider, now=_now)

    preview = service.handle_message(
        message="Crie uma tarefa de vistoria para a empresa Acme",
        request_id="ambiguous-1",
    )

    assert preview.kind == "confirmation"
    assert "Acme" in preview.fields["cliente"]
    assert "confirmar" in preview.fields["cliente"].lower()
    assert db.query(Task).count() == 0


def test_unknown_client_keeps_free_text_and_does_not_block_confirmed_task(db):
    provider = QueueProvider(TaskCreateCommand(title="Preparar orçamento", client="Roca"))
    service = AssistantService(db, provider, now=_now)

    preview = service.handle_message(
        message="Crie tarefa para preparar orçamento para a empresa Roca",
        request_id="unknown-client-task-1",
    )

    assert preview.kind == "confirmation"
    assert "Roca" in preview.fields["cliente"]
    assert "revisão" in preview.fields["cliente"].lower()
    assert db.query(Task).count() == 0

    created = service.confirm_action(preview.action_id, preview.confirmation_token)
    task = db.get(Task, created.task_id)
    assert task.client_id is None
    assert task.client_name == "Roca"
    assert task.client_link_status == "pending_review"


def test_explicit_manual_task_request_routes_without_ollama_and_waits_for_confirmation(db):
    service = AssistantService(db, provider=None, now=_now)

    preview = service.handle_message(
        message="Crie uma tarefa para preparar orçamento da empresa Roca, sem prazo.",
        request_id="direct-task-no-ollama-1",
    )

    assert preview.kind == "confirmation"
    assert preview.fields["titulo"] == "preparar orçamento"
    assert "Roca" in preview.fields["cliente"]
    assert preview.fields["prazo"] == "Sem prazo"
    assert db.query(Task).count() == 0


def test_direct_task_create_parses_relative_date_and_client_name_from_tail(db):
    service = AssistantService(db, provider=None, now=_now)

    preview = service.handle_message(
        message="Crie uma tarefa para ligar para Roca na sexta.",
        request_id="direct-task-date-client-1",
    )

    assert preview.kind == "confirmation"
    assert preview.fields["titulo"] == "ligar"
    assert preview.fields["cliente"].startswith("Roca")
    assert preview.fields["prazo"] == "02/10/2026"


def test_ambiguous_client_keeps_task_draft_without_repeating_question(db):
    db.add_all([Client(razao_social="Alfa Serviços"), Client(razao_social="Alfa Indústria")])
    db.commit()
    service = AssistantService(
        db,
        QueueProvider(TaskCreateCommand(title="Preparar relatório", client="Alfa")),
        now=_now,
    )

    preview = service.handle_message(
        message="Crie uma tarefa para preparar relatório da empresa Alfa",
        request_id="ambiguous-client-task-1",
    )

    assert preview.kind == "confirmation"
    assert "Alfa" in preview.fields["cliente"]
    assert "confirmar" in preview.fields["cliente"].lower()
    action = db.query(AssistantAction).one()
    assert action.status == "pending"
    assert action.arguments_json["client_id"] is None
    assert action.arguments_json["client_name"] == "Alfa"


def test_client_reply_updates_same_clarification_draft_and_rotates_confirmation(db):
    db.add_all([Client(razao_social="Roca Serviços"), Client(razao_social="Roca Industrial")])
    db.add(User(nome="Carlos", email="carlos@example.test", senha_hash="hash", ativo=True))
    db.commit()
    provider = QueueProvider(
        TaskCreateCommand(title="Preparar relatório", responsible="Carlos inexistente"),
        TaskDraftCorrectionCommand(client="Roca Serviços", responsible="Carlos"),
    )
    service = AssistantService(db, provider, now=_now)
    question = service.handle_message(
        message="Quero uma tarefa para preparar relatório com Carlos inexistente",
        request_id="same-draft-client-1",
    )
    action_before = db.query(AssistantAction).one()
    old_id = action_before.id

    corrected = service.handle_message(
        message="Use Roca Serviços e Carlos",
        request_id="same-draft-client-2",
        conversation_id=question.conversation_id,
    )
    assert "corrigir_tarefa" in provider.calls[1]["allowed_tools"]

    actions = db.query(AssistantAction).all()
    assert len(actions) == 1
    assert actions[0].id == old_id
    assert actions[0].status == "pending"
    assert corrected.kind == "confirmation", corrected.message
    assert corrected.action_id == old_id
    assert corrected.fields["cliente"] == "Roca Serviços"
    assert corrected.confirmation_token != question.confirmation_token


def test_register_company_reply_preserves_task_and_does_not_create_client(db):
    provider = QueueProvider(
        TaskCreateCommand(title="Preparar orçamento", client="Roca"),
        TaskDraftCorrectionCommand(client="Roca"),
    )
    service = AssistantService(db, provider, now=_now)
    preview = service.handle_message(
        message="Crie tarefa para preparar orçamento da empresa Roca",
        request_id="register-company-no-loop-1",
    )
    revised = service.handle_message(
        message="Cadastre a empresa Roca",
        request_id="register-company-no-loop-2",
        conversation_id=preview.conversation_id,
    )

    assert revised.kind == "confirmation"
    assert revised.action_id == preview.action_id
    assert db.query(Client).count() == 0
    assert db.query(Task).count() == 0
    action = db.query(AssistantAction).one()
    assert action.status == "pending"
    assert action.arguments_json["client_name"] == "Roca"


def test_legacy_client_clarification_can_be_recovered_without_reasking(db):
    service = AssistantService(
        db,
        QueueProvider(TaskCreateCommand(title="Preparar orçamento")),
        now=_now,
    )
    initial = service.handle_message(
        message="Crie tarefa para preparar orçamento",
        request_id="legacy-client-loop-1",
    )
    action = db.query(AssistantAction).one()
    action.status = "needs_clarification"
    action.arguments_json = TaskCreateCommand(
        title="Preparar orçamento", client="Roca"
    ).model_dump(mode="json")
    db.add(AssistantMessage(
        conversation_id=initial.conversation_id,
        role="assistant",
        kind="clarification",
        content="Não encontrei o cliente 'roca'. Qual cadastro devo usar?",
        details_json={},
    ))
    db.commit()

    recommended = service.handle_message(
        message="O que você recomenda?",
        request_id="legacy-client-loop-2",
        conversation_id=initial.conversation_id,
    )

    assert recommended.kind == "confirmation"
    assert recommended.action_id == action.id
    assert len(db.query(AssistantAction).all()) == 1
    assert "Roca" in recommended.fields["cliente"]

    registered = service.handle_message(
        message="Cadastre a empresa Roca",
        request_id="legacy-client-loop-3",
        conversation_id=initial.conversation_id,
    )

    assert registered.kind == "confirmation"
    assert registered.action_id == action.id
    assert "não criei nem alterei cadastro" in registered.message.lower()
    assert db.query(Client).count() == 0
    assert db.query(Task).count() == 0

    company = service.handle_message(
        message="Roca",
        request_id="legacy-client-loop-4",
        conversation_id=initial.conversation_id,
    )
    assert company.kind == "confirmation"
    assert company.action_id == action.id
    assert db.query(AssistantAction).count() == 1


def test_correction_updates_existing_pending_draft_and_rotates_confirmation(db):
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
    assert len(actions) == 1
    assert actions[0].status == "pending"
    assert preview.action_id == actions[0].id


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
            content="Preciso de uma análise geral do andamento.",
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
            message="Preciso de uma análise geral do andamento.",
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
    assert "dispon" in reply.message
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
