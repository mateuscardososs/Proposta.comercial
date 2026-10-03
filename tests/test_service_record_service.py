from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.db import Base, ensure_service_history_guards_for_engine
from app.models import (
    AssistantAction, AssistantConversation, Client, ServiceCall, ServiceEvent,
    ServiceTaskLink, ServiceWorkflowStep, ServiceWorkflowTransition, Task,
)
from app.schemas import (
    ServiceCallQuery,
    ServiceEventCorrectionCreate,
    ServiceEventCreate,
    ServiceReminderCreate,
    ServiceStepChange,
)


STEP_TYPES = {"report", "proposal", "proposal_sent", "invoice", "receipt"}


@pytest.fixture(autouse=True)
def reset_database():
    """Override the shared drop_all fixture: correction chains use restrictive self FKs."""
    yield


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'service.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    ensure_service_history_guards_for_engine(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _context(db):
    client = Client(razao_social="Cliente")
    conversation = AssistantConversation()
    db.add_all([client, conversation])
    db.commit()
    return client, conversation


def _action(db, conversation, number):
    action = AssistantAction(
        conversation_id=conversation.id, request_id=f"service-{number}",
        confirmation_token_hash=f"service-hash-{number}", action_type="register_service_event",
        status="confirmed",
    )
    db.add(action)
    db.commit()
    return action


def _register(db, client, conversation, action, event_type, *, call_id=None, day=2, changes=()):
    from app.services.service_record_service import register_event

    return register_event(
        db,
        ServiceEventCreate(
            client_id=client.id, service_call_id=call_id, summary="Balança",
            event_type=event_type, occurred_on=date(2026, 10, day),
            description=event_type, step_changes=list(changes),
        ),
        conversation_id=conversation.id, assistant_action_id=action.id,
    )


def _correct(db, conversation, action, call_id, event_id, **fields):
    from app.services.service_record_service import correct_event

    return correct_event(
        db,
        ServiceEventCorrectionCreate(
            service_call_id=call_id, supersedes_event_id=event_id,
            occurred_on=date(2026, 10, 4), reason="Corrigir registro", **fields,
        ),
        conversation_id=conversation.id, assistant_action_id=action.id,
    )


def test_new_call_has_independent_initial_states_and_five_unknown_steps(db):
    client = Client(razao_social="Cliente de teste")
    db.add(client)
    db.flush()
    call = ServiceCall(client_id=client.id, summary="Verificar balanca", opened_on=date(2026, 10, 2))
    db.add(call)
    db.flush()
    db.add_all(ServiceWorkflowStep(service_call_id=call.id, step_type=kind) for kind in STEP_TYPES)
    db.commit()

    assert call.execution_status == "not_started"
    assert call.administrative_status == "open"
    steps = db.scalars(select(ServiceWorkflowStep).where(ServiceWorkflowStep.service_call_id == call.id)).all()
    assert {step.step_type for step in steps} == STEP_TYPES
    assert {step.status for step in steps} == {"unknown"}


def test_service_dtos_validate_correction_and_query_bounds():
    payload = ServiceEventCreate(
        client_id=1, summary="Novo chamado", event_type="inspection",
        occurred_on=date(2026, 10, 2), description="Inspecao no local",
        step_changes=[ServiceStepChange(step_type="report", status="pending")],
    )
    assert payload.step_changes[0].note == ""
    assert ServiceCallQuery().limit == 20
    assert ServiceReminderCreate(title="Retornar ao cliente").status == "a_fazer"

    with pytest.raises(ValidationError, match="Informe ao menos um campo corrigido"):
        ServiceEventCorrectionCreate(
            service_call_id=1, supersedes_event_id=1,
            occurred_on=date(2026, 10, 2), reason="Data incorreta",
        )
    with pytest.raises(ValidationError):
        ServiceCallQuery(limit=51)
    with pytest.raises(ValidationError):
        ServiceEventCreate(
            client_id=1, summary="Novo chamado", event_type="inspection",
            occurred_on=date(2026, 10, 2), description="Inspecao",
            step_changes=[ServiceStepChange(step_type="report", status="pending")] * 6,
        )


def test_inspection_does_not_complete_execution(db):
    client, conversation = _context(db)
    result = _register(db, client, conversation, _action(db, conversation, 1), "inspection")
    assert result.service_call.execution_status == "not_started"
    assert result.service_call.administrative_status == "open"
    assert len(result.service_call.workflow_steps) == 5
    assert {step.status for step in result.service_call.workflow_steps} == {"unknown"}


