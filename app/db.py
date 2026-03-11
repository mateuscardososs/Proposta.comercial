from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
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
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


class Base(DeclarativeBase):
    pass


def ensure_schema_compatibility() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as conn:
        tables = {
            str(row[0])
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        if "proposals" not in tables:
            return

        proposal_columns = {
            str(row[1])
            for row in conn.execute(text("PRAGMA table_info('proposals')"))
        }
        if "condicao_pagamento_dias" not in proposal_columns:
            conn.execute(
                text(
                    "ALTER TABLE proposals "
                    "ADD COLUMN condicao_pagamento_dias INTEGER NOT NULL DEFAULT 0"
                )
            )
        if "imposto_percentual" not in proposal_columns:
            conn.execute(
                text(
                    "ALTER TABLE proposals "
                    "ADD COLUMN imposto_percentual NUMERIC(7,2) NOT NULL DEFAULT 0"
                )
            )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
