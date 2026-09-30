from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from app.assistant.contracts import TaskCreateCommand
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
                    "content": json.dumps(
                        {
                            "tool": "criar_tarefa",
                            "title": "Ligar para o cliente",
                            "due_date": "amanha",
                        }
                    ),
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
    assert isinstance(payload["format"], dict)
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
