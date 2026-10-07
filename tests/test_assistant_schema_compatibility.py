from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import MetaData, create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.db import (
    Base,
    ensure_schema_compatibility_for_engine,
    ensure_service_history_guards_for_engine,
)
from app.models import (
    AssistantAction,
    AssistantConversation,
    Client,
    Lancamento,
    Proposal,
    ServiceCall,
    ServiceEvent,
    ServiceTechnicalReport,
    ServiceWorkflowStep,
    ServiceWorkflowTransition,
    Task,
    User,
)

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
EMAIL_AUTOMATION_TABLES = {"inbox_emails", "email_task_links", "email_sync_states", "email_action_drafts"}


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


def test_email_projection_adds_reply_coverage_and_extraction_column_without_losing_rows(tmp_path):
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
    assert {"awaiting_reply", "sent_coverage", "extracted_fields"}.issubset(columns)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT awaiting_reply, sent_coverage FROM inbox_emails WHERE id = 1")).one()
    assert row.awaiting_reply == "unknown"
    assert row.sent_coverage == 0

    ensure_schema_compatibility_for_engine(engine)
    assert "extracted_fields" in {column["name"] for column in inspect(engine).get_columns("inbox_emails")}


def test_financial_archive_column_is_added_to_existing_schema(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'old_lancamentos.sqlite3').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE lancamentos (
                id INTEGER PRIMARY KEY, tipo VARCHAR(20) NOT NULL,
                descricao VARCHAR(255) NOT NULL, valor NUMERIC(14, 2) NOT NULL,
                data_emissao DATE NOT NULL, data_vencimento DATE NOT NULL,
                status VARCHAR(20) NOT NULL, data_pagamento DATE
            )
        """))
        connection.execute(text("""
            INSERT INTO lancamentos (id, tipo, descricao, valor, data_emissao,
                data_vencimento, status, data_pagamento)
            VALUES (1, 'pagar', 'Conta preservada', 100, '2026-09-01',
                '2026-10-01', 'pendente', NULL)
        """))

    ensure_schema_compatibility_for_engine(engine)

    assert "arquivado_em" in {column["name"] for column in inspect(engine).get_columns("lancamentos")}
    assert "ix_lancamentos_arquivado_em" in {
        index["name"] for index in inspect(engine).get_indexes("lancamentos")
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT descricao FROM lancamentos WHERE id = 1")) == "Conta preservada"


def test_task_client_text_fields_are_added_without_losing_existing_tasks(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'old_tasks.sqlite3').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY, titulo VARCHAR(255) NOT NULL,
                descricao TEXT NOT NULL DEFAULT '', status VARCHAR(50) NOT NULL,
                client_id INTEGER, proposal_id INTEGER, user_id INTEGER,
                prazo DATE, ordem INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
            )
        """))
        connection.execute(text("""
            INSERT INTO tasks (id, titulo, descricao, status, ordem, created_at, updated_at)
            VALUES (7, 'Tarefa preservada', '', 'a_fazer', 0,
                    '2026-10-02 10:00:00', '2026-10-02 10:00:00')
        """))

    ensure_schema_compatibility_for_engine(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("tasks")}
    assert {"client_name", "client_link_status", "estimated_duration_minutes"}.issubset(columns)
    with engine.connect() as connection:
        task = connection.execute(text(
            "SELECT titulo, client_name, client_link_status, estimated_duration_minutes FROM tasks WHERE id=7"
        )).one()
    assert task.titulo == "Tarefa preservada"
    assert task.client_name is None
    assert task.client_link_status == "unlinked"
    assert task.estimated_duration_minutes is None


