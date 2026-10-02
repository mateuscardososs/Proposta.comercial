from __future__ import annotations

from datetime import date, datetime
import json
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.assistant.contracts import (
    ConversationCommand, ServiceDraftCorrectionCommand, ServiceEventDraftCommand,
    ServiceQueryCommand, ServiceReminderDraftCommand, ServiceReminderItemCommand,
    ServiceStepChangeCommand,
    TaskCreateCommand, assistant_command_adapter,
)
from app.assistant.evidence import validate_execution_claims
from app.assistant.ollama import OllamaProvider, _prompt_tool_results, _validate_tool_scope
from app.assistant.provider import ProviderMessage, ProviderPendingAction, ProviderToolResult
from app.assistant.service import AssistantService
from app.db import Base, ensure_service_history_guards_for_engine
from app.models import AssistantAction, AssistantMessage, Client, ServiceCall, ServiceEvent, ServiceWorkflowTransition, ServiceTaskLink, Task


@pytest.fixture(autouse=True)
def reset_database():
    yield


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'assistant-services.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    ensure_service_history_guards_for_engine(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


class QueueProvider:
    def __init__(self, *commands):
        self.commands = list(commands)
        self.calls = []

    def interpret(self, messages, **kwargs):
        self.calls.append(kwargs)
        return self.commands.pop(0)


def service(db, *commands):
    return AssistantService(
        db, QueueProvider(*commands),
        now=lambda: datetime(2026, 10, 2, 9, tzinfo=ZoneInfo("America/Recife")),
    )


def client(db, name="Alfa"):
    item = Client(razao_social=name)
    db.add(item)
    db.commit()
    return item


def test_inspection_draft_does_not_claim_execution(db):
    client(db)
    assistant = service(db, ServiceEventDraftCommand(
        client="Alfa", event_type="execution_completed", execution_completed_explicitly=True,
        description="Inspecionei a balança", summary="Balança",
    ))
    draft = assistant.handle_message(
        message="Fui à empresa Alfa, mas só fiz uma inspeção na balança.", request_id="inspection-1")
    assert draft.kind == "confirmation"
    assert draft.fields["evento"] == "Inspeção"
    assert draft.fields["execucao"] == "Não iniciada"
    assert db.query(ServiceEvent).count() == 0
    result = assistant.confirm_action(draft.action_id, draft.confirmation_token)
    assert result.kind == "success"
    assert db.query(ServiceEvent).one().event_type == "inspection"
    assert db.query(ServiceCall).one().execution_status == "not_started"


def test_finished_repair_asks_only_for_missing_client_or_call(db):
    assistant = service(db, ServiceEventDraftCommand(event_type="execution_completed", execution_completed_explicitly=True))
    reply = assistant.handle_message(message="Terminei o conserto.", request_id="finished-1")
    assert reply.kind == "clarification"
    assert "cliente" in reply.message.lower()
    assert db.query(ServiceCall).count() == 0


def test_ambiguous_client_asks_short_question(db):
    client(db, "Alfa Norte")
    client(db, "Alfa Sul")
    assistant = service(db, ServiceEventDraftCommand(client="Alfa", event_type="inspection"))
    reply = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="ambiguous-client")
    assert reply.kind == "clarification"
    assert "Alfa Norte" in reply.message and "Alfa Sul" in reply.message
    assert db.query(ServiceCall).count() == 0


def test_missing_date_proposes_today_with_absolute_date(db):
    client(db)
    assistant = service(db, ServiceEventDraftCommand(client="Alfa", event_type="inspection"))
    reply = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="today-default")
    assert reply.kind == "confirmation"
    assert reply.fields["data"] == "02/10/2026"
    assert db.query(ServiceCall).count() == 0


def test_cancel_service_draft_writes_nothing(db):
    client(db)
    assistant = service(db, ServiceEventDraftCommand(client="Alfa", event_type="inspection"))
    draft = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="cancel-draft")
    cancelled = assistant.cancel_action(draft.action_id, draft.confirmation_token)
    assert cancelled.kind == "text"
    assert db.query(ServiceCall).count() == db.query(ServiceEvent).count() == 0


def test_confirmed_service_action_is_idempotent(db):
    client(db)
    assistant = service(db, ServiceEventDraftCommand(client="Alfa", event_type="inspection"))
    draft = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="idempotent-service")
    first = assistant.confirm_action(draft.action_id, draft.confirmation_token)
    second = assistant.confirm_action(draft.action_id, draft.confirmation_token)
    assert first == second
    assert db.query(ServiceEvent).count() == db.query(ServiceCall).count() == 1


