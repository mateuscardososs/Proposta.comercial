from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
from pydantic import ValidationError

from app.assistant.contracts import ConversationCommand, TaskCreateCommand
from app.assistant.gemini import GeminiProvider
from app.assistant.ollama import OllamaProvider
from app.assistant.provider import (
    ProviderAuthenticationError,
    ProviderMessage,
    ProviderModelUnavailableError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.assistant.service import AssistantService
from app.config import Settings
from app.routers import assistant as assistant_router


def _function_response(name: str, args: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [{"functionCall": {"name": name, "args": args}}],
                    },
                    "finishReason": "STOP",
                }
            ]
        },
    )


def test_gemini_sends_only_allowed_functions_and_returns_typed_command():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key_header"] = request.headers.get("x-goog-api-key")
        captured["payload"] = json.loads(request.content)
        return _function_response(
            "responder_conversa", {"message": "Posso ajudar a organizar isso."}
        )

    provider = GeminiProvider(
        api_key="fake-test-key",
        model="gemini-test-model",
        connect_timeout=1,
        read_timeout=5,
        transport=httpx.MockTransport(handler),
    )

    result = provider.interpret_with_trace(
        [ProviderMessage(role="user", content="Me ajude a organizar a semana.")],
        today=date(2026, 10, 6),
        timezone="America/Recife",
        allowed_tools={"responder_conversa"},
    )

    assert isinstance(result.command, ConversationCommand)
    assert result.command.message == "Posso ajudar a organizar isso."
    assert captured["api_key_header"] == "fake-test-key"
    assert "fake-test-key" not in captured["url"]
    payload = captured["payload"]
    functions = payload["tools"][0]["functionDeclarations"]
    assert [item["name"] for item in functions] == ["responder_conversa"]
    function_config = payload["toolConfig"]["functionCallingConfig"]
    assert function_config["mode"] == "ANY"
    assert function_config["allowedFunctionNames"] == ["responder_conversa"]
    assert result.inferences[0].provider == "gemini"


def test_gemini_task_arguments_are_validated_by_existing_contract():
    provider = GeminiProvider(
        api_key="fake-test-key",
        model="gemini-test-model",
        connect_timeout=1,
        read_timeout=5,
        transport=httpx.MockTransport(
            lambda _request: _function_response(
                "criar_tarefa", {"title": "Revisar relatório", "due_date": "amanhã"}
            )
        ),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Crie uma tarefa para revisar relatório amanhã.")],
        today=date(2026, 10, 6),
        timezone="America/Recife",
        allowed_tools={"criar_tarefa"},
    )

    assert isinstance(command, TaskCreateCommand)
    assert command.title == "Revisar relatório"
    assert command.due_date == "amanhã"


def test_gemini_missing_key_fails_before_network_request():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _function_response("responder_conversa", {"message": "Não deve ser chamado."})

    provider = GeminiProvider(
        api_key="",
        model="gemini-test-model",
        connect_timeout=1,
        read_timeout=5,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError, match="GEMINI_API_KEY"):
        provider.interpret(
            [ProviderMessage(role="user", content="Pergunta sintética.")],
            today=date(2026, 10, 6),
            timezone="America/Recife",
        )

    assert requests == []


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, ProviderAuthenticationError),
        (403, ProviderAuthenticationError),
        (404, ProviderModelUnavailableError),
        (429, ProviderRateLimitError),
    ],
)
def test_gemini_maps_api_status_without_exposing_response_body(status_code, error_type):
    secret_body_marker = "private-provider-error-body"
    provider = GeminiProvider(
        api_key="fake-test-key",
        model="gemini-test-model",
        connect_timeout=1,
        read_timeout=5,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(status_code, json={"error": secret_body_marker})
        ),
    )

    with pytest.raises(error_type) as captured:
        provider.interpret(
            [ProviderMessage(role="user", content="Pergunta sintética.")],
            today=date(2026, 10, 6),
            timezone="America/Recife",
        )

    assert secret_body_marker not in str(captured.value)
    assert "fake-test-key" not in str(captured.value)


