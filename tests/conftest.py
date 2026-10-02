from __future__ import annotations

import os
from pathlib import Path
from tempfile import gettempdir

import pytest


TEST_DB_PATH = Path(gettempdir()) / "proposta_comercial_financeiro_tests.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["OUTPUT_DIR"] = str(Path(gettempdir()) / "proposta_comercial_test_output")
os.environ["TEMPLATE_DOC_PATH"] = str(
    Path(gettempdir()) / "proposta_comercial_test_templates" / "proposta_template.docx"
)

from app.db import Base, SessionLocal, engine, ensure_service_history_guards_for_engine  # noqa: E402


def _drop_test_schema() -> None:
    """Reset only the explicitly isolated pytest database, including RESTRICT history FKs."""
    if engine.dialect.name == "sqlite":
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            Base.metadata.drop_all(bind=connection)
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
        return
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def reset_database():
    _drop_test_schema()
    Base.metadata.create_all(bind=engine)
    ensure_service_history_guards_for_engine(engine)
    yield
    _drop_test_schema()


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
