from datetime import date

import pytest

from app.assistant.contracts import TaskCreateCommand, TaskDraftCorrectionCommand
from app.assistant.service import AssistantService
from app.models import (
    AssistantAction,
    AssistantConversation,
    Client,
    Proposal,
    Task,
    User,
)


def setup_draft(db):
    conversation = AssistantConversation()
    users = [User(nome=name, email=f"draft{i}@example.invalid", senha_hash="unused")
             for i, name in enumerate(("Ana Silva", "Ana Souza"))]
    clients = [Client(razao_social=name) for name in ("Alfa Industria", "Alfa Servicos")]
    db.add_all([conversation, *users, *clients])
    db.flush()
    return AssistantService(db, None), conversation, users, clients


def test_ambiguous_responsible_correction_reuses_action_and_request(db):
    service, conversation, users, _ = setup_draft(db)
    command = TaskCreateCommand(title=" Revisar ", responsible="Ana", due_date="amanha",
                                estimated_duration_minutes=35)
    reply = service._prepare_task(conversation.id, "draft-original", command, date(2026, 9, 30))
    assert reply.kind == "clarification"
    action = db.query(AssistantAction).one()
    assert action.status == "needs_clarification"
    assert action.arguments_json == command.model_dump(mode="json")
    original_id, original_hash = action.id, action.confirmation_token_hash
    corrected = service._correct_pending_task(conversation.id, "draft-correction",
        TaskDraftCorrectionCommand(responsible=users[0].nome), date(2026, 9, 30))
    assert corrected.kind == "confirmation"
    assert corrected.action_id == original_id
    assert action.request_id == "draft-original"
    assert action.status == "pending"
    assert action.arguments_json["prazo"] == "2026-10-01"
    assert action.arguments_json["estimated_duration_minutes"] == 35
    assert original_hash != action.confirmation_token_hash
    assert db.query(AssistantAction).count() == 1
    assert db.query(Task).count() == 0


@pytest.mark.parametrize(("client", "link_status"), [(None, "unlinked"), ("Alfa", "needs_confirmation"),
                                                     ("Novo cliente", "pending_review")])
def test_optional_client_and_removal_rotate_token_without_creating_task(db, client, link_status):
    service, conversation, users, _ = setup_draft(db)
    reply = service._prepare_task(conversation.id, "draft-clear", TaskCreateCommand(
        title="Revisar", client=client, responsible=users[0].nome, due_date="amanha"), date(2026, 9, 30))
    action = db.query(AssistantAction).one()
    assert action.arguments_json["client_link_status"] == link_status
    corrected = service._correct_pending_task(conversation.id, "draft-clear-correction",
        TaskDraftCorrectionCommand(clear_client=True, clear_responsible=True, clear_due_date=True,
                                   estimated_duration_minutes=45), date(2026, 9, 30))
    assert corrected.action_id == reply.action_id
    assert action.request_id == "draft-clear"
    assert action.confirmation_token_hash == service._token_hash(corrected.confirmation_token)
    assert action.confirmation_token_hash != service._token_hash(reply.confirmation_token)
    assert {key: action.arguments_json[key] for key in ("prazo", "client_id", "client_name", "user_id")} == dict.fromkeys(("prazo", "client_id", "client_name", "user_id"))
    assert corrected.fields["duracao_estimada"] == "45 minutos (estimativa)"
    assert corrected.fields["cliente"] == "Sem cliente"
    assert db.query(Task).count() == 0


@pytest.mark.parametrize(("scenario", "message"), [
    ("missing", "Nao encontrei a proposta 456."),
    ("revisions", "A proposta 456 possui as revisoes 01, 00. Informe a revisao pela tela do quadro antes de vincular pelo assistente."),
    ("mismatch", "A proposta informada pertence a outro cliente. Qual vinculo devo usar?"),
])
def test_proposal_constraints_preserve_exact_messages(db, scenario, message):
    service, conversation, users, clients = setup_draft(db)
    if scenario != "missing":
        db.add(Proposal(numero=456, revisao="00", client_id=clients[0].id, user_id=users[0].id))
        if scenario == "revisions":
            db.add(Proposal(numero=456, revisao="01", client_id=clients[0].id, user_id=users[0].id))
        db.flush()
    reply = service._prepare_task(conversation.id, "draft-proposal", TaskCreateCommand(
        title="Revisar", proposal_number=456, client=clients[1].razao_social), date(2026, 9, 30))
    assert reply.kind == "clarification"
    assert reply.message == message
    assert db.query(AssistantAction).count() == 0
    assert db.query(Task).count() == 0
