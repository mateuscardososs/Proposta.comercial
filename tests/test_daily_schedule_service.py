from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import DBAPIError

from app.models import (
    AssistantAction,
    AssistantConversation,
    DailySchedulePreference,
    DailyScheduleSnapshot,
    FixedCommitment,
    Task,
    WorkAvailabilityWindow,
)
from app.services.daily_schedule_service import (
    ScheduleChangedError,
    build_daily_schedule,
    save_daily_schedule_snapshot,
)


def test_no_availability_never_assumes_open_time_and_does_not_write_tasks(db):
    task = Task(titulo="Tarefa sem horário cadastrado", prazo=date(2026, 10, 6))
    db.add(task)
    db.commit()
    before_updated_at = task.updated_at

    schedule = build_daily_schedule(
        db,
        today=date(2026, 10, 6),
        now=datetime(2026, 10, 6, 8, 0, tzinfo=ZoneInfo("America/Recife")),
    )

    assert schedule.blocks == ()
    assert schedule.unscheduled[0].task_id == task.id
    assert "disponibilidade" in schedule.unscheduled[0].reason.casefold()
    assert task.updated_at == before_updated_at
    assert db.query(DailySchedulePreference).count() == 0


def test_uses_recurring_windows_fixed_commitments_and_estimated_default(db):
    tasks = [
        Task(titulo="Prazo hoje primeiro", prazo=date(2026, 10, 6), estimated_duration_minutes=60),
        Task(titulo="Urgente depois", descricao="Urgente", estimated_duration_minutes=None),
    ]
    db.add_all(tasks)
    db.add_all(
        [
            WorkAvailabilityWindow(weekday=1, start_time=time(9), end_time=time(12)),
            FixedCommitment(
                title="Intervalo",
                occurrence_type="weekly",
                weekday=1,
                commitment_date=None,
                start_time=time(10),
                end_time=time(10, 30),
            ),
        ]
    )
    db.commit()

    schedule = build_daily_schedule(
        db,
        today=date(2026, 10, 6),  # Tuesday
        now=datetime(2026, 10, 6, 8, 0, tzinfo=ZoneInfo("America/Recife")),
    )

    assert [(block.title, block.start.time(), block.end.time()) for block in schedule.blocks] == [
        ("Prazo hoje primeiro", time(9), time(10)),
        ("Urgente depois", time(10, 30), time(11, 30)),
    ]
    assert schedule.blocks[0].duration_source == "task_estimate"
    assert schedule.blocks[1].duration_minutes == 60
    assert schedule.blocks[1].duration_source == "default_estimate"
    assert schedule.blocks[1].is_estimate is True


def test_task_that_cannot_fit_is_reported_with_reason_and_deadline_is_respected(db):
    task = Task(titulo="Prazo de hoje", prazo=date(2026, 10, 6), estimated_duration_minutes=180)
    db.add(task)
    db.add(WorkAvailabilityWindow(weekday=1, start_time=time(9), end_time=time(10)))
    db.commit()

    schedule = build_daily_schedule(
        db,
        today=date(2026, 10, 6),
        now=datetime(2026, 10, 6, 8, 0, tzinfo=ZoneInfo("America/Recife")),
    )

    assert not schedule.blocks
    assert schedule.unscheduled[0].task_id == task.id
    assert "180 minutos" in schedule.unscheduled[0].reason


def test_fixed_commitment_for_date_overrides_weekly_availability(db):
    db.add(WorkAvailabilityWindow(weekday=1, start_time=time(9), end_time=time(17)))
    db.add(
        FixedCommitment(
            title="Compromisso",
            occurrence_type="dated",
            weekday=None,
            commitment_date=date(2026, 10, 6),
            start_time=time(9),
            end_time=time(17),
        )
    )
    db.add(Task(titulo="Sem espaço", prazo=date(2026, 10, 6)))
    db.commit()

    schedule = build_daily_schedule(
        db,
        today=date(2026, 10, 6),
        now=datetime(2026, 10, 6, 8, 0, tzinfo=ZoneInfo("America/Recife")),
    )

    assert schedule.blocks == ()
    assert "compromisso" in schedule.unscheduled[0].reason.casefold()


def test_confirmed_snapshots_are_idempotent_versioned_and_append_only(db):
    conversation = AssistantConversation()
    db.add(conversation)
    db.flush()
    action1 = AssistantAction(
        conversation_id=conversation.id,
        request_id="save-daily-1",
        confirmation_token_hash="hash-one",
        action_type="save_daily_schedule",
        status="pending",
        arguments_json={},
        result_json={},
    )
    db.add(action1)
    db.flush()
    first = save_daily_schedule_snapshot(
        db,
        schedule_date=date(2026, 10, 6),
        snapshot={"blocks": []},
        assistant_action_id=action1.id,
        idempotency_key="assistant-action:1",
        expected_previous_snapshot_id=None,
    )
    db.commit()
    repeated = save_daily_schedule_snapshot(
        db,
        schedule_date=date(2026, 10, 6),
        snapshot={"blocks": []},
        assistant_action_id=action1.id,
        idempotency_key="assistant-action:1",
        expected_previous_snapshot_id=None,
    )
    assert repeated.id == first.id

    action2 = AssistantAction(
        conversation_id=conversation.id,
        request_id="save-daily-2",
        confirmation_token_hash="hash-two",
        action_type="save_daily_schedule",
        status="pending",
        arguments_json={},
        result_json={},
    )
    db.add(action2)
    db.flush()
    second = save_daily_schedule_snapshot(
        db,
        schedule_date=date(2026, 10, 6),
        snapshot={"blocks": [{"task_id": 3}]},
        assistant_action_id=action2.id,
        idempotency_key="assistant-action:2",
        expected_previous_snapshot_id=first.id,
    )
    db.commit()
    assert (first.version, second.version) == (1, 2)
    assert db.query(DailyScheduleSnapshot).count() == 2
    with pytest.raises(DBAPIError):
        first.snapshot_json = {"blocks": ["mutated"]}
        db.commit()
    db.rollback()
    with pytest.raises(DBAPIError):
        db.delete(first)
        db.commit()
    db.rollback()


def test_snapshot_replacement_requires_current_previous_version(db):
    conversation = AssistantConversation()
    db.add(conversation)
    db.flush()
    action = AssistantAction(
        conversation_id=conversation.id,
        request_id="stale-save",
        confirmation_token_hash="hash",
        action_type="save_daily_schedule",
        status="pending",
        arguments_json={},
        result_json={},
    )
    db.add(action)
    db.flush()
    with pytest.raises(ScheduleChangedError):
        save_daily_schedule_snapshot(
            db,
            schedule_date=date(2026, 10, 6),
            snapshot={"blocks": []},
            assistant_action_id=action.id,
            idempotency_key="stale",
            expected_previous_snapshot_id=999,
        )


def test_schedule_keeps_shared_order_without_limiting_source_tasks_to_fifty(db):
    tasks = [
        Task(titulo=f"Task {number:02}", status="a_fazer", ordem=number)
        for number in range(55)
    ]
    db.add_all(tasks)
    db.add(WorkAvailabilityWindow(weekday=1, start_time=time(9), end_time=time(18)))
    db.commit()

    schedule = build_daily_schedule(
        db,
        today=date(2026, 10, 6),
        now=datetime(2026, 10, 6, 8, tzinfo=ZoneInfo("America/Recife")),
    )

    assert len(schedule.blocks) == 9
    assert len(schedule.unscheduled) == 46
    assert schedule.blocks[0].title == "Task 00"
    assert schedule.unscheduled[-1].title == "Task 54"
