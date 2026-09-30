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
from app.assistant.provider import ProviderMessage, ProviderUnavailableError
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
    assert [item.content for item in provider.calls[1]] == [
        "O que você faz?",
        first.message,
        "O que você quis dizer?",
    ]


def test_conversation_reply_cannot_claim_an_unexecuted_action(db):
    provider = QueueProvider(
        ConversationCommand(message="Criei a tarefa no quadro para você.")
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(message="Oi", request_id="unsafe-talk-1")

    assert reply.kind == "error"
    assert "Nada foi alterado" in reply.message
    assert db.query(Task).count() == 0


def test_empty_query_explicitly_reports_empty_board_and_offers_help(db):
    provider = QueueProvider(TaskQueryCommand())
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
    provider = QueueProvider(TaskQueryCommand())
    service = AssistantService(db, provider, now=_now, request_lease_seconds=120)

    reply = service.handle_message(
        message="Mostre as tarefas",
        request_id="expired-request-1",
        conversation_id=conversation.id,
    )

    request = db.query(AssistantRequest).filter_by(request_id="expired-request-1").one()
    assert reply.kind == "text"
    assert len(provider.calls) == 1
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