def test_execution_started_marks_in_progress(db):
    client, conversation = _context(db)
    result = _register(db, client, conversation, _action(db, conversation, 1), "execution_started")
    assert result.service_call.execution_status == "in_progress"
    assert result.service_call.technically_completed_at is None


def test_explicit_execution_completed_marks_only_technical_completion(db):
    client, conversation = _context(db)
    result = _register(db, client, conversation, _action(db, conversation, 1), "execution_completed")
    assert result.service_call.execution_status == "completed"
    assert result.service_call.technically_completed_at is not None
    assert result.service_call.administrative_status == "open"


def test_report_pending_keeps_administration_open(db):
    client, conversation = _context(db)
    result = _register(db, client, conversation, _action(db, conversation, 1), "execution_completed",
                       changes=[ServiceStepChange(step_type="report", status="pending")])
    assert result.service_call.administrative_status == "open"
    assert next(step for step in result.service_call.workflow_steps if step.step_type == "report").status == "pending"


def test_proposal_not_applicable_does_not_force_order(db):
    client, conversation = _context(db)
    result = _register(db, client, conversation, _action(db, conversation, 1), "inspection",
                       changes=[ServiceStepChange(step_type="proposal", status="not_applicable")])
    assert result.transitions[0].previous_status == "unknown"
    assert result.transitions[0].new_status == "not_applicable"


def test_administration_closes_only_when_execution_and_all_steps_are_terminal(db):
    client, conversation = _context(db)
    changes = [ServiceStepChange(step_type=kind, status="not_applicable") for kind in sorted(STEP_TYPES)]
    result = _register(db, client, conversation, _action(db, conversation, 1), "inspection", changes=changes)
    assert result.service_call.administrative_status == "open"
    result = _register(db, client, conversation, _action(db, conversation, 2), "execution_completed",
                       call_id=result.service_call.id)
    assert result.service_call.administrative_status == "closed"
    assert result.service_call.administratively_closed_at is not None


def test_unknown_to_pending_to_waiting_customer_records_two_transitions(db):
    client, conversation = _context(db)
    first = _register(db, client, conversation, _action(db, conversation, 1), "note",
                      changes=[ServiceStepChange(step_type="report", status="pending")])
    second = _register(db, client, conversation, _action(db, conversation, 2), "note",
                       call_id=first.service_call.id,
                       changes=[ServiceStepChange(step_type="report", status="waiting_customer", note="Aguardando")])
    assert [(t.previous_status, t.new_status) for t in (first.transitions[0], second.transitions[0])] == [
        ("unknown", "pending"), ("pending", "waiting_customer")]
    assert second.transitions[0].observation == "Aguardando"


def test_one_action_changes_multiple_steps_with_one_event(db):
    client, conversation = _context(db)
    result = _register(db, client, conversation, _action(db, conversation, 1), "note", changes=[
        ServiceStepChange(step_type="report", status="pending"),
        ServiceStepChange(step_type="invoice", status="not_applicable"),
    ])
    assert len(result.transitions) == 2
    assert db.scalar(select(func.count()).select_from(ServiceEvent)) == 1
    assert {t.service_event_id for t in result.transitions} == {result.event.id}


def test_duplicate_assistant_action_reconciles_event_and_transitions(db):
    client, conversation = _context(db)
    action = _action(db, conversation, 1)
    first = _register(db, client, conversation, action, "note", changes=[
        ServiceStepChange(step_type="report", status="pending")])
    replay = _register(db, client, conversation, action, "note", changes=[
        ServiceStepChange(step_type="report", status="pending")])
    assert replay.event.id == first.event.id
    assert [t.id for t in replay.transitions] == [t.id for t in first.transitions]
    assert db.scalar(select(func.count()).select_from(ServiceCall)) == 1


def test_correction_completed_to_inspection_reprojects_to_in_progress(db):
    client, conversation = _context(db)
    start = _register(db, client, conversation, _action(db, conversation, 1), "execution_started")
    done = _register(db, client, conversation, _action(db, conversation, 2), "execution_completed",
                     call_id=start.service_call.id)
    corrected = _correct(db, conversation, _action(db, conversation, 3), done.service_call.id,
                         done.event.id, corrected_event_type="inspection")
    assert corrected.service_call.execution_status == "in_progress"
    assert corrected.service_call.technically_completed_at is None
    assert corrected.service_call.administrative_status == "open"


