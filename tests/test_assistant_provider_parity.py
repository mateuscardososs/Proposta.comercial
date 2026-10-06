from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.assistant.contracts import (
    assistant_command_adapter,
)
from app.assistant.gemini import GeminiProvider, _gemini_function_declarations
from app.assistant.ollama import (
    DEFAULT_TOOL_NAMES,
    SERVICE_TOOLS,
    TOOL_DEFINITIONS,
    OllamaProvider,
    _ollama_tools,
)
from app.assistant.provider import ProviderMessage, ProviderResponseError
from app.assistant.service import AssistantService
from app.models import (
    AssistantAction,
    AssistantMessage,
    Client,
    ServiceCall,
    ServiceEvent,
    Task,
)

TODAY = date(2026, 10, 6)
NOW = datetime(2026, 10, 6, 9, 0, tzinfo=ZoneInfo("America/Recife"))

VALID_ARGUMENTS: dict[str, dict[str, object]] = {
    "responder_conversa": {"message": "Posso ajudar com isso."},
    "consultar_tarefas": {"priorities": True, "limit": 10},
    "consultar_emails": {"period": "week", "category": "customer_quote_request"},
    "consultar_servicos": {"pending_only": True},
    "registrar_evento_servico": {
        "client": "Alfa",
        "event_type": "inspection",
        "summary": "Inspeção da balança",
        "description": "Foi feita uma inspeção.",
        "step_changes": [{"step_type": "report", "status": "pending"}],
    },
    "corrigir_registro_servico": {
        "event_id": 7,
        "event_type": "inspection",
        "description": "Corrige para visita de inspeção.",
    },
    "criar_lembretes_servico": {
        "service_call_id": 7,
        "reminders": [{"title": "Preparar relatório", "step_type": "report"}],
    },
    "criar_tarefa": {"title": "Revisar proposta", "due_date": "amanhã", "client": "Alfa"},
    "corrigir_tarefa": {"title": "Revisar relatório"},
    "confirmar_acao": {},
    "cancelar_acao": {},
    "fora_do_escopo": {"message": "Não posso executar isso."},
}


def _http_response(provider_name: str, name: str, arguments: dict[str, object]) -> httpx.Response:
    if provider_name == "gemini":
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"functionCall": {"name": name, "args": arguments}}]
                        }
                    }
                ]
            },
        )
    return httpx.Response(
        200,
        json={
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
            }
        },
    )


def _make_provider(provider_name, responses, captured=None):
    remaining = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(json.loads(request.content))
        response = remaining.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    transport = httpx.MockTransport(handler)
    if provider_name == "gemini":
        return GeminiProvider(
            api_key="synthetic-test-key",
            model="synthetic-test-model",
            connect_timeout=1,
            read_timeout=5,
            transport=transport,
        )
    return OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="synthetic-test-model",
        connect_timeout=1,
        read_timeout=5,
        transport=transport,
    )


PROVIDERS = ["ollama", "gemini"]


def test_gemini_and_ollama_expose_identical_complete_tool_contracts():
    all_tools = DEFAULT_TOOL_NAMES | SERVICE_TOOLS
    ollama_tools = {
        item["function"]["name"]: item["function"]["parameters"]
        for item in _ollama_tools(all_tools)
    }
    gemini_tools = {
        item["name"]: item["parameters"] for item in _gemini_function_declarations(all_tools)
    }

    expected_names = {name for name, _description, _contract in TOOL_DEFINITIONS}
    assert set(ollama_tools) == set(gemini_tools) == expected_names
    assert len(expected_names) == 12
    assert all(isinstance(schema, dict) and schema.get("type") == "object" for schema in gemini_tools.values())


@pytest.mark.parametrize("provider_name", PROVIDERS)
@pytest.mark.parametrize("tool_name", sorted(VALID_ARGUMENTS))
def test_each_provider_returns_existing_typed_command_for_every_assistant_tool(provider_name, tool_name):
    arguments = VALID_ARGUMENTS[tool_name]
    provider = _make_provider(
        provider_name,
        [_http_response(provider_name, tool_name, arguments)],
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Pedido sintético de teste.")],
        today=TODAY,
        timezone="America/Recife",
        allowed_tools={tool_name},
    )

    expected = assistant_command_adapter.validate_python({"tool": tool_name, **arguments})
    assert type(command) is type(expected)
    assert command.model_dump() == expected.model_dump()


@pytest.mark.parametrize("provider_name", PROVIDERS)
@pytest.mark.parametrize(
    ("tool_name", "invalid_arguments"),
    [
        ("consultar_emails", {"category": "financial_action_not_supported"}),
        ("criar_tarefa", {"title": "x" * 256}),
        ("corrigir_tarefa", {}),
        ("criar_lembretes_servico", {"reminders": [{}]}),
    ],
)
def test_each_provider_rejects_invalid_contract_arguments(provider_name, tool_name, invalid_arguments):
    invalid = _http_response(provider_name, tool_name, invalid_arguments)
    provider = _make_provider(provider_name, [invalid, invalid])

    with pytest.raises(ProviderResponseError):
        provider.interpret(
            [ProviderMessage(role="user", content="Pedido sintético de teste.")],
            today=TODAY,
            timezone="America/Recife",
            allowed_tools={tool_name},
        )


