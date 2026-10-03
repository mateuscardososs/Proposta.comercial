"""Transactional service-call history and reconstructible current state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import (
    AssistantAction, Client, ServiceCall, ServiceEvent, ServiceTaskLink,
    ServiceWorkflowStep, ServiceWorkflowTransition, Task,
)
from app.schemas import (
    CorrectableServiceEventType, ServiceCallQuery, ServiceEventCorrectionCreate,
    ServiceEventCreate, ServiceReminderCreate, TaskCreate,
)
from app.services import board_service


STEP_TYPES = ("report", "proposal", "proposal_sent", "invoice", "receipt")
TERMINAL_STEP_STATUSES = frozenset(("completed", "not_applicable"))


def _ensure_database_transaction(db: Session) -> None:
    """Ensure SQLite has a real outer transaction before opening a SAVEPOINT.

    sqlite3's legacy transaction mode does not BEGIN for SELECT statements.
    Releasing the first SAVEPOINT can therefore commit it as the outermost
    transaction. Starting BEGIN only when the DBAPI connection is not already
    in a transaction preserves transactions owned by the caller.
    """
    connection = db.connection()
    if connection.dialect.name != "sqlite":
        return
    driver_connection = connection.connection.driver_connection
    if not driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN")


@dataclass(frozen=True)
class ServiceMutationResult:
    service_call: ServiceCall
    event: ServiceEvent
    transitions: Sequence[ServiceWorkflowTransition]


@dataclass(frozen=True)
class EffectiveServiceEvent:
    source_event_id: int
    leaf_event_id: int
    event_type: CorrectableServiceEventType
    occurred_on: date
    description: str


def list_service_calls(db: Session, query: ServiceCallQuery) -> list[ServiceCall]:
    statement = select(ServiceCall).options(
        joinedload(ServiceCall.client),
        selectinload(ServiceCall.workflow_steps),
        selectinload(ServiceCall.events),
    )
    if query.client_id is not None:
        statement = statement.where(ServiceCall.client_id == query.client_id)
    if query.execution_status is not None:
        statement = statement.where(ServiceCall.execution_status == query.execution_status)
    if query.administrative_status is not None:
        statement = statement.where(ServiceCall.administrative_status == query.administrative_status)
    if query.pending_only:
        statement = statement.where(ServiceCall.administrative_status == "open")
    return list(db.scalars(statement.order_by(ServiceCall.opened_on.desc(), ServiceCall.id.desc()).limit(query.limit)))


def get_service_call(db: Session, service_call_id: int) -> ServiceCall | None:
    return db.scalar(
        select(ServiceCall)
        .options(
            joinedload(ServiceCall.client),
            selectinload(ServiceCall.workflow_steps),
            selectinload(ServiceCall.events),
            selectinload(ServiceCall.workflow_transitions),
            selectinload(ServiceCall.task_links).selectinload(ServiceTaskLink.task),
        )
        .where(ServiceCall.id == service_call_id)
    )


def find_open_calls_for_client(db: Session, client_id: int) -> list[ServiceCall]:
    return list_service_calls(db, ServiceCallQuery(client_id=client_id, administrative_status="open", limit=50))


def effective_service_events(events: Sequence[ServiceEvent]) -> list[EffectiveServiceEvent]:
    by_id: dict[int, EffectiveServiceEvent] = {}
    roots: dict[int, EffectiveServiceEvent] = {}
    call_by_id: dict[int, int] = {}
    for event in sorted(events, key=lambda item: item.id):
        if event.event_type != "correction":
            if event.supersedes_event_id is not None:
                raise ValueError("Evento original nao pode substituir outro evento.")
            effective = EffectiveServiceEvent(
                source_event_id=event.id, leaf_event_id=event.id,
                event_type=event.event_type, occurred_on=event.occurred_on,
                description=event.description,
            )
            roots[event.id] = effective
            by_id[event.id] = effective
            call_by_id[event.id] = event.service_call_id
            continue
        parent = by_id.get(event.supersedes_event_id)
        if parent is None or call_by_id[event.supersedes_event_id] != event.service_call_id:
            raise ValueError("Correcao aponta para evento ausente ou de outro chamado.")
        current = roots[parent.source_event_id]
        if current.leaf_event_id != event.supersedes_event_id:
            raise ValueError("Correcao deve apontar para a folha atual.")
        effective = EffectiveServiceEvent(
            source_event_id=parent.source_event_id, leaf_event_id=event.id,
            event_type=event.corrected_event_type or parent.event_type,
            occurred_on=event.corrected_occurred_on or parent.occurred_on,
            description=event.corrected_description if event.corrected_description is not None else parent.description,
        )
        roots[parent.source_event_id] = effective
        by_id[event.id] = effective
        call_by_id[event.id] = event.service_call_id
    return sorted(roots.values(), key=lambda item: (item.occurred_on, item.leaf_event_id))


def rebuild_current_projection(db: Session, service_call: ServiceCall) -> None:
    events = list(db.scalars(select(ServiceEvent).where(
        ServiceEvent.service_call_id == service_call.id).order_by(ServiceEvent.id)))
    effective = effective_service_events(events)
    last_execution = next((event for event in reversed(effective)
                           if event.event_type in ("execution_started", "execution_completed")), None)
    if last_execution is None:
        service_call.execution_status = "not_started"
        service_call.technically_completed_at = None
    elif last_execution.event_type == "execution_started":
        service_call.execution_status = "in_progress"
        service_call.technically_completed_at = None
    else:
        service_call.execution_status = "completed"
        service_call.technically_completed_at = datetime.combine(last_execution.occurred_on, time.min)

    steps = list(db.scalars(select(ServiceWorkflowStep).where(
        ServiceWorkflowStep.service_call_id == service_call.id).order_by(ServiceWorkflowStep.id)))
    statuses = {step.step_type: "unknown" for step in steps}
    transitions = list(db.scalars(select(ServiceWorkflowTransition).where(
        ServiceWorkflowTransition.service_call_id == service_call.id).order_by(ServiceWorkflowTransition.id)))
    for transition in transitions:
        if transition.step_type not in statuses or statuses[transition.step_type] != transition.previous_status:
            raise ValueError("Historico de etapas inconsistente.")
        statuses[transition.step_type] = transition.new_status
    for step in steps:
        step.status = statuses[step.step_type]

    closed = (service_call.execution_status == "completed"
              and len(steps) == len(STEP_TYPES)
              and set(statuses) == set(STEP_TYPES)
              and all(status in TERMINAL_STEP_STATUSES for status in statuses.values()))
    service_call.administrative_status = "closed" if closed else "open"
    service_call.administratively_closed_at = (
        max([service_call.technically_completed_at, *(t.created_at for t in transitions)])
        if closed else None
    )
    db.flush()


def _validate_action(db: Session, assistant_action_id: int, conversation_id: int | None = None) -> AssistantAction:
    action = db.get(AssistantAction, assistant_action_id)
    if action is None or (conversation_id is not None and action.conversation_id != conversation_id):
        raise ValueError("Acao confirmada nao encontrada para a conversa.")
    return action


def _mutation_result(db: Session, event: ServiceEvent) -> ServiceMutationResult:
    call = db.get(ServiceCall, event.service_call_id)
    transitions = list(db.scalars(select(ServiceWorkflowTransition).where(
        ServiceWorkflowTransition.service_event_id == event.id).order_by(ServiceWorkflowTransition.id)))
    return ServiceMutationResult(call, event, transitions)


def register_event(
    db: Session, payload: ServiceEventCreate, *, conversation_id: int,
    assistant_action_id: int, commit: bool = True,
) -> ServiceMutationResult:
    existing = db.scalar(select(ServiceEvent).where(ServiceEvent.assistant_action_id == assistant_action_id))
    if existing is not None:
        return _mutation_result(db, existing)
    _validate_action(db, assistant_action_id, conversation_id)
    if db.get(Client, payload.client_id) is None:
        raise ValueError("Cliente nao encontrado.")
    if payload.event_type == "correction":
        raise ValueError("Use correct_event para registrar correcoes.")
    if payload.service_call_id is not None and payload.force_new_call:
        raise ValueError("Nao e possivel indicar chamado e forcar novo chamado.")
    step_types = [change.step_type for change in payload.step_changes]
    if len(step_types) != len(set(step_types)):
        raise ValueError("Cada etapa pode mudar apenas uma vez por acao.")
    _ensure_database_transaction(db)
    with db.begin_nested():
        if payload.service_call_id is None:
            call = ServiceCall(
                client_id=payload.client_id, summary=payload.summary,
                opened_on=payload.occurred_on, conversation_id=conversation_id,
            )
            db.add(call)
            db.flush()
            db.add_all(ServiceWorkflowStep(service_call_id=call.id, step_type=kind) for kind in STEP_TYPES)
            db.flush()
        else:
            call = db.get(ServiceCall, payload.service_call_id)
            if call is None:
                raise ValueError("Chamado nao encontrado.")
            if call.client_id != payload.client_id:
                raise ValueError("Chamado pertence a outro cliente.")
        event = ServiceEvent(
            service_call_id=call.id, assistant_action_id=assistant_action_id,
            conversation_id=conversation_id, event_type=payload.event_type,
            occurred_on=payload.occurred_on, description=payload.description,
        )
        db.add(event)
        db.flush()
        transitions = []
        for change in payload.step_changes:
            step = db.scalar(select(ServiceWorkflowStep).where(
                ServiceWorkflowStep.service_call_id == call.id,
                ServiceWorkflowStep.step_type == change.step_type,
            ).with_for_update())
            if step is None:
                raise ValueError("Etapa nao encontrada.")
            if step.status == change.status:
                raise ValueError("Mudanca de etapa sem alteracao de estado.")
            transition = ServiceWorkflowTransition(
                service_call_id=call.id, step_type=change.step_type,
                previous_status=step.status, new_status=change.status,
                observation=change.note, service_event_id=event.id,
                assistant_action_id=assistant_action_id,
            )
            db.add(transition)
            transitions.append(transition)
        db.flush()
        rebuild_current_projection(db, call)
    if commit:
        db.commit()
    return ServiceMutationResult(call, event, transitions)


def correct_event(
    db: Session, payload: ServiceEventCorrectionCreate, *, conversation_id: int,
    assistant_action_id: int, commit: bool = True,
) -> ServiceMutationResult:
    existing = db.scalar(select(ServiceEvent).where(ServiceEvent.assistant_action_id == assistant_action_id))
    if existing is not None:
        return _mutation_result(db, existing)
    _validate_action(db, assistant_action_id, conversation_id)
    _ensure_database_transaction(db)
    with db.begin_nested():
        call = db.get(ServiceCall, payload.service_call_id)
        if call is None:
            raise ValueError("Chamado nao encontrado.")
        parent = db.get(ServiceEvent, payload.supersedes_event_id)
        if parent is None or parent.service_call_id != call.id:
            raise ValueError("Evento de outro chamado ou inexistente.")
        events = list(db.scalars(select(ServiceEvent).where(ServiceEvent.service_call_id == call.id)))
        effective = effective_service_events(events)
        if parent.id not in {item.leaf_event_id for item in effective}:
            raise ValueError("Evento ja corrigido; indique a folha atual.")
        event = ServiceEvent(
            service_call_id=call.id, assistant_action_id=assistant_action_id,
            conversation_id=conversation_id, event_type="correction", occurred_on=payload.occurred_on,
            description=payload.reason, supersedes_event_id=parent.id,
            correction_reason=payload.reason, corrected_event_type=payload.corrected_event_type,
            corrected_occurred_on=payload.corrected_occurred_on,
            corrected_description=payload.corrected_description,
        )
        db.add(event)
        db.flush()
        rebuild_current_projection(db, call)
    if commit:
        db.commit()
    return ServiceMutationResult(call, event, ())


def create_reminders(
    db: Session, *, service_call_id: int, assistant_action_id: int,
    reminders: Sequence[ServiceReminderCreate], commit: bool = True,
) -> list[Task]:
    existing_links = list(db.scalars(select(ServiceTaskLink).where(
        ServiceTaskLink.assistant_action_id == assistant_action_id).order_by(ServiceTaskLink.id)))
    if existing_links:
        if any(link.service_call_id != service_call_id for link in existing_links):
            raise ValueError("Acao ja vinculada a outro chamado.")
        return [task for link in existing_links if (task := link.task) is not None]
    _validate_action(db, assistant_action_id)
    if not reminders or len(reminders) > 5:
        raise ValueError("Informe de um a cinco lembretes.")
    _ensure_database_transaction(db)
    with db.begin_nested():
        call = db.get(ServiceCall, service_call_id)
        if call is None:
            raise ValueError("Chamado nao encontrado.")
        tasks = []
        for reminder in reminders:
            if reminder.step_type is not None and db.scalar(select(ServiceWorkflowStep.id).where(
                ServiceWorkflowStep.service_call_id == call.id,
                ServiceWorkflowStep.step_type == reminder.step_type,
            )) is None:
                raise ValueError("Etapa nao encontrada.")
            task = board_service.create_task(db, TaskCreate(
                titulo=reminder.title, descricao=reminder.description,
                status=reminder.status, client_id=call.client_id,
                user_id=reminder.user_id, prazo=reminder.due_date,
            ), commit=False)
            db.add(ServiceTaskLink(
                service_call_id=call.id, step_type=reminder.step_type,
                task_id=task.id, assistant_action_id=assistant_action_id,
            ))
            tasks.append(task)
        db.flush()
    if commit:
        db.commit()
    return tasks
