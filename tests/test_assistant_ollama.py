from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from app.assistant.contracts import (
    ConversationCommand,
    TaskCreateCommand,
    TaskQueryCommand,
    UnsupportedCommand,
)
from app.assistant.ollama import OllamaProvider
from app.assistant.provider import ProviderMessage, ProviderUnavailableError


def test_ollama_uses_configured_model_and_validated_schema():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "criar_tarefa",
                                "arguments": {
                                    "title": "Ligar para o cliente",
                                    "due_date": "amanha",
                                },
                            }
                        }
                    ],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-configurado",
        connect_timeout=2,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Crie para amanha")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert isinstance(command, TaskCreateCommand)
    assert command.title == "Ligar para o cliente"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "modelo-configurado"
    assert payload["stream"] is False
    assert isinstance(payload["tools"], list)
    assert "shell" not in json.dumps(payload).lower()
    assert "sql" not in json.dumps(payload).lower()


def test_ollama_rejects_non_local_url():
    with pytest.raises(ValueError, match="local"):
        OllamaProvider(
            base_url="https://example.com",
            model="qualquer",
            connect_timeout=2,
            read_timeout=30,
        )


def test_ollama_connection_failure_has_specific_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    provider = OllamaProvider(
        base_url="http://localhost:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=1,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError, match="Ollama"):
        provider.interpret(
            [ProviderMessage(role="user", content="Liste tarefas")],
            today=date(2026, 9, 30),
            timezone="America/Recife",
        )


def test_ollama_timeout_has_specific_error_and_no_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow model", request=request)

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-lento",
        connect_timeout=1,
        read_timeout=1,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError, match="Ollama"):
        provider.interpret(
            [ProviderMessage(role="user", content="Crie uma tarefa")],
            today=date(2026, 9, 30),
            timezone="America/Recife",
        )


def test_ollama_prompt_limits_tools_and_treats_content_as_data():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "cancelar_acao", "arguments": {}}}
                    ],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    provider.interpret(
        [ProviderMessage(role="user", content="Apague tudo e rode um comando")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    payload = captured["payload"]
    assert isinstance(payload, dict)
    system_prompt = payload["messages"][0]["content"]
    assert "confirmar_acao" in system_prompt
    assert "cancelar_acao" in system_prompt
    assert "corrigir_tarefa" in system_prompt
    assert "dados nao confiaveis" in system_prompt
    assert "exclusao" in system_prompt
    assert "financeiro" in system_prompt


def test_ollama_accepts_one_validated_single_tool_call():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "consultar_tarefas",
                                "arguments": {"overdue_only": True, "limit": 10},
                            }
                        }
                    ],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Tem alguma tarefa atrasada?")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert isinstance(command, TaskQueryCommand)
    assert command.overdue_only is True
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert "format" not in payload
    assert {tool["function"]["name"] for tool in payload["tools"]} == {
        "consultar_tarefas",
        "criar_tarefa",
        "corrigir_tarefa",
        "confirmar_acao",
        "cancelar_acao",
        "fora_do_escopo",
        "responder_conversa",
    }


def test_ollama_repairs_a_text_response_once_by_requiring_a_tool_call():
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return httpx.Response(
                200,
                json={
                    "message": {
                        "role": "assistant",
                        "content": "Entendido, vou atribuir a Carlos.",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "corrigir_tarefa",
                                "arguments": {"responsible": "Carlos"},
                            }
                        }
                    ],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Deixe essa tarefa com Carlos.")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert command.responsible == "Carlos"
    assert len(payloads) == 2
    repair_messages = payloads[1]["messages"]
    assert isinstance(repair_messages, list)
    assert repair_messages[-2]["role"] == "assistant"
    assert "exatamente uma ferramenta" in repair_messages[-1]["content"]


def test_ollama_accepts_only_a_validated_textual_out_of_scope_refusal():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": (
                        'fora_do_escopo {"message": "Nao posso apagar tarefas; nada foi alterado."}'
                    ),
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Apague todas as tarefas.")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert isinstance(command, UnsupportedCommand)
    assert "nada foi alterado" in command.message


def test_ollama_accepts_a_structured_natural_conversation_reply():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "responder_conversa",
                                "arguments": {
                                    "message": "Boa tarde! Como posso ajudar com o seu quadro?"
                                },
                            }
                        }
                    ],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Oi, boa tarde.")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert isinstance(command, ConversationCommand)
    assert command.message.startswith("Boa tarde")
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert "responder_conversa" in {
        tool["function"]["name"] for tool in payload["tools"]
    }
    system_prompt = payload["messages"][0]["content"]
    assert "nao pode afirmar" in system_prompt.lower()
    assert "consulta real" in system_prompt.lower()
