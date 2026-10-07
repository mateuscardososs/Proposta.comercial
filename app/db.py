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
    _relax_service_report_event_links(target_engine, table_names)
    if "tasks" in table_names:
        task_columns = {str(column["name"]) for column in inspector.get_columns("tasks")}
        task_additions = (
            ("client_name", "VARCHAR(255)", None),
            ("client_link_status", "VARCHAR(30)", "'unlinked'"),
            ("estimated_duration_minutes", "INTEGER", None),
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
            ("extracted_fields", "JSON", None, None),
        ):
            if column_name in email_columns:
                continue
            if target_engine.dialect.name == "postgresql":
                if postgres_default is None:
                    statement = f"ALTER TABLE inbox_emails ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
                else:
                    statement = f"ALTER TABLE inbox_emails ADD COLUMN IF NOT EXISTS {column_name} {column_type} NOT NULL DEFAULT {postgres_default}"
            else:
                if sqlite_default is None:
                    statement = f"ALTER TABLE inbox_emails ADD COLUMN {column_name} {column_type}"
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
    if "lancamentos" in table_names:
        lancamento_columns = {
            str(column["name"]) for column in inspector.get_columns("lancamentos")
        }
        if "arquivado_em" not in lancamento_columns:
            statement = (
                "ALTER TABLE lancamentos ADD COLUMN IF NOT EXISTS arquivado_em DATE"
                if target_engine.dialect.name == "postgresql"
                else "ALTER TABLE lancamentos ADD COLUMN arquivado_em DATE"
            )
            with target_engine.begin() as conn:
                conn.execute(text(statement))
        with target_engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_lancamentos_arquivado_em "
                    "ON lancamentos (arquivado_em)"
                )
            )
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


def _relax_service_report_event_links(target_engine: Engine, table_names: set[str]) -> None:
    """Allow document/admin history to exist without fabricating a technical event."""
    requirements = {
        "service_workflow_transitions": {"service_event_id"},
        "service_technical_reports": {"document_event_id"},
    }
    required_changes: list[tuple[str, str]] = []
    current_inspector = inspect(target_engine)
    for table_name, column_names in requirements.items():
        if table_name not in table_names:
            continue
        for column in current_inspector.get_columns(table_name):
            if column["name"] in column_names and not column["nullable"]:
                required_changes.append((table_name, str(column["name"])))
    if not required_changes:
        return

    if target_engine.dialect.name == "postgresql":
        with target_engine.begin() as connection:
            for table_name, column_name in required_changes:
                connection.execute(text(
                    f'ALTER TABLE "{table_name}" ALTER COLUMN "{column_name}" DROP NOT NULL'
                ))
        return

    if target_engine.dialect.name != "sqlite":
        raise RuntimeError("Migração de vínculos opcionais de relatório não suportada neste banco.")

    # SQLite cannot alter nullability in place. Rebuild only the two affected tables,
    # copying every column verbatim. Foreign keys are re-enabled and checked before return.
    metadata = Base.metadata
    with target_engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        transaction = connection.begin()
        try:
            for table_name in dict.fromkeys(table for table, _ in required_changes):
                old_table = f"_compat_old_{table_name}"
                if old_table in inspect(connection).get_table_names():
                    raise RuntimeError(f"Migração SQLite interrompida: tabela temporária {old_table} existe.")
                table = metadata.tables[table_name]
                names = [column.name for column in table.columns]
                quoted_names = ", ".join(f'"{name}"' for name in names)
                connection.exec_driver_sql(f'ALTER TABLE "{table_name}" RENAME TO "{old_table}"')
                for index in inspect(connection).get_indexes(old_table):
                    index_name = index.get("name")
                    if index_name:
                        connection.exec_driver_sql(f'DROP INDEX "{index_name}"')
                table.create(connection)
                connection.exec_driver_sql(
                    f'INSERT INTO "{table_name}" ({quoted_names}) '
                    f'SELECT {quoted_names} FROM "{old_table}"'
                )
                connection.exec_driver_sql(f'DROP TABLE "{old_table}"')
            transaction.commit()
        except Exception:
            transaction.rollback()
            raise
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError("Migração SQLite deixou violações de chave estrangeira.")