def test_administrative_steps_append_each_confirmed_transition(db):
    client(db)
    assistant = service(
        db,
        ServiceEventDraftCommand(client="Alfa", event_type="inspection", description="Inspeção", summary="Balança",
                                 step_changes=[ServiceStepChangeCommand(step_type="report", status="pending")]),
        ServiceEventDraftCommand(client="Alfa", event_type="inspection", description="Inspeção", summary="Balança",
                                 step_changes=[ServiceStepChangeCommand(step_type="report", status="waiting_customer")]),
    )
    first = assistant.handle_message(message="Fiz inspeção na Alfa, falta o relatório.", request_id="step-pending")
    assistant.confirm_action(first.action_id, first.confirmation_token)
    second = assistant.handle_message(message="Fiz outra inspeção na Alfa; o relatório está aguardando aprovação do cliente.", request_id="step-waiting", conversation_id=first.conversation_id)
    assert second.kind == "confirmation", second.message
    assistant.confirm_action(second.action_id, second.confirmation_token)
    transitions = db.query(ServiceWorkflowTransition).order_by(ServiceWorkflowTransition.id).all()
    assert [(row.previous_status, row.new_status) for row in transitions] == [
        ("unknown", "pending"), ("pending", "waiting_customer"),
    ]
    assert db.query(ServiceEvent).count() == 2


def test_correction_is_append_only_and_reprojects_service(db):
    client(db)
    assistant = service(
        db,
        ServiceEventDraftCommand(client="Alfa", event_type="execution_completed", execution_completed_explicitly=True,
                                 description="Consertei a balança", summary="Balança"),
        ServiceDraftCorrectionCommand(event_id=1, event_type="inspection", description="Foi só inspeção"),
    )
    draft = assistant.handle_message(message="Terminei o conserto da balança na Alfa.", request_id="correction-original")
    assistant.confirm_action(draft.action_id, draft.confirmation_token)
    correction = assistant.handle_message(
        message="Corrigindo: foi apenas inspeção, não consertei.", request_id="correction-fix",
        conversation_id=draft.conversation_id,
    )
    assert correction.kind == "confirmation", correction.message
    assistant.confirm_action(correction.action_id, correction.confirmation_token)
    call = db.query(ServiceCall).one()
    events = db.query(ServiceEvent).order_by(ServiceEvent.id).all()
    assert events[0].event_type == "execution_completed"
    assert events[1].event_type == "correction"
    assert call.execution_status == "not_started"


def test_correcting_unconfirmed_event_invalidates_old_confirmation(db):
    client(db)
    assistant = service(
        db,
        ServiceEventDraftCommand(client="Alfa", event_type="execution_completed", execution_completed_explicitly=True,
                                 description="Consertei a balança", summary="Balança"),
        ServiceDraftCorrectionCommand(event_type="inspection"),
    )
    original = assistant.handle_message(message="Terminei o conserto da balança na Alfa.", request_id="draft-before-correction")
    revised = assistant.handle_message(
        message="Na verdade, foi só inspeção.", request_id="draft-correction",
        conversation_id=original.conversation_id,
    )
    assert revised.kind == "confirmation"
    assert revised.fields["evento"] == "Inspeção"
    with pytest.raises(ValueError, match="cancelada"):
        assistant.confirm_action(original.action_id, original.confirmation_token)
    assistant.confirm_action(revised.action_id, revised.confirmation_token)
    assert db.query(ServiceEvent).one().event_type == "inspection"
    assert db.query(ServiceCall).one().execution_status == "not_started"


