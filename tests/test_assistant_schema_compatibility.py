from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.db import Base, ensure_service_history_guards_for_engine
from app.models import Client, Lancamento, Proposal, Task, User


ASSISTANT_TABLES = {
    "assistant_conversations",
    "assistant_messages",
    "assistant_actions",
    "assistant_requests",
}
SERVICE_TABLES = {
    "service_calls",
    "service_events",
    "service_workflow_steps",
    "service_workflow_transitions",
    "service_task_links",
}


def test_create_all_adds_assistant_tables_without_changing_existing_tasks(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'existing.sqlite3').as_posix()}")
    old_tables = [
        table
        for table in Base.metadata.sorted_tables
        if table.name not in ASSISTANT_TABLES | SERVICE_TABLES
    ]
    Base.metadata.create_all(engine, tables=old_tables)
    with Session(engine) as session:
        session.add(Task(titulo="Dado operacional preservado", status="a_fazer", ordem=0))
        session.commit()

    Base.metadata.create_all(engine)

    assert ASSISTANT_TABLES.issubset(set(inspect(engine).get_table_names()))
    with Session(engine) as session:
        assert session.scalar(select(Task.titulo)) == "Dado operacional preservado"


def test_create_all_adds_service_tables_without_changing_existing_data(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'before_services.sqlite3').as_posix()}")
    old_tables = [
        table for table in Base.metadata.sorted_tables if table.name not in SERVICE_TABLES
    ]
    Base.metadata.create_all(engine, tables=old_tables)
    with Session(engine) as session:
        client = Client(razao_social="Cliente preservado")
        user = User(nome="Operador", email="operador@example.test", senha_hash="teste")
        session.add_all([client, user])
        session.flush()
        session.add_all([
            Task(titulo="Dado operacional preservado", status="a_fazer", ordem=0, client_id=client.id),
            Proposal(numero=900001, revisao="00", client_id=client.id, user_id=user.id),
            Lancamento(
                tipo="receber", descricao="Lancamento preservado", client_id=client.id,
                valor=Decimal("10.00"), data_vencimento=date(2026, 10, 10),
            ),
        ])
        session.commit()

    Base.metadata.create_all(engine)
    ensure_service_history_guards_for_engine(engine)
    ensure_service_history_guards_for_engine(engine)

    assert SERVICE_TABLES.issubset(set(inspect(engine).get_table_names()))
    with engine.connect() as conn:
        assert conn.scalar(text("PRAGMA foreign_keys")) == 1
    with Session(engine) as session:
        assert session.scalar(select(Client.razao_social)) == "Cliente preservado"
        assert session.scalar(select(Task.titulo)) == "Dado operacional preservado"
        assert session.scalar(select(Proposal.numero)) == 900001
        assert session.scalar(select(Lancamento.descricao)) == "Lancamento preservado"