def test_correction_completed_to_inspection_without_start_reprojects_to_not_started(db):
    client, conversation = _context(db)
    done = _register(db, client, conversation, _action(db, conversation, 1), "execution_completed")
    corrected = _correct(db, conversation, _action(db, conversation, 2), done.service_call.id,
                         done.event.id, corrected_event_type="inspection")
    assert corrected.service_call.execution_status == "not_started"
    assert corrected.service_call.technically_completed_at is None


def test_description_only_correction_keeps_completed_projection(db):
    client, conversation = _context(db)
    done = _register(db, client, conversation, _action(db, conversation, 1), "execution_completed")
    corrected = _correct(db, conversation, _action(db, conversation, 2), done.service_call.id,
                         done.event.id, corrected_description="Reparo concluido")
    assert corrected.service_call.execution_status == "completed"
    assert corrected.service_call.technically_completed_at is not None


def test_correction_chain_rejects_branch(db):
    client, conversation = _context(db)
    original = _register(db, client, conversation, _action(db, conversation, 1), "note")
    first = _correct(db, conversation, _action(db, conversation, 2), original.service_call.id,
                     original.event.id, corrected_description="A")
    with pytest.raises(ValueError, match="folha|corrigido"):
        _correct(db, conversation, _action(db, conversation, 3), original.service_call.id,
                 original.event.id, corrected_description="B")
    second = _correct(db, conversation, _action(db, conversation, 4), original.service_call.id,
                      first.event.id, corrected_description="C")
    assert second.event.supersedes_event_id == first.event.id


def test_correction_preserves_original_event(db):
    client, conversation = _context(db)
    original = _register(db, client, conversation, _action(db, conversation, 1), "note")
    _correct(db, conversation, _action(db, conversation, 2), original.service_call.id,
             original.event.id, corrected_description="Corrigida")
    db.refresh(original.event)
    assert original.event.description == "note"


def test_effective_events_sort_by_effective_date_and_leaf_id_on_tie(db):
    from app.services.service_record_service import effective_service_events

    client, conversation = _context(db)
    first = _register(db, client, conversation, _action(db, conversation, 1), "execution_completed", day=3)
    second = _register(db, client, conversation, _action(db, conversation, 2), "execution_started",
                       call_id=first.service_call.id, day=2)
    correction = _correct(db, conversation, _action(db, conversation, 3), first.service_call.id,
                          first.event.id, corrected_occurred_on=date(2026, 10, 2))
    effective = effective_service_events(db.scalars(select(ServiceEvent).where(
        ServiceEvent.service_call_id == first.service_call.id)).all())
    assert [(e.source_event_id, e.leaf_event_id) for e in effective] == [
        (second.event.id, second.event.id), (first.event.id, correction.event.id)]
    assert correction.service_call.execution_status == "completed"


def test_queries_filter_open_pending_and_client(db):
    from app.services.service_record_service import find_open_calls_for_client, get_service_call, list_service_calls

    client, conversation = _context(db)
    result = _register(db, client, conversation, _action(db, conversation, 1), "inspection")
    assert [call.id for call in list_service_calls(db, ServiceCallQuery(client_id=client.id, pending_only=True))] == [result.service_call.id]
    assert [call.id for call in find_open_calls_for_client(db, client.id)] == [result.service_call.id]
    assert get_service_call(db, result.service_call.id).id == result.service_call.id
    assert get_service_call(db, 999999) is None


def test_reminders_use_board_service_and_link_tasks_once(db):
    from app.services.service_record_service import create_reminders

    client, conversation = _context(db)
    result = _register(db, client, conversation, _action(db, conversation, 1), "note")
    action = _action(db, conversation, 2)
    reminders = [ServiceReminderCreate(title="Enviar laudo", step_type="report"),
                 ServiceReminderCreate(title="Ligar cliente")]
    tasks = create_reminders(db, service_call_id=result.service_call.id,
                             assistant_action_id=action.id, reminders=reminders)
    replay = create_reminders(db, service_call_id=result.service_call.id,
                              assistant_action_id=action.id, reminders=reminders)
    assert [task.id for task in replay] == [task.id for task in tasks]
    assert db.scalar(select(func.count()).select_from(Task)) == 2
    links = db.scalars(select(ServiceTaskLink).order_by(ServiceTaskLink.id)).all()
    assert [link.step_type for link in links] == ["report", None]
    assert all(task.client_id == client.id for task in tasks)