def test_gemini_maps_http_timeout_to_provider_timeout():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout detail")

    provider = GeminiProvider(
        api_key="fake-test-key",
        model="gemini-test-model",
        connect_timeout=1,
        read_timeout=5,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderTimeoutError, match="Gemini"):
        provider.interpret(
            [ProviderMessage(role="user", content="Pergunta sintética.")],
            today=date(2026, 10, 6),
            timezone="America/Recife",
        )


def test_gemini_repairs_invalid_structured_output_once_without_reusing_it(caplog):
    calls = 0
    private_model_output = "private-unvalidated-model-output"

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": private_model_output}]}}]},
            )
        return _function_response("responder_conversa", {"message": "Resposta sintética."})

    provider = GeminiProvider(
        api_key="fake-test-key",
        model="gemini-test-model",
        connect_timeout=1,
        read_timeout=5,
        transport=httpx.MockTransport(handler),
    )

    with caplog.at_level("INFO", logger="app.assistant.gemini"):
        result = provider.interpret_with_trace(
            [ProviderMessage(role="user", content="Pergunta sintética.")],
            today=date(2026, 10, 6),
            timezone="America/Recife",
            allowed_tools={"responder_conversa"},
        )

    assert result.command.message == "Resposta sintética."
    assert calls == 2
    assert private_model_output not in caplog.text


def test_gemini_repairs_non_json_response_without_leaking_body():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, content=b"private-not-json-response")
        return _function_response("responder_conversa", {"message": "Resposta sintética."})

    provider = GeminiProvider(
        api_key="fake-test-key",
        model="gemini-test-model",
        connect_timeout=1,
        read_timeout=5,
        transport=httpx.MockTransport(handler),
    )

    result = provider.interpret_with_trace(
        [ProviderMessage(role="user", content="Pergunta sintética.")],
        today=date(2026, 10, 6),
        timezone="America/Recife",
        allowed_tools={"responder_conversa"},
    )

    assert result.command.message == "Resposta sintética."
    assert calls == 2
    assert all(trace.repair_reason for trace in result.inferences[:1])


def test_gemini_invalid_output_fails_after_one_repair():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "malformed"}]}}]},
        )

    provider = GeminiProvider(
        api_key="fake-test-key",
        model="gemini-test-model",
        connect_timeout=1,
        read_timeout=5,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderResponseError):
        provider.interpret(
            [ProviderMessage(role="user", content="Pergunta sintética.")],
            today=date(2026, 10, 6),
            timezone="America/Recife",
            allowed_tools={"responder_conversa"},
        )

    assert calls == 2


def test_provider_factory_keeps_ollama_default_and_selects_gemini(monkeypatch):
    default_settings = Settings(_env_file=None)
    monkeypatch.setattr(assistant_router, "get_settings", lambda: default_settings)
    assert isinstance(assistant_router.get_assistant_provider(), OllamaProvider)

    gemini_settings = Settings(
        _env_file=None,
        llm_provider="gemini",
        gemini_api_key="fake-test-key",
        gemini_model="configured-gemini-model",
    )
    monkeypatch.setattr(assistant_router, "get_settings", lambda: gemini_settings)
    provider = assistant_router.get_assistant_provider()
    assert isinstance(provider, GeminiProvider)
    assert provider.model == "configured-gemini-model"


def test_provider_setting_rejects_unknown_provider():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_provider="some-cloud-provider")


def test_missing_gemini_key_returns_clear_error_without_falling_back(db):
    provider = GeminiProvider(
        api_key="",
        model="configured-gemini-model",
        connect_timeout=1,
        read_timeout=5,
        transport=httpx.MockTransport(
            lambda _request: pytest.fail("No request or fallback should occur without a key")
        ),
    )
    service = AssistantService(db, provider=provider)

    reply = service.handle_message(
        message="Explique em termos simples o que é uma balança comercial.",
        request_id="gemini-missing-key-synthetic",
    )

    assert reply.kind == "error"
    assert "GEMINI_API_KEY" in reply.message
    assert "Ollama" not in reply.message
