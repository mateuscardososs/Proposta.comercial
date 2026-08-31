from __future__ import annotations

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


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
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
    if "proposals" not in inspector.get_table_names():
        return

    proposal_columns = {
        str(column["name"])
        for column in inspector.get_columns("proposals")
    }
    with target_engine.begin() as conn:
        if target_engine.dialect.name == "sqlite" and "condicao_pagamento_dias" not in proposal_columns:
            conn.execute(
                text(
                    "ALTER TABLE proposals "
                    "ADD COLUMN condicao_pagamento_dias INTEGER NOT NULL DEFAULT 0"
                )
            )
        if target_engine.dialect.name == "sqlite" and "imposto_percentual" not in proposal_columns:
            conn.execute(
                text(
                    "ALTER TABLE proposals "
                    "ADD COLUMN imposto_percentual NUMERIC(7,2) NOT NULL DEFAULT 0"
                )
            )
        if "origem" not in proposal_columns:
            if target_engine.dialect.name == "postgresql":
                statement = (
                    "ALTER TABLE proposals ADD COLUMN IF NOT EXISTS "
                    "origem VARCHAR(30) NOT NULL DEFAULT 'sistema'"
                )
            else:
                statement = (
                    "ALTER TABLE proposals ADD COLUMN "
                    "origem VARCHAR(30) NOT NULL DEFAULT 'sistema'"
                )
            conn.execute(text(statement))


def ensure_schema_compatibility() -> None:
    ensure_schema_compatibility_for_engine(engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
