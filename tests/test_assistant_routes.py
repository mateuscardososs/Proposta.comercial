from __future__ import annotations

from fastapi.testclient import TestClient

from app.assistant.contracts import ConversationCommand, TaskCreateCommand, TaskQueryCommand
from app.main import app
from app.routers.assistant import get_assistant_provider


class RouteProvider:
    def __init__(self):
        self.command = TaskQueryCommand()

    def interpret(self, messages, *, today, timezone):
        return self.command


def test_assistant_page_uses_existing_shell_and_local_warning():
    with TestClient(app) as client:
        response = client.get("/web/assistente")

    assert response.status_code == 200
    assert "Assistente" in response.text
    assert "Somente neste computador" in response.text
    assert 'id="assistant-message"' in response.text
    assert 'id="assistant-send"' in response.text
    assert 'id="voice-start"' in response.text
    assert 'id="voice-finish"' in response.text
    assert 'id="voice-stop"' in response.text
    assert 'id="voice-repeat"' in response.text
    assert 'id="voice-end"' in response.text
    assert 'src="/assets/assistant_chat.js"' in response.text
    assert 'src="/assets/assistant_voice_bootstrap.js"' in response.text
    assert 'id="assistant-retry"' in response.text
    assert 'id="voice-level"' in response.text
    assert 'href="/web/assistente" class="active"' in response.text


def test_assistant_api_creates_preview_then_idempotent_task():
    provider = RouteProvider()
    provider.command = TaskCreateCommand(title="Revisar proposta")
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    try:
        with TestClient(app) as client:
            preview = client.post(
                "/api/assistant/messages",
                json={"message": "Crie a tarefa revisar proposta", "request_id": "route-create-1"},
            )
            assert preview.status_code == 200
            payload = preview.json()
            assert payload["kind"] == "confirmation"

            first = client.post(
                f"/api/assistant/actions/{payload['action_id']}/confirm",
                json={"confirmation_token": payload["confirmation_token"]},
            )
            repeated = client.post(
                f"/api/assistant/actions/{payload['action_id']}/confirm",
                json={"confirmation_token": payload["confirmation_token"]},
            )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert first.json()["task_id"] == repeated.json()["task_id"]
    assert first.json()["task_url"].startswith("/web/board/")


def test_conversation_history_endpoint_returns_messages():
    provider = RouteProvider()
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    try:
        with TestClient(app) as client:
            sent = client.post(
                "/api/assistant/messages",
                json={"message": "Mostre minhas tarefas", "request_id": "route-history-1"},
            )
            conversation_id = sent.json()["conversation_id"]
            history = client.get(f"/api/assistant/conversations/{conversation_id}")
    finally:
        app.dependency_overrides.clear()

    assert history.status_code == 200
    assert [item["role"] for item in history.json()["messages"]] == ["user", "assistant"]


def test_assistant_api_returns_a_natural_structured_conversation_reply():
    provider = RouteProvider()
    provider.command = ConversationCommand(
        message="Olá! Posso consultar tarefas e preparar uma nova tarefa com você."
    )
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/assistant/messages",
                json={"message": "Oi", "request_id": "route-talk-1"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["kind"] == "text"
    assert response.json()["message"].startswith("Olá")
    assert response.json()["task_id"] is None


def test_conversation_history_never_exposes_confirmation_credentials():
    provider = RouteProvider()
    provider.command = TaskCreateCommand(title="Revisar credenciais")
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    try:
        with TestClient(app) as client:
            preview = client.post(
                "/api/assistant/messages",
                json={"message": "Crie uma tarefa", "request_id": "route-secret-1"},
            )
            payload = preview.json()
            history = client.get(
                f"/api/assistant/conversations/{payload['conversation_id']}"
            )
    finally:
        app.dependency_overrides.clear()

    assert preview.status_code == 200
    assert payload["confirmation_token"]
    assert history.status_code == 200
    serialized_history = history.text
    assert "confirmation_token" not in serialized_history
    assert payload["confirmation_token"] not in serialized_history
