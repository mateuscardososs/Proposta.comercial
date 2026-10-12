from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.assistant.contracts import ServiceQueryCommand
from app.assistant.service_records import AssistantServiceRecordAdapter
from app.db import Base
from app.services import service_record_service


def adapter(db, resolve_client):
    return AssistantServiceRecordAdapter(
        db, today=lambda: date(2026, 10, 11), resolve_client=resolve_client,
        resolve_user=Mock(), token_hash=Mock(),
    )


def test_ambiguous_client_never_queries(monkeypatch):
    listing = Mock(side_effect=AssertionError("must not list"))
    monkeypatch.setattr(service_record_service, "list_service_calls", listing)
    resolver = Mock(return_value=(None, "Qual Alfa?"))
    execution = adapter(object(), resolver).execute_query(12, ServiceQueryCommand(client="Alfa"))
    assert execution.reply.model_dump()["message"] == "Qual Alfa?"
    assert execution.reply.kind == "clarification"
    assert execution.reply.conversation_id == 12
    assert execution.result is None
    resolver.assert_called_once_with("Alfa")
    listing.assert_not_called()


@pytest.mark.parametrize("with_client", [True, False])
def test_filters_empty_and_current_callback(monkeypatch, with_client):
    db = object()
    listing = Mock(return_value=[])
    monkeypatch.setattr(service_record_service, "list_service_calls", listing)
    monkeypatch.setattr("app.assistant.service_records.secrets.token_urlsafe", lambda size: f"evidence-{size}")
    instance = adapter(db, Mock(side_effect=AssertionError("stale callback")))
    instance.resolve_client = Mock(return_value=(SimpleNamespace(id=7) if with_client else None, None))
    command = ServiceQueryCommand(client="Alfa", execution_status="in_progress", administrative_status="open", pending_only=True, return_tasks_only=True, limit=4)
    execution = instance.execute_query(13, command)
    actual_db, query = listing.call_args.args
    assert actual_db is db
    assert query.model_dump() == {"client_id": 7 if with_client else None, "execution_status": "in_progress", "administrative_status": "open", "pending_only": True, "return_tasks_only": True, "limit": 4}
    assert execution.reply.message == "Nenhum chamado encontrado para os filtros informados."
    assert execution.result.state == "empty"
    assert execution.result.tool == "consultar_servicos"
    assert execution.result.evidence_id == "evidence-16"
    assert execution.result.payload == {"count": 0, "service_calls": []}


@pytest.mark.parametrize("returns", [False, True])
def test_projection_effective_events_order_and_return_links(monkeypatch, returns):
    day = date(2026, 10, 2)
    events = [SimpleNamespace(id=i, service_call_id=1, event_type="note", occurred_on=day, description=f"event {i}", supersedes_event_id=None) for i in range(1, 6)]
    events.append(SimpleNamespace(id=6, service_call_id=1, event_type="correction", occurred_on=day, description="correction", corrected_event_type="inspection", corrected_occurred_on=None, corrected_description="x" * 260, supersedes_event_id=5))
    def link(task_id, status="pendente", step=None, event=1, deadline=day):
        task = SimpleNamespace(id=task_id, titulo=f"Retorno {task_id}", prazo=deadline, status=status)
        return SimpleNamespace(task=task, step_type=step, service_event_id=event)
    links = [link(8), link(9, deadline=None), link(10, status="concluido"), link(11, step="report"), link(12, event=None), SimpleNamespace(task=None, step_type=None, service_event_id=1)]
    def call(call_id, step_status):
        return SimpleNamespace(id=call_id, client=SimpleNamespace(razao_social="Alfa"), summary=f"Balança {call_id}", execution_status="in_progress", administrative_status="open", opened_on=day, technically_completed_at=day, administratively_closed_at=None, events=events, workflow_steps=[SimpleNamespace(step_type="proposal", status="completed"), SimpleNamespace(step_type="report", status=step_status), SimpleNamespace(step_type="invoice", status="pending")], task_links=links)
    calls = [call(4, "unknown"), call(2, "waiting_customer")]
    monkeypatch.setattr(service_record_service, "list_service_calls", Mock(return_value=calls))
    before = repr(calls), repr(events), repr(links)
    execution = adapter(object(), Mock(return_value=(None, None))).execute_query(14, ServiceQueryCommand(return_tasks_only=returns))
    expected_returns = [{"task_id": 8, "title": "Retorno 8", "due_date": "2026-10-02", "status": "pendente", "source_event_id": 1}, {"task_id": 9, "title": "Retorno 9", "due_date": None, "status": "pendente", "source_event_id": 1}] if returns else []
    expected = []
    for call_id, status in [(4, "unknown"), (2, "waiting_customer")]:
        expected.append({"id": call_id, "client": "Alfa", "summary": f"Balança {call_id}", "execution_status": "in_progress", "administrative_status": "open", "next_pending_step": "report", "opened_on": "2026-10-02", "technically_completed_at": "2026-10-02", "administratively_closed_at": None, "workflow_steps": [{"step_type": "proposal", "status": "completed"}, {"step_type": "report", "status": status}, {"step_type": "invoice", "status": "pending"}], "event_types": ["inspection", "note"], "effective_event_count": 5, "recent_events": [{"event_type": "note", "occurred_on": "2026-10-02", "description": "event 3"}, {"event_type": "note", "occurred_on": "2026-10-02", "description": "event 4"}, {"event_type": "inspection", "occurred_on": "2026-10-02", "description": "x" * 240}], "return_tasks": expected_returns})
    assert execution.result.payload == {"count": 2, "service_calls": expected}
    assert execution.result.state == "success"
    suffix = "; retornos: tarefa #8 Retorno 8 (prazo 2026-10-02), tarefa #9 Retorno 9 (prazo sem prazo)" if returns else ""
    assert execution.reply.message == f"#4 Alfa: Balança 4{suffix}; #2 Alfa: Balança 2{suffix}"
    assert (repr(calls), repr(events), repr(links)) == before


def test_real_session_query_emits_no_dml_or_actions():
    from app.models import AssistantAction, Client, ServiceCall, ServiceEvent, Task

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        client = Client(razao_social="Alfa")
        db.add(client)
        db.flush()
        db.add(ServiceCall(client_id=client.id, summary="Balança", opened_on=date(2026, 10, 2)))
        db.commit()
        models = (ServiceCall, ServiceEvent, Task, AssistantAction)
        before = tuple(db.query(model).count() for model in models)
        statements = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(engine, "before_cursor_execute", capture)
        try:
            execution = adapter(db, Mock(return_value=(client, None))).execute_query(15, ServiceQueryCommand(client="Alfa"))
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert execution.result.payload["count"] == 1
        assert statements
        assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
        assert tuple(db.query(model).count() for model in models) == before
        assert not db.new and not db.dirty and not db.deleted
    engine.dispose()