def test_event_failure_rolls_back_event_transitions_and_projection(db, monkeypatch):
    client, conversation = _context(db)
    initial = _register(db, client, conversation, _action(db, conversation, 1), "inspection")
    action = _action(db, conversation, 2)
    inserts = 0

    def fail_second_insert(mapper, connection, target):
        nonlocal inserts
        inserts += 1
        if inserts == 2:
            raise RuntimeError("injected")

    event.listen(ServiceWorkflowTransition, "before_insert", fail_second_insert)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            _register(db, client, conversation, action, "note", call_id=initial.service_call.id, changes=[
            ServiceStepChange(step_type="report", status="pending"),
            ServiceStepChange(step_type="invoice", status="completed"),
            ])
    finally:
        event.remove(ServiceWorkflowTransition, "before_insert", fail_second_insert)
    assert inserts == 2
    assert db.scalar(select(func.count()).select_from(ServiceEvent)) == 1
    assert db.scalar(select(func.count()).select_from(ServiceWorkflowTransition)) == 0
    db.refresh(initial.service_call)
    assert initial.service_call.execution_status == "not_started"
    assert {step.status for step in initial.service_call.workflow_steps} == {"unknown"}


def test_reminder_failure_rolls_back_tasks_and_links(db, monkeypatch):
    import app.services.service_record_service as service

    client, conversation = _context(db)
    result = _register(db, client, conversation, _action(db, conversation, 1), "note")
    action = _action(db, conversation, 2)
    original = service.board_service.create_task
    calls = 0

    def fail_second(session, payload, *, commit=True):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected")
        return original(session, payload, commit=commit)

    monkeypatch.setattr(service.board_service, "create_task", fail_second)
    with pytest.raises(RuntimeError, match="injected"):
        service.create_reminders(db, service_call_id=result.service_call.id,
                                 assistant_action_id=action.id,
                                 reminders=[ServiceReminderCreate(title="A"), ServiceReminderCreate(title="B")])
    assert db.scalar(select(func.count()).select_from(Task)) == 0
    assert db.scalar(select(func.count()).select_from(ServiceTaskLink)) == 0


def test_register_event_commit_false_is_rolled_back_by_outer_transaction(db):
    from app.services.service_record_service import register_event

    client, conversation = _context(db)
    action = _action(db, conversation, 1)
    payload = ServiceEventCreate(
        client_id=client.id, summary="Balança", event_type="inspection",
        occurred_on=date(2026, 10, 2), description="Visita",
        step_changes=[ServiceStepChange(step_type="report", status="pending")],
    )
    result = register_event(db, payload, conversation_id=conversation.id,
                            assistant_action_id=action.id, commit=False)
    call_id = result.service_call.id
    db.rollback()

    with Session(db.get_bind()) as observer:
        assert observer.get(ServiceCall, call_id) is None
        assert observer.scalar(select(func.count()).select_from(ServiceEvent)) == 0
        assert observer.scalar(select(func.count()).select_from(ServiceWorkflowTransition)) == 0


def test_correct_event_commit_false_is_rolled_back_by_outer_transaction(db):
    client, conversation = _context(db)
    start = _register(db, client, conversation, _action(db, conversation, 1), "execution_started")
    completed = _register(db, client, conversation, _action(db, conversation, 2),
                          "execution_completed", call_id=start.service_call.id)
    action = _action(db, conversation, 3)
    from app.services.service_record_service import correct_event

    result = correct_event(
        db, ServiceEventCorrectionCreate(
            service_call_id=start.service_call.id, supersedes_event_id=completed.event.id,
            occurred_on=date(2026, 10, 4), reason="Na verdade foi inspeção",
            corrected_event_type="inspection",
        ), conversation_id=conversation.id, assistant_action_id=action.id, commit=False,
    )
    assert result.service_call.execution_status == "in_progress"
    db.rollback()

    with Session(db.get_bind()) as observer:
        call = observer.get(ServiceCall, start.service_call.id)
        assert call.execution_status == "completed"
        assert observer.scalar(select(func.count()).select_from(ServiceEvent)) == 2


def test_create_reminders_commit_false_is_rolled_back_by_outer_transaction(db):
    from app.services.service_record_service import create_reminders

    client, conversation = _context(db)
    result = _register(db, client, conversation, _action(db, conversation, 1), "note")
    action = _action(db, conversation, 2)
    create_reminders(
        db, service_call_id=result.service_call.id, assistant_action_id=action.id,
        reminders=[ServiceReminderCreate(title="Relatório")], commit=False,
    )
    db.rollback()

    with Session(db.get_bind()) as observer:
        assert observer.scalar(select(func.count()).select_from(Task)) == 0
        assert observer.scalar(select(func.count()).select_from(ServiceTaskLink)) == 0
