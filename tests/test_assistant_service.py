from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.assistant.contracts import TaskCreateCommand, TaskQueryCommand
from app.assistant.provider import ProviderMessage, ProviderUnavailableError
from app.assistant.service import AssistantService
from app.db import SessionLocal
from app.models import AssistantAction, AssistantConversation, AssistantMessage, Client, Task, User


class QueueProvider:
    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[list[ProviderMessage]] = []

    def interpret(self, messages, *, today, timezone):
        self.calls.append(list(messages))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


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
    provider = QueueProvider(TaskQueryCommand(include_completed=False, limit=10))
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
    assert [message.content for message in provider.calls[1]] == [
        "Crie uma tarefa de vistoria para a Acme",
        question.message,
        "E a Acme Norte",
    ]
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
    db.add(
        AssistantMessage(
            conversation_id=conversation.id,
            role="user",
            kind="text",
            content="Crie uma tarefa",
            request_id="in-progress-1",
            details_json={},
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
