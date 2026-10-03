from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.assistant.contracts import (
    CancelActionCommand,
    ConversationCommand,
    ConfirmActionCommand,
    TaskDraftCorrectionCommand,
    assistant_command_adapter,
)
from app.assistant.capabilities import CapabilityRegistry
from app.assistant.ollama import _ollama_tools
from app.assistant.provider import ProviderPendingAction, ProviderToolResult
from app.assistant.evidence import validate_execution_claims


@pytest.mark.parametrize(
    ("payload", "expected_type"),
    [
        ({"tool": "confirmar_acao"}, ConfirmActionCommand),
        ({"tool": "cancelar_acao"}, CancelActionCommand),
        (
            {
                "tool": "corrigir_tarefa",
                "title": "Revisar relatorio",
                "due_date": "depois de amanha",
            },
            TaskDraftCorrectionCommand,
        ),
    ],
)
def test_conversation_control_commands_are_typed(payload, expected_type):
    command = assistant_command_adapter.validate_python(payload)

    assert isinstance(command, expected_type)


def test_commands_reject_unexpected_fields():
    with pytest.raises(ValidationError):
        assistant_command_adapter.validate_python(
            {"tool": "confirmar_acao", "sql": "DELETE FROM tasks"}
        )


def test_task_draft_correction_requires_an_explicit_change():
    with pytest.raises(ValidationError):
        TaskDraftCorrectionCommand()


def test_conversation_command_accepts_a_natural_validated_reply():
    command = assistant_command_adapter.validate_python(
        {
            "tool": "responder_conversa",
            "message": "Boa tarde! Posso consultar e criar tarefas no quadro.",
        }
    )

    assert isinstance(command, ConversationCommand)


@pytest.mark.parametrize("message", ["", "x" * 2401])
def test_conversation_command_rejects_empty_or_excessive_replies(message):
    with pytest.raises(ValidationError):
        ConversationCommand(message=message)


@pytest.mark.parametrize(
    "payload",
    [
        {"tool": "consultar_servicos", "execution_status": "in_progress", "pending_only": True},
        {"tool": "registrar_evento_servico", "client": "Cliente A", "event_type": "inspection"},
        {"tool": "corrigir_registro_servico", "event_id": 7, "description": "Inspecao concluida"},
        {"tool": "criar_lembretes_servico", "reminders": [{"title": "Retornar ao cliente"}]},
    ],
)
def test_service_commands_are_typed(payload):
    assert assistant_command_adapter.validate_python(payload).tool == payload["tool"]


@pytest.mark.parametrize(
    "payload",
    [
        {"tool": "consultar_servicos", "sql": "SELECT * FROM service_calls"},
        {"tool": "consultar_servicos", "execution_status": "done"},
        {"tool": "registrar_evento_servico", "service_call_id": 0},
        {"tool": "registrar_evento_servico", "step_changes": [{"step_type": "report", "status": "pending"}] * 6},
        {"tool": "registrar_evento_servico", "step_changes": [{"step_type": "report", "status": "invented"}]},
        {"tool": "corrigir_registro_servico", "event_id": 0},
        {"tool": "criar_lembretes_servico", "reminders": []},
        {"tool": "criar_lembretes_servico", "reminders": [{"title": "T"}] * 6},
        {"tool": "criar_lembretes_servico", "reminders": [{"title": "T", "user_id": 1}]},
    ],
)
def test_service_commands_reject_invalid_or_extraneous_fields(payload):
    with pytest.raises(ValidationError):
        assistant_command_adapter.validate_python(payload)


def test_service_provider_envelopes_accept_only_the_planned_actions():
    assert ProviderToolResult(tool="consultar_servicos", payload={}).tool == "consultar_servicos"
    for action in ("register_service_event", "correct_service_event", "create_service_reminders"):
        assert ProviderPendingAction(action_type=action, status="pending", arguments={}).action_type == action

    with pytest.raises(ValidationError):
        ProviderToolResult(tool="executar_sql", payload={})


def test_ollama_exposes_only_tools_allowed_for_the_current_round():
    allowed = {"consultar_servicos", "registrar_evento_servico", "responder_conversa"}
    names = {entry["function"]["name"] for entry in _ollama_tools(allowed)}
    assert names == allowed
    assert _ollama_tools(set()) == []


def test_service_capabilities_are_available_with_confirmation_for_writes():
    registry = CapabilityRegistry()
    assert registry.get("service_read").state == "available"
    write = registry.get("service_write")
    assert write.state == "available"
    assert "confirm" in write.detail.casefold()
    for name in ("document_write", "finance_write", "email_send", "tax_issue"):
        assert registry.get(name).state != "available"


@pytest.mark.parametrize(
    "message",
    [
        "Não encontrei nenhum chamado para a Alfa.",
        "O serviço foi registrado com sucesso.",
        "Registrei os serviços da Alfa.",
    ],
)
def test_service_claim_variants_require_execution_evidence(message):
    with pytest.raises(ValueError, match="evidencia|confirmado"):
        validate_execution_claims(message, tool_results=())


