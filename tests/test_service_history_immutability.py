from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db import Base, ensure_service_history_guards_for_engine
from app.models import (
    AssistantAction, AssistantConversation, Client, ServiceCall, ServiceEvent,
    ServiceWorkflowStep, ServiceWorkflowTransition,
)


def _history_fixture(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'history.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    ensure_service_history_guards_for_engine(engine)
    with Session(engine) as session:
        client = Client(razao_social="Cliente")
        conversation = AssistantConversation()
        session.add_all([client, conversation])
        session.flush()
        action = AssistantAction(
            conversation_id=conversation.id, request_id="r1", confirmation_token_hash="h1",
            action_type="registrar_evento_servico", status="confirmed",
        )
        call = ServiceCall(client_id=client.id, summary="Chamado", opened_on=date(2026, 10, 2))
        session.add_all([action, call])
        session.flush()
        step = ServiceWorkflowStep(service_call_id=call.id, step_type="report")
        event = ServiceEvent(
            service_call_id=call.id, assistant_action_id=action.id,
            event_type="call_received", occurred_on=date(2026, 10, 2), description="Recebido",
        )
        session.add_all([step, event])
        session.flush()
        transition = ServiceWorkflowTransition(
            service_call_id=call.id, step_type="report", previous_status="unknown",
            new_status="pending", observation="", service_event_id=event.id,
            assistant_action_id=action.id,
        )
        session.add(transition)
        session.commit()
        ids = (call.id, step.id, event.id, transition.id, action.id)
    return engine, ids


def test_historical_relationships_and_foreign_keys_restrict_deletion():
    for relation in (ServiceCall.events, ServiceCall.workflow_transitions):
        cascades = relation.property.cascade
        assert "delete" not in cascades
        assert "delete-orphan" not in cascades
        assert relation.property.passive_deletes is True
    for model in (ServiceEvent, ServiceWorkflowTransition):
        assert all(fk.ondelete in {"RESTRICT", "NO ACTION"} for fk in model.__table__.foreign_keys)


def test_sqlite_enables_foreign_keys_and_rejects_mismatched_transition(tmp_path):
    engine, (call_id, _, event_id, _, action_id) = _history_fixture(tmp_path)
    with engine.connect() as conn:
        assert conn.scalar(text("PRAGMA foreign_keys")) == 1
        assert conn.scalar(text("PRAGMA recursive_triggers")) == 1
    with Session(engine) as session:
        other_client = Client(razao_social="Outro")
        other_action = AssistantAction(
            conversation=AssistantConversation(), request_id="r2", confirmation_token_hash="h2",
            action_type="registrar_evento_servico", status="confirmed",
        )
        session.add_all([other_client, other_action])
        session.flush()
        other_call = ServiceCall(client_id=other_client.id, summary="Outro", opened_on=date(2026, 10, 2))
        session.add(other_call)
        session.flush()
        session.add(ServiceWorkflowStep(service_call_id=other_call.id, step_type="report"))
        new_action = AssistantAction(
            conversation_id=other_action.conversation_id, request_id="r3", confirmation_token_hash="h3",
            action_type="registrar_evento_servico", status="confirmed",
        )
        session.add(new_action)
        session.flush()
        new_event = ServiceEvent(
            service_call_id=call_id, assistant_action_id=new_action.id,
            event_type="note", occurred_on=date(2026, 10, 2), description="Nota",
        )
        session.add(new_event)
        session.commit()
        with pytest.raises(DBAPIError) as call_mismatch:
            session.add(ServiceWorkflowTransition(
                service_call_id=other_call.id, step_type="report", previous_status="unknown",
                new_status="pending", observation="", service_event_id=new_event.id,
                assistant_action_id=new_action.id,
            ))
            session.commit()
        assert "FOREIGN KEY constraint failed" in str(call_mismatch.value.orig)
        session.rollback()
        with pytest.raises(DBAPIError) as action_mismatch:
            session.add(ServiceWorkflowTransition(
                service_call_id=call_id, step_type="report", previous_status="unknown",
                new_status="pending", observation="", service_event_id=event_id,
                assistant_action_id=other_action.id,
            ))
            session.commit()
        assert "FOREIGN KEY constraint failed" in str(action_mismatch.value.orig)
        session.rollback()


@pytest.mark.parametrize("table", ["service_events", "service_workflow_transitions"])
def test_insert_or_replace_cannot_replace_history_row(tmp_path, table):
    engine, (call_id, _, event_id, transition_id, action_id) = _history_fixture(tmp_path)
    if table == "service_events":
        with Session(engine) as session:
            original_action = session.get(AssistantAction, action_id)
            action = AssistantAction(
                conversation_id=original_action.conversation_id, request_id="r3",
                confirmation_token_hash="h3", action_type="registrar_evento_servico",
                status="confirmed",
            )
            session.add(action)
            session.flush()
            unreferenced_event = ServiceEvent(
                service_call_id=call_id, assistant_action_id=action.id,
                event_type="note", occurred_on=date(2026, 10, 2), description="Original",
            )
            session.add(unreferenced_event)
            session.commit()
            identifier = unreferenced_event.id
        statement = text("""
            INSERT OR REPLACE INTO service_events
                (id, service_call_id, assistant_action_id, event_type, occurred_on, description, created_at)
            SELECT id, service_call_id, assistant_action_id, event_type, occurred_on, 'Substituido', created_at
            FROM service_events WHERE id = :id
        """)
        read_value = select(ServiceEvent.description).where(ServiceEvent.id == identifier)
        expected = "Original"
    else:
        identifier = transition_id
        statement = text("""
            INSERT OR REPLACE INTO service_workflow_transitions
                (id, service_call_id, step_type, previous_status, new_status, observation,
                 service_event_id, assistant_action_id, created_at)
            SELECT id, service_call_id, step_type, previous_status, new_status, 'Substituido',
                   service_event_id, assistant_action_id, created_at
            FROM service_workflow_transitions WHERE id = :id
        """)
        read_value = select(ServiceWorkflowTransition.observation).where(
            ServiceWorkflowTransition.id == identifier
        )
        expected = ""

    with pytest.raises(DBAPIError, match="service history is immutable"):
        with engine.begin() as conn:
            conn.execute(statement, {"id": identifier})
    with Session(engine) as session:
        assert session.scalar(read_value) == expected


def test_sql_direct_cannot_mutate_history_or_delete_referenced_rows(tmp_path):
    engine, (call_id, step_id, event_id, transition_id, action_id) = _history_fixture(tmp_path)
    statements = [
        ("UPDATE service_events SET description='alterado' WHERE id=:id", event_id),
        ("DELETE FROM service_events WHERE id=:id", event_id),
        ("UPDATE service_workflow_transitions SET observation='alterado' WHERE id=:id", transition_id),
        ("DELETE FROM service_workflow_transitions WHERE id=:id", transition_id),
        ("DELETE FROM service_calls WHERE id=:id", call_id),
        ("DELETE FROM service_workflow_steps WHERE id=:id", step_id),
        ("DELETE FROM assistant_actions WHERE id=:id", action_id),
    ]
    for statement, identifier in statements:
        with pytest.raises(DBAPIError):
            with engine.begin() as conn:
                conn.execute(text(statement), {"id": identifier})
    with Session(engine) as session:
        assert session.scalar(select(ServiceEvent.description)) == "Recebido"
        assert session.scalar(select(ServiceWorkflowTransition.observation)) == ""
        assert session.scalar(select(ServiceCall.id)) == call_id
        assert session.scalar(select(ServiceWorkflowStep.id)) == step_id
        assert session.scalar(select(AssistantAction.id)) == action_id


def test_orm_rejects_history_update_and_delete_before_flush(tmp_path):
    engine, (_, _, event_id, transition_id, _) = _history_fixture(tmp_path)
    with Session(engine) as session:
        event = session.get(ServiceEvent, event_id)
        event.description = "Alterado"
        with pytest.raises(ValueError, match="imutavel"):
            session.flush()
        session.rollback()
    with Session(engine) as session:
        transition = session.get(ServiceWorkflowTransition, transition_id)
        session.delete(transition)
        with pytest.raises(ValueError, match="imutavel"):
            session.flush()
        session.rollback()