def test_confirmed_service_reminders_create_once_and_return_task_links(db):
    client(db)
    # Store a real presentation record so the reminder command must resolve a shown call.
    assistant = service(db, ServiceEventDraftCommand(client="Alfa", event_type="inspection", summary="Balança", description="Inspeção"))
    draft = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="reminder-base")
    assistant.confirm_action(draft.action_id, draft.confirmation_token)
    db.add(AssistantMessage(
        conversation_id=draft.conversation_id, role="assistant", kind="text", content="Chamado #1",
        details_json={"service_calls": [{"id": 1}]},
    ))
    db.commit()
    reminder_assistant = service(db, ServiceReminderDraftCommand(
        service_call_id=1, reminders=[ServiceReminderItemCommand(
            title="Preparar relatório", description="Chamado #1", step_type="report", due_date="amanhã",
        )],
    ))
    pending = reminder_assistant.handle_message(
        message="Crie um lembrete Preparar relatório para o chamado #1 para amanhã.",
        request_id="reminder-create", conversation_id=draft.conversation_id,
    )
    assert pending.kind == "confirmation", pending.message
    assert pending.fields["lembretes"] == "Preparar relatório — 03/10/2026"
    first = reminder_assistant.confirm_action(pending.action_id, pending.confirmation_token)
    second = reminder_assistant.confirm_action(pending.action_id, pending.confirmation_token)
    assert first.kind == "success" and first.task_urls == ["/web/board/1/edit"]
    assert second == first
    assert db.query(Task).count() == db.query(ServiceTaskLink).count() == 1
    assert db.query(Task).one().prazo == date(2026, 10, 3)
    assert db.get(AssistantAction, draft.action_id).result_json["service_call_id"] == db.query(ServiceCall).one().id


def test_service_query_uses_real_evidence_and_bounded_result(db):
    client(db)
    assistant = service(db,
        ServiceEventDraftCommand(client="Alfa", event_type="inspection"),
        ServiceQueryCommand(client="Alfa"),
        ConversationCommand(message="Encontrei um chamado da Alfa em aberto."),
    )
    draft = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="query-seed")
    assistant.confirm_action(draft.action_id, draft.confirmation_token)
    reply = assistant.handle_message(message="Quais serviços da Alfa estão em aberto?", request_id="service-query", conversation_id=draft.conversation_id)
    assert reply.kind == "text"
    assert "Alfa" in reply.message
    assert assistant.provider.calls[-1]["tool_results"][0].tool == "consultar_servicos"
    assert assistant.provider.calls[-1]["tool_results"][0].payload["count"] == 1
    assert assistant.provider.calls[-1]["allowed_tools"] == {"responder_conversa"}


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("A resposta contradiz o evento de inspecao registrado.", "service_event_conflict"),
        ("A resposta afirmou estado de tarefa sem consulta ao quadro.", "unqueried_task_state"),
    ],
)
def test_service_grounding_repairs_have_specific_safe_hints(message, expected):
    from app.assistant.ollama import _repair_hint, _repair_reason

    reason = _repair_reason(ValueError(message))
    assert reason == expected
    assert _repair_hint(reason)


def test_empty_service_answer_repair_hint_uses_only_the_verified_count():
    from app.assistant.ollama import _repair_hint

    result = ProviderToolResult(tool="consultar_servicos", state="success", payload={"count": 1})
    hint = _repair_hint("service_result_conflict", (result,))
    assert "retornou 1 chamado" in hint
    assert "Alfa" not in hint


def test_single_open_call_is_shown_in_confirmation(db):
    client(db)
    assistant = service(db,
        ServiceEventDraftCommand(client="Alfa", event_type="inspection"),
        ServiceEventDraftCommand(client="Alfa", event_type="execution_started"),
    )
    first = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="single-first")
    assistant.confirm_action(first.action_id, first.confirmation_token)
    second = assistant.handle_message(message="Comecei a execução na Alfa.", request_id="single-second", conversation_id=first.conversation_id)
    assert second.kind == "confirmation"
    assert f"#{db.query(ServiceCall).one().id}" in second.fields["chamado"]
    assistant.confirm_action(second.action_id, second.confirmation_token)
    assert db.query(ServiceCall).count() == 1
    assert db.query(ServiceEvent).count() == 2


def test_force_new_call_does_not_reuse_open_call(db):
    client(db)
    assistant = service(db,
        ServiceEventDraftCommand(client="Alfa", event_type="inspection"),
        ServiceEventDraftCommand(client="Alfa", event_type="inspection", force_new_call=True),
    )
    first = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="new-first")
    assistant.confirm_action(first.action_id, first.confirmation_token)
    second = assistant.handle_message(message="Novo chamado: fiz outra inspeção na Alfa.", request_id="new-second", conversation_id=first.conversation_id)
    assert second.fields["chamado"] == "Novo chamado"
    assistant.confirm_action(second.action_id, second.confirmation_token)
    assert db.query(ServiceCall).count() == 2


