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

from app.db import Base, SessionLocal, engine  # noqa: E402


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