def test_email_sync_activation_boundary_is_added_to_existing_state_table(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'old_sync_state.sqlite3').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE email_sync_states (
                id INTEGER PRIMARY KEY, provider VARCHAR(30) NOT NULL,
                mailbox_key VARCHAR(160) NOT NULL, paused BOOLEAN NOT NULL DEFAULT 0,
                last_attempt_at DATETIME, last_success_at DATETIME,
                last_error VARCHAR(200), last_count INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
            )
        """))
        connection.execute(text("""
            INSERT INTO email_sync_states (id, provider, mailbox_key, created_at, updated_at)
            VALUES (1, 'imap_yahoo', 'pilot', '2026-10-02 10:00:00', '2026-10-02 10:00:00')
        """))

    ensure_schema_compatibility_for_engine(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("email_sync_states")}
    assert "activation_at" in columns
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM email_sync_states")) == 1


def test_report_event_links_become_optional_without_losing_existing_history(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy_service_report_links.sqlite3').as_posix()}" )
    legacy_metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(legacy_metadata)
    legacy_metadata.tables["service_workflow_transitions"].c.service_event_id.nullable = False
    legacy_metadata.tables["service_technical_reports"].c.document_event_id.nullable = False
    legacy_metadata.create_all(engine)

    with Session(engine) as session:
        client = Client(razao_social="Cliente legado")
        conversation = AssistantConversation()
        session.add_all([client, conversation])
        session.flush()
        source_action = AssistantAction(
            conversation_id=conversation.id,
            request_id="legacy-service-source",
            confirmation_token_hash="1" * 64,
            action_type="register_service_event",
            status="executed",
        )
        report_action = AssistantAction(
            conversation_id=conversation.id,
            request_id="legacy-report-action",
            confirmation_token_hash="2" * 64,
            action_type="generate_service_report",
            status="executed",
        )
        session.add_all([source_action, report_action])
        session.flush()
        call = ServiceCall(
            client_id=client.id,
            summary="Chamado legado",
            opened_on=date(2026, 10, 1),
            execution_status="completed",
        )
        session.add(call)
        session.flush()
        step = ServiceWorkflowStep(service_call_id=call.id, step_type="report", status="completed")
        session.add(step)
        session.flush()
        event = ServiceEvent(
            service_call_id=call.id,
            assistant_action_id=source_action.id,
            conversation_id=conversation.id,
            event_type="execution_completed",
            occurred_on=date(2026, 10, 2),
            description="Registro legado",
        )
        session.add(event)
        session.flush()
        session.add(ServiceWorkflowTransition(
            service_call_id=call.id,
            step_type="report",
            previous_status="pending",
            new_status="completed",
            observation="Transição legada preservada",
            service_event_id=event.id,
            assistant_action_id=source_action.id,
        ))
        report = ServiceTechnicalReport(
            service_call_id=call.id,
            assistant_action_id=report_action.id,
            document_event_id=event.id,
            idempotency_key="legacy-report-key",
            source_fingerprint="a" * 64,
            source_event_ids=[event.id],
            client_snapshot_json={"name": "Cliente legado"},
            fields_json={"equipment": "Balança sintética"},
            source_fields_json={},
            manual_overrides_json=[],
            missing_fields_json=[],
            docx_path="legacy/report.docx",
            pdf_path="legacy/report.pdf",
            confirmed_at=datetime(2026, 10, 3, tzinfo=UTC),
        )
        session.add(report)
        session.commit()
        report_id = report.id

    ensure_schema_compatibility_for_engine(engine)

    columns = {
        table: {column["name"]: column["nullable"] for column in inspect(engine).get_columns(table)}
        for table in ("service_workflow_transitions", "service_technical_reports")
    }
    assert columns["service_workflow_transitions"]["service_event_id"] is True
    assert columns["service_technical_reports"]["document_event_id"] is True
    with Session(engine) as session:
        migrated = session.get(ServiceTechnicalReport, report_id)
        transition = session.scalar(select(ServiceWorkflowTransition))
        assert migrated.fields_json["equipment"] == "Balança sintética"
        assert migrated.document_event_id is not None
        assert transition.observation == "Transição legada preservada"
        assert transition.service_event_id is not None
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