def test_multiple_open_calls_ask_which_call(db):
    client(db)
    assistant = service(db,
        ServiceEventDraftCommand(client="Alfa", event_type="inspection"),
        ServiceEventDraftCommand(client="Alfa", event_type="inspection", force_new_call=True),
        ServiceEventDraftCommand(client="Alfa", event_type="execution_started"),
    )
    first = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="multi-first")
    assistant.confirm_action(first.action_id, first.confirmation_token)
    second = assistant.handle_message(message="Novo chamado: outra inspeção na Alfa.", request_id="multi-second", conversation_id=first.conversation_id)
    assistant.confirm_action(second.action_id, second.confirmation_token)
    question = assistant.handle_message(message="Comecei a execução na Alfa.", request_id="multi-third", conversation_id=first.conversation_id)
    assert question.kind == "clarification"
    assert "Qual chamado" in question.message
    assert db.query(ServiceEvent).count() == 2


def test_retry_after_commit_reconciles_service_result(db):
    client(db)
    assistant = service(db, ServiceEventDraftCommand(client="Alfa", event_type="inspection"))
    draft = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="reconcile")
    result = assistant.confirm_action(draft.action_id, draft.confirmation_token)
    replay = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="reconcile")
    assert replay == result
    assert db.query(ServiceCall).count() == db.query(ServiceEvent).count() == 1


def test_relative_date_is_resolved_in_local_timezone(db):
    client(db)
    assistant = service(db, ServiceEventDraftCommand(client="Alfa", event_type="inspection", occurred_on="ontem"))
    draft = assistant.handle_message(message="Ontem fiz inspeção na Alfa.", request_id="relative-date")
    assert draft.fields["data"] == "01/10/2026"


def test_direct_confirmation_uses_same_service_action(db):
    client(db)
    assistant = service(db, ServiceEventDraftCommand(client="Alfa", event_type="inspection"))
    draft = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="direct-draft")
    result = assistant.handle_message(message="Confirmo", request_id="direct-confirm", conversation_id=draft.conversation_id)
    assert result.kind == "success"
    assert db.query(ServiceEvent).count() == 1


def test_multiple_open_calls_can_be_resolved_by_presented_ordinal(db):
    client(db)
    assistant = service(db,
        ServiceEventDraftCommand(client="Alfa", event_type="inspection"),
        ServiceEventDraftCommand(client="Alfa", event_type="inspection", force_new_call=True),
        ServiceEventDraftCommand(client="Alfa", event_type="execution_started"),
        ServiceEventDraftCommand(),
    )
    first = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="ordinal-first")
    assistant.confirm_action(first.action_id, first.confirmation_token)
    second = assistant.handle_message(message="Novo chamado: outra inspeção na Alfa.", request_id="ordinal-second", conversation_id=first.conversation_id)
    assistant.confirm_action(second.action_id, second.confirmation_token)
    question = assistant.handle_message(message="Comecei a execução na Alfa.", request_id="ordinal-third", conversation_id=first.conversation_id)
    assert question.kind == "clarification"
    selected = assistant.handle_message(message="O segundo.", request_id="ordinal-fourth", conversation_id=first.conversation_id)
    assert selected.kind == "confirmation"
    assert f"#{db.query(ServiceCall).order_by(ServiceCall.id.asc()).first().id}" in selected.fields["chamado"]
    assert db.query(ServiceEvent).count() == 2


def test_model_supplied_unmentioned_call_id_is_not_accepted(db):
    client(db)
    assistant = service(db,
        ServiceEventDraftCommand(client="Alfa", event_type="inspection"),
        ServiceEventDraftCommand(client="Alfa", service_call_id=1, event_type="execution_started"),
    )
    first = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="id-first")
    assistant.confirm_action(first.action_id, first.confirmation_token)
    second = assistant.handle_message(message="Comecei a execução na Alfa.", request_id="id-second", conversation_id=first.conversation_id)
    assert second.kind == "clarification"
    assert db.query(ServiceEvent).count() == 1


def test_service_query_does_not_apply_model_invented_client_filter(db):
    client(db, "Alfa")
    client(db, "Beta")
    assistant = service(db,
        ServiceEventDraftCommand(client="Alfa", event_type="inspection"),
        ServiceQueryCommand(client="Beta"),
        ConversationCommand(message="Encontrei um chamado em aberto."),
    )
    draft = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="filter-seed")
    assistant.confirm_action(draft.action_id, draft.confirmation_token)
    reply = assistant.handle_message(message="Quais serviços estão em aberto?", request_id="filter-query", conversation_id=draft.conversation_id)
    assert reply.kind == "text"
    assert assistant.provider.calls[-1]["tool_results"][0].payload["count"] == 1


