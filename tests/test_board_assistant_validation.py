from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.models import Client, Proposal, Task, User
from app.schemas import TaskCreate
from app.services import board_service


def test_task_schema_rejects_unknown_status():
    with pytest.raises(ValidationError):
        TaskCreate(titulo="Status invalido", status="inventado")


def test_create_task_rejects_client_that_does_not_match_proposal(db):
    first = Client(razao_social="Cliente Um")
    second = Client(razao_social="Cliente Dois")
    user = User(nome="Responsavel", email="responsavel-assistant@example.com", senha_hash="hash")
    db.add_all([first, second, user])
    db.flush()
    proposal = Proposal(numero=400, revisao="00", client_id=first.id, user_id=user.id)
    db.add(proposal)
    db.commit()

    with pytest.raises(ValueError, match="cliente"):
        board_service.create_task(
            db,
            TaskCreate(
                titulo="Tarefa inconsistente",
                client_id=second.id,
                proposal_id=proposal.id,
            ),
        )


def test_priority_tasks_put_documentation_risk_before_overdue(db):
    db.add_all(
        [
            Task(
                titulo="Atrasada",
                status="a_fazer",
                prazo=date(2026, 9, 1),
                ordem=0,
            ),
            Task(
                titulo="Servico feito sem nota",
                status="servico_feito_falta_nota_pedido",
                prazo=None,
                ordem=0,
            ),
        ]
    )
    db.commit()

    tasks = board_service.query_tasks(
        db,
        today=date(2026, 9, 30),
        priorities=True,
        include_completed=False,
        limit=10,
    )

    assert [task.titulo for task in tasks] == ["Servico feito sem nota", "Atrasada"]


def test_create_task_derives_client_from_proposal(db):
    client = Client(razao_social="Cliente da proposta")
    user = User(nome="Responsavel proposta", email="proposal-task@example.com", senha_hash="hash")
    db.add_all([client, user])
    db.flush()
    proposal = Proposal(numero=401, revisao="00", client_id=client.id, user_id=user.id)
    db.add(proposal)
    db.commit()

    task = board_service.create_task(
        db,
        TaskCreate(titulo="Vinculo derivado", proposal_id=proposal.id),
    )

    assert task.client_id == client.id
