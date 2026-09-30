from __future__ import annotations

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Task


ASSISTANT_TABLES = {
    "assistant_conversations",
    "assistant_messages",
    "assistant_actions",
    "assistant_requests",
}


def test_create_all_adds_assistant_tables_without_changing_existing_tasks(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'existing.sqlite3').as_posix()}")
    old_tables = [
        table
        for table in Base.metadata.sorted_tables
        if table.name not in ASSISTANT_TABLES
    ]
    Base.metadata.create_all(engine, tables=old_tables)
    with Session(engine) as session:
        session.add(Task(titulo="Dado operacional preservado", status="a_fazer", ordem=0))
        session.commit()

    Base.metadata.create_all(engine)

    assert ASSISTANT_TABLES.issubset(set(inspect(engine).get_table_names()))
    with Session(engine) as session:
        assert session.scalar(select(Task.titulo)) == "Dado operacional preservado"