def test_missing_client_clarification_keeps_finished_work_context(db):
    client(db)
    assistant = service(db,
        ServiceEventDraftCommand(event_type="execution_completed", execution_completed_explicitly=True),
        ServiceEventDraftCommand(client="Alfa"),
    )
    question = assistant.handle_message(message="Terminei o conserto.", request_id="context-first")
    assert question.kind == "clarification"
    draft = assistant.handle_message(message="Foi na Alfa.", request_id="context-second", conversation_id=question.conversation_id)
    assert draft.kind == "confirmation"
    assert draft.fields["evento"] == "Execução concluída"
    assert db.query(ServiceEvent).count() == 0


def test_only_spoken_administrative_step_is_in_draft_and_event(db):
    client(db)
    assistant = service(db, ServiceEventDraftCommand(
        client="Alfa", event_type="inspection", step_changes=[
            ServiceStepChangeCommand(step_type="report", status="pending"),
            ServiceStepChangeCommand(step_type="proposal", status="completed"),
        ],
    ))
    draft = assistant.handle_message(message="Fiz inspeção na Alfa; relatório pendente.", request_id="spoken-step")
    assert draft.kind == "confirmation"
    assert "Relatório" in draft.fields["etapas"]
    assert "Proposta" not in draft.fields["etapas"]
    assistant.confirm_action(draft.action_id, draft.confirmation_token)
    assert [(step.step_type, step.status) for step in db.query(ServiceCall).one().workflow_steps if step.status != "unknown"] == [("report", "pending")]


def test_service_request_is_not_converted_to_task(db):
    client(db)
    assistant = service(db, TaskCreateCommand(title="Inspeção na Alfa"))
    reply = assistant.handle_message(message="Registre a inspeção na Alfa.", request_id="no-task-substitution")
    assert reply.kind == "error"
    assert db.query(ServiceCall).count() == 0


def test_pode_registrar_direct_control_confirms_service(db):
    client(db)
    assistant = service(db, ServiceEventDraftCommand(client="Alfa", event_type="inspection"))
    draft = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="direct-register-draft")
    result = assistant.handle_message(message="Pode registrar", request_id="direct-register-confirm", conversation_id=draft.conversation_id)
    assert result.kind == "success"
    assert db.query(ServiceEvent).count() == 1


def test_direct_cancel_service_draft_writes_nothing(db):
    client(db)
    assistant = service(db, ServiceEventDraftCommand(client="Alfa", event_type="inspection"))
    draft = assistant.handle_message(message="Fiz inspeção na Alfa.", request_id="direct-cancel-draft")
    result = assistant.handle_message(message="Cancela", request_id="direct-cancel-control", conversation_id=draft.conversation_id)
    assert result.kind == "text"
    assert db.query(ServiceCall).count() == db.query(ServiceEvent).count() == 0


def test_model_invented_event_type_asks_for_clarification(db):
    client(db)
    assistant = service(db, ServiceEventDraftCommand(client="Alfa", event_type="inspection"))
    reply = assistant.handle_message(message="Fui à Alfa.", request_id="invented-event")
    assert reply.kind == "clarification"
    assert db.query(ServiceCall).count() == 0


def test_cannot_claim_service_query_without_tool_evidence():
    with pytest.raises(ValueError, match="servico.*evidencia"):
        validate_execution_claims("Consultei os serviços e encontrei um chamado.", tool_results=())


def test_cannot_claim_service_registration_before_confirmed_result():
    query = ProviderToolResult(
        tool="consultar_servicos", state="success", payload={"count": 1, "service_calls": []}
    )
    with pytest.raises(ValueError, match="registro.*confirm"):
        validate_execution_claims("Registrei o serviço da Alfa.", tool_results=(query,))


def test_failed_service_query_cannot_be_called_successful():
    failed = ProviderToolResult(tool="consultar_servicos", state="failed", payload={"count": 0})
    with pytest.raises(ValueError, match="bem-sucedida"):
        validate_execution_claims("Consultei os serviços de hoje.", tool_results=(failed,))


@pytest.mark.parametrize(
    "claim",
    [
        "Marquei a conta como paga.",
        "Atualizei o documento.",
        "Emiti a nota fiscal.",
        "Enviei o e-mail.",
    ],
)
def test_finance_document_tax_and_email_writes_remain_blocked(claim):
    service_result = ProviderToolResult(
        tool="consultar_servicos", state="success", payload={"count": 1, "service_calls": []}
    )
    with pytest.raises(ValueError, match="sem evidencia"):
        validate_execution_claims(claim, tool_results=(service_result,))