def ensure_schema_compatibility() -> None:
    ensure_schema_compatibility_for_engine(engine)
    ensure_service_history_guards_for_engine(engine)


def ensure_service_history_guards_for_engine(target_engine: Engine) -> None:
    tables = set(inspect(target_engine).get_table_names())
    service_tables = {"service_events", "service_workflow_transitions", "service_technical_reports"}.intersection(tables)
    finance_tables = {"lancamento_historicos"}.intersection(tables)
    schedule_tables = {"daily_schedule_snapshots"}.intersection(tables)
    if not service_tables and not finance_tables and not schedule_tables:
        return

    if target_engine.dialect.name == "sqlite":
        with target_engine.begin() as conn:
            for table in service_tables:
                for operation in ("UPDATE", "DELETE"):
                    trigger = f"{table}_reject_{operation.lower()}"
                    conn.execute(text(f"CREATE TRIGGER IF NOT EXISTS {trigger} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'service history is immutable'); END"))
            for operation in ("UPDATE", "DELETE"):
                trigger = f"lancamento_historicos_reject_{operation.lower()}"
                conn.execute(text(f"CREATE TRIGGER IF NOT EXISTS {trigger} BEFORE {operation} ON lancamento_historicos BEGIN SELECT RAISE(ABORT, 'financial history is immutable'); END"))
            for table in schedule_tables:
                for operation in ("UPDATE", "DELETE"):
                    trigger = f"{table}_reject_{operation.lower()}"
                    conn.execute(text(f"CREATE TRIGGER IF NOT EXISTS {trigger} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'daily schedule history is immutable'); END"))
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
            for table in service_tables:
                trigger = f"{table}_reject_mutation"
                conn.execute(text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
                conn.execute(text(f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_service_history_mutation()"))
            if finance_tables:
                conn.execute(
                    text("""
                    CREATE OR REPLACE FUNCTION reject_financial_history_mutation()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN
                        RAISE EXCEPTION 'financial history is immutable';
                    END;
                    $$
                """)
                )
                conn.execute(text("DROP TRIGGER IF EXISTS lancamento_historicos_reject_mutation ON lancamento_historicos"))
                conn.execute(text("CREATE TRIGGER lancamento_historicos_reject_mutation BEFORE UPDATE OR DELETE ON lancamento_historicos FOR EACH ROW EXECUTE FUNCTION reject_financial_history_mutation()"))
            if schedule_tables:
                conn.execute(
                    text("""
                    CREATE OR REPLACE FUNCTION reject_daily_schedule_mutation()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN
                        RAISE EXCEPTION 'daily schedule history is immutable';
                    END;
                    $$
                    """)
                )
                for table in schedule_tables:
                    trigger = f"{table}_reject_mutation"
                    conn.execute(text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
                    conn.execute(text(f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_daily_schedule_mutation()"))


@event.listens_for(Session, "before_flush")
def _reject_service_history_mutation(session: Session, flush_context, instances) -> None:
    from .models import (
        LancamentoHistorico,
        ServiceEvent,
        ServiceTechnicalReport,
        ServiceWorkflowTransition,
    )

    del flush_context, instances
    historical = (ServiceEvent, ServiceWorkflowTransition, ServiceTechnicalReport)
    if any(isinstance(obj, LancamentoHistorico) for obj in session.deleted):
        raise ValueError("Histórico financeiro imutável: exclusão não permitida.")
    if any(isinstance(obj, historical) for obj in session.deleted):
        raise ValueError("Historico de servico imutavel: exclusao nao permitida.")
    for obj in session.dirty:
        state = inspect(obj)
        if isinstance(obj, LancamentoHistorico) and state.persistent and any(
            state.attrs[column.key].history.has_changes()
            for column in state.mapper.column_attrs
        ):
            raise ValueError("Histórico financeiro imutável: alteração não permitida.")
        if isinstance(obj, historical) and state.persistent and any(state.attrs[column.key].history.has_changes() for column in state.mapper.column_attrs):
            raise ValueError("Historico de servico imutavel: alteracao nao permitida.")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