@pytest.mark.parametrize("provider_name", PROVIDERS)
def test_create_correct_confirm_retry_history_and_cancel_are_provider_parity(provider_name, db):
    captured: list[dict[str, object]] = []
    provider = _make_provider(
        provider_name,
        [
            _http_response(provider_name, "criar_tarefa", {"title": "Revisar proposta", "client": "Alfa"}),
            _http_response(provider_name, "corrigir_tarefa", {"title": "Revisar relatório"}),
        ],
        captured,
    )
    service = AssistantService(db, provider, now=lambda: NOW)

    preview = service.handle_message(
        message="Preciso registrar uma atividade do quadro para a Alfa.",
        request_id=f"{provider_name}-parity-create",
        source="voice",
    )
    assert preview.kind == "confirmation"
    assert db.query(Task).count() == 0
    voice_message = (
        db.query(AssistantMessage)
        .filter_by(role="user", content="Preciso registrar uma atividade do quadro para a Alfa.")
        .one()
    )
    assert voice_message.details_json["source"] == "voice"

    corrected = service.handle_message(
        message="Na verdade, mude o título para revisar relatório.",
        request_id=f"{provider_name}-parity-correct",
        conversation_id=preview.conversation_id,
    )
    assert corrected.kind == "confirmation"
    assert corrected.action_id == preview.action_id
    assert corrected.confirmation_token != preview.confirmation_token
    assert "Preciso registrar uma atividade" in json.dumps(captured[1], ensure_ascii=False)
    assert preview.message in json.dumps(captured[1], ensure_ascii=False)
    with pytest.raises(ValueError, match="Token"):
        service.confirm_action(preview.action_id, preview.confirmation_token)

    created = service.handle_message(
        message="Pode criar",
        request_id=f"{provider_name}-parity-confirm",
        conversation_id=preview.conversation_id,
    )
    repeated = service.handle_message(
        message="Pode criar",
        request_id=f"{provider_name}-parity-confirm-repeat",
        conversation_id=preview.conversation_id,
    )
    assert created.kind == "success"
    assert repeated.task_id == created.task_id
    task = db.get(Task, created.task_id)
    assert task.titulo == "Revisar relatório"
    assert task.client_id is None
    assert task.client_name == "Alfa"
    assert task.client_link_status == "pending_review"
    assert db.query(Task).count() == 1
    assert db.get(AssistantAction, preview.action_id).status == "executed"

    cancel_payloads: list[dict[str, object]] = []
    cancel_provider = _make_provider(
        provider_name,
        [_http_response(provider_name, "criar_tarefa", {"title": "Cancelar teste"})],
        cancel_payloads,
    )
    cancel_service = AssistantService(db, cancel_provider, now=lambda: NOW)
    cancel_preview = cancel_service.handle_message(
        message="Preciso registrar uma atividade como tarefa: fazer teste de cancelamento.",
        request_id=f"{provider_name}-parity-cancel-preview",
    )
    cancelled = cancel_service.handle_message(
        message="Não, cancela",
        request_id=f"{provider_name}-parity-cancel",
        conversation_id=cancel_preview.conversation_id,
    )
    assert cancelled.kind == "text"
    assert len(cancel_payloads) == 1
    assert db.get(AssistantAction, cancel_preview.action_id).status == "cancelled"
    assert db.query(Task).count() == 1


@pytest.mark.parametrize("provider_name", PROVIDERS)
def test_today_agenda_uses_same_deterministic_open_task_query_for_each_provider(db, provider_name):
    db.add_all(
        [
            Task(titulo="Tarefa atrasada", status="a_fazer", prazo=date(2026, 10, 3), ordem=0),
            Task(titulo="Tarefa sem prazo", status="a_fazer", prazo=None, ordem=1),
        ]
    )
    db.commit()
    provider = _make_provider(
        provider_name,
        [httpx.ConnectError("provider must not be called for deterministic agenda")],
    )
    service = AssistantService(db, provider, now=lambda: NOW)

    reply = service.handle_message(
        message="Organize minha agenda e diga o que devo fazer hoje.",
        request_id=f"{provider_name}-parity-today-agenda",
    )

    assert reply.kind == "text"
    assert "Tarefa atrasada" in reply.message
    assert "Tarefa sem prazo" in reply.message


@pytest.mark.parametrize("provider_name", PROVIDERS)
def test_service_event_tool_uses_existing_confirmation_and_idempotent_service_adapter(db, provider_name):
    db.add(Client(razao_social="Alfa"))
    db.commit()
    provider = _make_provider(
        provider_name,
        [
            _http_response(
                provider_name,
                "registrar_evento_servico",
                {
                    "client": "Alfa",
                    "event_type": "inspection",
                    "summary": "Inspeção de balança",
                    "description": "Foi realizada inspeção, sem reparo.",
                },
            )
        ],
    )
    service = AssistantService(db, provider, now=lambda: NOW)

    draft = service.handle_message(
        message="Fui à empresa Alfa, mas só fiz uma inspeção.",
        request_id=f"{provider_name}-parity-service-event",
        source="voice",
    )

    assert draft.kind == "confirmation"
    assert db.query(ServiceCall).count() == 0
    assert db.query(ServiceEvent).count() == 0
    first = service.confirm_action(draft.action_id, draft.confirmation_token)
    repeated = service.confirm_action(draft.action_id, draft.confirmation_token)

    assert first.kind == "success"
    assert repeated == first
    assert db.query(ServiceCall).count() == 1
    event = db.query(ServiceEvent).one()
    assert event.event_type == "inspection"
    assert db.query(Task).count() == 0