def test_service_result_sent_to_ollama_contains_at_most_ten_compact_calls():
    calls = [
        {
            "id": number,
            "client": "Alfa",
            "summary": "Inspecao",
            "execution_status": "in_progress",
            "administrative_status": "open",
            "next_pending_step": "report",
            "opened_on": "2026-10-02",
            "technically_completed_at": None,
            "administratively_closed_at": None,
            "event_types": ["inspection"],
            "effective_event_count": 1,
            "recent_events": [{"event_type": "inspection", "occurred_on": "2026-10-02", "description": "x" * 400}],
            "workflow_steps": [{"step_type": "report", "status": "pending"}],
            "events": [{"description": "historico confidencial"}],
        }
        for number in range(12)
    ]
    result = ProviderToolResult(
        tool="consultar_servicos", state="success", payload={"count": 12, "service_calls": calls}
    )

    compact = _prompt_tool_results((result,))[0]["payload"]["service_calls"]

    assert len(compact) == 10
    assert compact[0]["id"] == 0
    assert "events" not in compact[0]
    assert set(compact[0]) == {
        "id", "client", "summary", "execution_status", "administrative_status",
        "next_pending_step", "opened_on", "technically_completed_at", "administratively_closed_at",
        "event_types", "effective_event_count", "recent_events", "workflow_steps",
    }
    assert compact[0]["recent_events"][0]["description"] == "x" * 240
    assert compact[0]["workflow_steps"] == [{"step_type": "report", "status": "pending"}]


def test_large_service_result_is_bounded_before_ollama_prompt():
    item = {
        "id": 1,
        "client": "C" * 2000,
        "summary": "S" * 5000,
        "next_pending_step": "P" * 2000,
    }
    result = ProviderToolResult(
        tool="consultar_servicos", state="success",
        payload={"count": 20, "service_calls": [item] * 20, "full_history": "H" * 20000},
    )
    compact = _prompt_tool_results((result,))[0]["payload"]
    assert len(str(compact)) < 6500
    assert "full_history" not in compact


def test_service_command_is_not_treated_as_an_unavailable_operation():
    command = assistant_command_adapter.validate_python(
        {"tool": "registrar_evento_servico", "client": "Alfa", "event_type": "inspection"}
    )
    assert _validate_tool_scope(command, current_message="Registre o atendimento da Alfa.") == command


def test_service_clarification_requires_service_tools_in_the_round():
    clarification = ConversationCommand(message="Qual cliente devo usar para o atendimento?")
    with pytest.raises(ValueError, match="limitacao"):
        _validate_tool_scope(clarification, current_message="Cadastre um atendimento de inspeção.")
    assert _validate_tool_scope(
        clarification,
        current_message="Cadastre um atendimento de inspeção.",
        allowed_tools={"registrar_evento_servico", "responder_conversa"},
    ) == clarification


def test_successful_service_query_allows_natural_answer_without_repeating_tool():
    command = ConversationCommand(message="O chamado está aberto e falta o relatório.")
    result = ProviderToolResult(tool="consultar_servicos", state="success", payload={"count": 1})
    assert _validate_tool_scope(
        command,
        current_message="Consulte os chamados e diga o que está pendente.",
        allowed_tools={"responder_conversa"},
        tool_results=(result,),
    ) == command


def test_financial_request_cannot_be_substituted_with_a_task():
    with pytest.raises(ValueError, match="indisponivel"):
        _validate_tool_scope(TaskCreateCommand(title="Pagar conta"), current_message="Pague a conta.")


def test_explicit_task_about_a_service_is_not_blocked():
    command = TaskCreateCommand(title="Ligar sobre o servico")
    assert _validate_tool_scope(command, current_message="Crie uma tarefa para acompanhar o serviço.") == command


def test_ollama_describes_service_pending_action_as_service_draft():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "Qual foi a data?"}})

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434", model="local-test",
        connect_timeout=1, read_timeout=1, transport=httpx.MockTransport(handler),
    )
    provider.interpret(
        [ProviderMessage(role="user", content="Na verdade, foi ontem.")],
        today=date(2026, 10, 2), timezone="America/Recife",
        pending_action=ProviderPendingAction(
            action_type="register_service_event", status="pending", arguments={"event_type": "inspection"},
        ),
        allowed_tools={"responder_conversa", "corrigir_registro_servico"},
    )

    envelope = captured["payload"]["messages"][1]["content"]
    assert "rascunho de servico" in envelope
    assert "chame corrigir_registro_servico" in envelope
    assert "rascunho de tarefa" not in envelope