@pytest.mark.parametrize(
    "message",
    [
        "Não foram encontrados serviços para a Alfa.",
        "O chamado da Alfa foi registrado com sucesso.",
        "O chamado #1 foi concluído com sucesso.",
    ],
)
def test_passive_service_claims_require_execution_evidence(message):
    with pytest.raises(ValueError, match="evidencia|confirmado"):
        validate_execution_claims(message, tool_results=())


def test_service_query_cannot_claim_empty_when_result_contains_records():
    result = ProviderToolResult(
        tool="consultar_servicos", evidence_id="services:test", state="success",
        payload={"count": 1, "service_calls": [{"id": 1, "client_name": "Alfa"}]},
    )
    with pytest.raises(ValueError, match="vazi|encontr"):
        validate_execution_claims(
            "Consultei os serviços, mas não encontrei nenhum chamado para a Alfa.",
            tool_results=(result,),
        )


def test_explicit_reminder_task_is_not_mistaken_for_service_write():
    from app.assistant.contracts import TaskCreateCommand
    from app.assistant.ollama import _validate_tool_scope

    for message in (
        "Crie uma tarefa para registrar o serviço da Alfa.",
        "Crie um lembrete para verificar os chamados amanhã.",
    ):
        command = _validate_tool_scope(
            TaskCreateCommand(title="Registrar serviço"), current_message=message,
            allowed_tools={"criar_tarefa"},
        )
        assert isinstance(command, TaskCreateCommand)


def test_tool_arguments_cannot_override_the_authorized_discriminator():
    import httpx
    from app.assistant.ollama import _validated_command

    response = httpx.Response(200, json={"message": {"tool_calls": [{"function": {
        "name": "responder_conversa",
        "arguments": {"tool": "registrar_evento_servico", "client": "Alfa"},
    }}]}})
    with pytest.raises(ValueError, match="ferramenta|tool"):
        _validated_command(response, allowed_tools={"responder_conversa"})


def test_service_result_date_can_be_repeated_in_brazilian_format():
    from app.assistant.contracts import ConversationCommand
    from app.assistant.ollama import _validate_conversation_grounding

    result = ProviderToolResult(
        tool="consultar_servicos", evidence_id="services:test", state="success",
        payload={"count": 1, "service_calls": [{"id": 1, "opened_on": "2026-10-02"}]},
    )
    command = ConversationCommand(message="Consultei o chamado #1, aberto em 02/10/2026.")
    grounded = _validate_conversation_grounding(
        command, tool_results=(result,), current_message="Quando foi aberto o chamado?",
    )
    assert grounded.message == command.message


def test_service_result_datetime_date_can_be_repeated_in_brazilian_format():
    from app.assistant.contracts import ConversationCommand
    from app.assistant.ollama import _validate_conversation_grounding

    result = ProviderToolResult(
        tool="consultar_servicos", evidence_id="services:test", state="success",
        payload={"count": 1, "service_calls": [{
            "id": 1, "technically_completed_at": "2026-10-02T00:00:00",
        }]},
    )
    command = ConversationCommand(message="O chamado #1 teve conclusão técnica em 02/10/2026.")
    grounded = _validate_conversation_grounding(
        command, tool_results=(result,), current_message="Quando foi concluído?",
    )
    assert grounded.message == command.message


@pytest.mark.parametrize(
    "message",
    [
        "O chamado #1 tem execução concluída.",
        "No chamado #1 o relatório está concluído.",
        "O chamado #99 está em andamento.",
    ],
)
def test_service_status_claims_must_match_the_consulted_projection(message):
    from app.assistant.contracts import ConversationCommand
    from app.assistant.ollama import _validate_conversation_grounding

    result = ProviderToolResult(
        tool="consultar_servicos", evidence_id="services:projection", state="success",
        payload={"count": 1, "service_calls": [{
            "id": 1, "execution_status": "not_started", "administrative_status": "open",
            "workflow_steps": [{"step_type": "report", "status": "pending"}],
        }]},
    )
    with pytest.raises(ValueError, match="chamado|tecnica|administrativo|estado"):
        _validate_conversation_grounding(
            ConversationCommand(message=message), tool_results=(result,),
            current_message="Mostre o chamado e sua situação.",
        )


@pytest.mark.parametrize(
    "message",
    [
        "A inspeção da Alfa Serviços Sintética ainda não foi executada.",
        "O chamado da Alfa Serviços Sintética está aberto, com a inspeção de balança ainda não iniciada.",
        "Não há rascunho de tarefa criado.",
    ],
)
def test_service_query_cannot_confuse_event_history_or_assert_unqueried_board_state(message):
    from app.assistant.contracts import ConversationCommand
    from app.assistant.ollama import _validate_conversation_grounding

    result = ProviderToolResult(
        tool="consultar_servicos", evidence_id="services:event-history", state="success",
        payload={"count": 1, "service_calls": [{
            "id": 1, "client": "Alfa Serviços Sintética", "execution_status": "not_started",
            "administrative_status": "open", "effective_event_count": 1,
            "event_types": ["inspection"], "recent_events": [{
                "event_type": "inspection", "description": "Inspeção sintética realizada.",
            }], "workflow_steps": [],
        }]},
    )
    with pytest.raises(ValueError):
        _validate_conversation_grounding(
            ConversationCommand(message=message), tool_results=(result,),
            current_message="Consulte os chamados da Alfa Serviços Sintética.",
        )
