from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.db import (
    Base,
    ensure_schema_compatibility_for_engine,
    ensure_service_history_guards_for_engine,
)
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
EMAIL_AUTOMATION_TABLES = {"inbox_emails", "email_task_links", "email_sync_states"}


def test_create_all_adds_assistant_tables_without_changing_existing_tasks(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'existing.sqlite3').as_posix()}")
    old_tables = [table for table in Base.metadata.sorted_tables if table.name not in ASSISTANT_TABLES | SERVICE_TABLES]
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
    old_tables = [table for table in Base.metadata.sorted_tables if table.name not in SERVICE_TABLES]
    Base.metadata.create_all(engine, tables=old_tables)
    with Session(engine) as session:
        client = Client(razao_social="Cliente preservado")
        user = User(nome="Operador", email="operador@example.test", senha_hash="teste")
        session.add_all([client, user])
        session.flush()
        session.add_all(
            [
                Task(
                    titulo="Dado operacional preservado",
                    status="a_fazer",
                    ordem=0,
                    client_id=client.id,
                ),
                Proposal(numero=900001, revisao="00", client_id=client.id, user_id=user.id),
                Lancamento(
                    tipo="receber",
                    descricao="Lancamento preservado",
                    client_id=client.id,
                    valor=Decimal("10.00"),
                    data_vencimento=date(2026, 10, 10),
                ),
            ]
        )
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


def test_create_all_adds_email_automation_tables_without_changing_existing_data(
    tmp_path,
):
    engine = create_engine(f"sqlite:///{(tmp_path / 'before_email_automation.sqlite3').as_posix()}")
    old_tables = [table for table in Base.metadata.sorted_tables if table.name not in EMAIL_AUTOMATION_TABLES]
    Base.metadata.create_all(engine, tables=old_tables)
    with Session(engine) as session:
        session.add(Task(titulo="Tarefa operacional preservada", status="a_fazer", ordem=0))
        session.commit()

    Base.metadata.create_all(engine)

    assert EMAIL_AUTOMATION_TABLES.issubset(set(inspect(engine).get_table_names()))
    with Session(engine) as session:
        assert session.scalar(select(Task.titulo)) == "Tarefa operacional preservada"


def test_email_projection_adds_reply_coverage_columns_without_losing_rows(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'email_projection_old.sqlite3').as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text("""
            CREATE TABLE inbox_emails (
                id INTEGER PRIMARY KEY, provider VARCHAR(30) NOT NULL,
                mailbox_key VARCHAR(160) NOT NULL, reference VARCHAR(160) NOT NULL,
                thread_reference VARCHAR(500) NOT NULL, sender VARCHAR(500) NOT NULL,
                subject VARCHAR(500) NOT NULL, received_at DATETIME NOT NULL,
                seen BOOLEAN NOT NULL, summary VARCHAR(400) NOT NULL,
                category VARCHAR(40) NOT NULL, confidence_band VARCHAR(20) NOT NULL,
                destination VARCHAR(30) NOT NULL, classification_reason TEXT NOT NULL,
                priority VARCHAR(20) NOT NULL, explicit_deadline VARCHAR(20),
                review_status VARCHAR(20) NOT NULL, last_seen_at DATETIME NOT NULL
            )
        """)
        )
        connection.execute(
            text("""
            INSERT INTO inbox_emails (
                id, provider, mailbox_key, reference, thread_reference, sender, subject,
                received_at, seen, summary, category, confidence_band, destination,
                classification_reason, priority, review_status, last_seen_at
            ) VALUES (1, 'synthetic', 'fixture', 'source-1', '', 'fixture sender', 'fixture subject',
                '2026-10-02 10:00:00', 0, 'fixture summary', 'pending_reply', 'medium', 'review',
                'coverage absent', 'normal', 'pending', '2026-10-02 10:00:00')
        """)
        )

    ensure_schema_compatibility_for_engine(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("inbox_emails")}
    assert {"awaiting_reply", "sent_coverage"}.issubset(columns)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT awaiting_reply, sent_coverage FROM inbox_emails WHERE id = 1")).one()
    assert row.awaiting_reply == "unknown"
    assert row.sent_coverage == 0
