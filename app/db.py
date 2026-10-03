from __future__ import annotations

import sqlite3
from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(
    settings.database_url,
    future=True,
    echo=False,
    connect_args=connect_args,
    pool_pre_ping=True,
)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    del connection_record
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA recursive_triggers=ON")
    cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


class Base(DeclarativeBase):
    pass


def ensure_schema_compatibility_for_engine(target_engine: Engine) -> None:
    inspector = inspect(target_engine)
    table_names = set(inspector.get_table_names())
    if "tasks" in table_names:
        task_columns = {str(column["name"]) for column in inspector.get_columns("tasks")}
        task_additions = (
            ("client_name", "VARCHAR(255)", None),
            ("client_link_status", "VARCHAR(30)", "'unlinked'"),
        )
        for column_name, column_type, default_value in task_additions:
            if column_name in task_columns:
                continue
            default_clause = f" NOT NULL DEFAULT {default_value}" if default_value else ""
            statement = f"ALTER TABLE tasks ADD COLUMN {column_name} {column_type}{default_clause}"
            with target_engine.begin() as conn:
                conn.execute(text(statement))
    if "inbox_emails" in inspector.get_table_names():
        email_columns = {str(column["name"]) for column in inspector.get_columns("inbox_emails")}
        for column_name, column_type, sqlite_default, postgres_default in (
            ("awaiting_reply", "VARCHAR(20)", "'unknown'", "'unknown'"),
            ("sent_coverage", "BOOLEAN", "0", "FALSE"),
        ):
            if column_name in email_columns:
                continue
            if target_engine.dialect.name == "postgresql":
                statement = f"ALTER TABLE inbox_emails ADD COLUMN IF NOT EXISTS {column_name} {column_type} NOT NULL DEFAULT {postgres_default}"
            else:
                statement = f"ALTER TABLE inbox_emails ADD COLUMN {column_name} {column_type} NOT NULL DEFAULT {sqlite_default}"
            with target_engine.begin() as conn:
                conn.execute(text(statement))
    if "email_sync_states" in table_names:
        state_columns = {str(column["name"]) for column in inspector.get_columns("email_sync_states")}
        if "activation_at" not in state_columns:
            timestamp_type = "TIMESTAMP" if target_engine.dialect.name == "postgresql" else "DATETIME"
            with target_engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE email_sync_states ADD COLUMN activation_at {timestamp_type}"))
    if "proposals" not in inspector.get_table_names():
        return

    proposal_columns = {str(column["name"]) for column in inspector.get_columns("proposals")}
    with target_engine.begin() as conn:
        if target_engine.dialect.name == "sqlite" and "condicao_pagamento_dias" not in proposal_columns:
            conn.execute(text("ALTER TABLE proposals ADD COLUMN condicao_pagamento_dias INTEGER NOT NULL DEFAULT 0"))
        if target_engine.dialect.name == "sqlite" and "imposto_percentual" not in proposal_columns:
            conn.execute(text("ALTER TABLE proposals ADD COLUMN imposto_percentual NUMERIC(7,2) NOT NULL DEFAULT 0"))
        if "origem" not in proposal_columns:
            if target_engine.dialect.name == "postgresql":
                statement = "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS origem VARCHAR(30) NOT NULL DEFAULT 'sistema'"
            else:
                statement = "ALTER TABLE proposals ADD COLUMN origem VARCHAR(30) NOT NULL DEFAULT 'sistema'"
            conn.execute(text(statement))


def ensure_schema_compatibility() -> None:
    ensure_schema_compatibility_for_engine(engine)
    ensure_service_history_guards_for_engine(engine)


def ensure_service_history_guards_for_engine(target_engine: Engine) -> None:
    tables = set(inspect(target_engine).get_table_names())
    if not {"service_events", "service_workflow_transitions"}.issubset(tables):
        return

    if target_engine.dialect.name == "sqlite":
        with target_engine.begin() as conn:
            for table in ("service_events", "service_workflow_transitions"):
                for operation in ("UPDATE", "DELETE"):
                    trigger = f"{table}_reject_{operation.lower()}"
                    conn.execute(text(f"CREATE TRIGGER IF NOT EXISTS {trigger} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'service history is immutable'); END"))
    elif target_engine.dialect.name == "postgresql":
        with target_engine.begin() as conn:
            conn.execute(
                text("""
                CREATE OR REPLACE FUNCTION reject_service_history_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'service history is immutable';
                END;
                $$
            """)
            )
            for table in ("service_events", "service_workflow_transitions"):
                trigger = f"{table}_reject_mutation"
                conn.execute(text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
                conn.execute(text(f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_service_history_mutation()"))


@event.listens_for(Session, "before_flush")
def _reject_service_history_mutation(session: Session, flush_context, instances) -> None:
    from .models import ServiceEvent, ServiceWorkflowTransition

    del flush_context, instances
    historical = (ServiceEvent, ServiceWorkflowTransition)
    if any(isinstance(obj, historical) for obj in session.deleted):
        raise ValueError("Historico de servico imutavel: exclusao nao permitida.")
    for obj in session.dirty:
        state = inspect(obj)
        if isinstance(obj, historical) and state.persistent and any(state.attrs[column.key].history.has_changes() for column in state.mapper.column_attrs):
            raise ValueError("Historico de servico imutavel: alteracao nao permitida.")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
