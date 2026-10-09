from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    DailySchedulePreference,
    DailyScheduleSnapshot,
    FixedCommitment,
    Task,
    WorkAvailabilityWindow,
)
from app.services.today_service import TaskDayPlan, get_task_day_plan


@dataclass(frozen=True)
class ScheduledBlock:
    task_id: int
    title: str
    start: datetime
    end: datetime
    duration_minutes: int
    duration_source: str
    is_estimate: bool
    priority_label: str
    status_label: str
    due_date: date | None
    client_name: str | None
    reason: str


@dataclass(frozen=True)
class UnscheduledTask:
    task_id: int
    title: str
    reason: str


@dataclass(frozen=True)
class FixedScheduleBlock:
    title: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class DailySchedule:
    today: date
    timezone: str
    availability_configured: bool
    default_duration_minutes: int
    blocks: tuple[ScheduledBlock, ...]
    fixed_blocks: tuple[FixedScheduleBlock, ...]
    unscheduled: tuple[UnscheduledTask, ...]
    prior_snapshot: DailyScheduleSnapshot | None = None
    history: tuple[DailyScheduleSnapshot, ...] = ()

    def snapshot(self) -> dict[str, Any]:
        return {
            "date": self.today.isoformat(),
            "timezone": self.timezone,
            "default_duration_minutes": self.default_duration_minutes,
            "blocks": [
                {
                    "task_id": block.task_id,
                    "title": block.title,
                    "start": block.start.isoformat(),
                    "end": block.end.isoformat(),
                    "duration_minutes": block.duration_minutes,
                    "duration_source": block.duration_source,
                    "is_estimate": block.is_estimate,
                    "priority_label": block.priority_label,
                    "status_label": block.status_label,
                    "due_date": block.due_date.isoformat() if block.due_date else None,
                    "client_name": block.client_name,
                    "reason": block.reason,
                }
                for block in self.blocks
            ],
            "fixed_blocks": [
                {
                    "title": block.title,
                    "start": block.start.isoformat(),
                    "end": block.end.isoformat(),
                }
                for block in self.fixed_blocks
            ],
            "unscheduled": [
                {"task_id": item.task_id, "title": item.title, "reason": item.reason}
                for item in self.unscheduled
            ],
        }


class ScheduleChangedError(ValueError):
    pass


def _merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _subtract_intervals(
    start: datetime,
    end: datetime,
    blocked: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    free = [(start, end)]
    for block_start, block_end in blocked:
        remaining: list[tuple[datetime, datetime]] = []
        for free_start, free_end in free:
            if block_end <= free_start or block_start >= free_end:
                remaining.append((free_start, free_end))
                continue
            if free_start < block_start:
                remaining.append((free_start, block_start))
            if block_end < free_end:
                remaining.append((block_end, free_end))
        free = remaining
    return free


def build_daily_schedule(
    db: Session,
    *,
    today: date | None = None,
    now: datetime | None = None,
    timezone: str = "America/Recife",
    task_plan: TaskDayPlan | None = None,
) -> DailySchedule:
    zone = ZoneInfo(timezone)
    reference = today or datetime.now(zone).date()
    local_now = now or datetime.now(zone)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=zone)
    else:
        local_now = local_now.astimezone(zone)
    if local_now.date() != reference:
        local_now = datetime.combine(reference, time.min, tzinfo=zone)

    windows = (
        db.query(WorkAvailabilityWindow)
        .filter(WorkAvailabilityWindow.weekday == reference.weekday())
        .order_by(WorkAvailabilityWindow.start_time, WorkAvailabilityWindow.id)
        .all()
    )
    commitments = (
        db.query(FixedCommitment)
        .filter(
            ((FixedCommitment.occurrence_type == "weekly") & (FixedCommitment.weekday == reference.weekday()))
            | ((FixedCommitment.occurrence_type == "dated") & (FixedCommitment.commitment_date == reference))
        )
        .order_by(FixedCommitment.start_time, FixedCommitment.id)
        .all()
    )
    preference = db.get(DailySchedulePreference, 1)
    default_duration = preference.default_task_duration_minutes if preference else 60
    history = _schedule_history(db, reference)
    prior_snapshot = history[0] if history else None
    blocks: list[ScheduledBlock] = []
    unscheduled: list[UnscheduledTask] = []

    if not windows:
        plan = task_plan or get_task_day_plan(db, today=reference)
        return DailySchedule(
            today=reference,
            timezone=timezone,
            availability_configured=False,
            default_duration_minutes=default_duration,
            blocks=(),
            fixed_blocks=(),
            unscheduled=tuple(
                UnscheduledTask(item.task_id, item.title, "Disponibilidade de trabalho não configurada; nenhum horário foi presumido como livre.")
                for item in plan.items
            ),
            prior_snapshot=prior_snapshot,
            history=history,
        )

    busy = [
        (
            datetime.combine(reference, item.start_time, tzinfo=zone),
            datetime.combine(reference, item.end_time, tzinfo=zone),
        )
        for item in commitments
    ]
    fixed_blocks = tuple(
        FixedScheduleBlock(
            title=item.title,
            start=start,
            end=end,
        )
        for item, (start, end) in zip(commitments, busy, strict=True)
    )
    free_intervals: list[tuple[datetime, datetime]] = []
    for window in windows:
        window_start = datetime.combine(reference, window.start_time, tzinfo=zone)
        window_end = datetime.combine(reference, window.end_time, tzinfo=zone)
        window_start = max(window_start, local_now)
        if window_start < window_end:
            free_intervals.extend(_subtract_intervals(window_start, window_end, busy))
    free_intervals = _merge_intervals(free_intervals)

    plan = task_plan or get_task_day_plan(db, today=reference)
    task_ids = [item.task_id for item in plan.items]
    task_map = (
        {task.id: task for task in db.query(Task).filter(Task.id.in_(task_ids)).all()}
        if task_ids else {}
    )
    for item in plan.items:
        task = task_map.get(item.task_id)
        task_duration = task.estimated_duration_minutes if task else None
        duration = task_duration or default_duration
        placed = False
        for index, (slot_start, slot_end) in enumerate(free_intervals):
            needed = timedelta(minutes=duration)
            if slot_start + needed > slot_end:
                continue
            finish = slot_start + needed
            due_note = (
                f"Prazo vencido em {item.due_date:%d/%m/%Y}; alocada primeiro por atraso."
                if item.due_date and item.due_date < reference
                else f"Prazo cadastrado para {item.due_date:%d/%m/%Y}."
                if item.due_date
                else "Sem prazo cadastrado."
            )
            is_default = task_duration is None
            blocks.append(
                ScheduledBlock(
                    task_id=item.task_id,
                    title=item.title,
                    start=slot_start,
                    end=finish,
                    duration_minutes=duration,
                    duration_source="default_estimate" if is_default else "task_estimate",
                    is_estimate=True,
                    priority_label=item.priority_label,
                    status_label=item.status_label,
                    due_date=item.due_date,
                    client_name=item.client_name,
                    reason=f"{item.reason} {due_note}",
                )
            )
            if finish < slot_end:
                free_intervals[index] = (finish, slot_end)
            else:
                free_intervals.pop(index)
            placed = True
            break
        if not placed:
            if not free_intervals:
                reason = "Não há horário de trabalho livre restante hoje após compromissos e blocos anteriores."
            else:
                reason = f"A duração estimada é {duration} minutos, mas não há intervalo contínuo livre suficiente."
            unscheduled.append(UnscheduledTask(item.task_id, item.title, reason))

    return DailySchedule(
        today=reference,
        timezone=timezone,
        availability_configured=True,
        default_duration_minutes=default_duration,
        blocks=tuple(blocks),
        fixed_blocks=fixed_blocks,
        unscheduled=tuple(unscheduled),
        prior_snapshot=prior_snapshot,
        history=history,
    )


def _latest_snapshot(db: Session, schedule_date: date) -> DailyScheduleSnapshot | None:
    return next(iter(_schedule_history(db, schedule_date)), None)


def _schedule_history(db: Session, schedule_date: date) -> tuple[DailyScheduleSnapshot, ...]:
    return tuple(
        db.query(DailyScheduleSnapshot)
        .filter(DailyScheduleSnapshot.schedule_date == schedule_date)
        .order_by(DailyScheduleSnapshot.version.desc(), DailyScheduleSnapshot.id.desc())
        .all()
    )


def save_daily_schedule_snapshot(
    db: Session,
    *,
    schedule_date: date,
    snapshot: dict[str, Any],
    assistant_action_id: int,
    idempotency_key: str,
    expected_previous_snapshot_id: int | None,
) -> DailyScheduleSnapshot:
    existing = (
        db.query(DailyScheduleSnapshot)
        .filter(DailyScheduleSnapshot.assistant_action_id == assistant_action_id)
        .one_or_none()
    )
    if existing:
        return existing
    latest = _latest_snapshot(db, schedule_date)
    actual_previous_id = latest.id if latest else None
    if actual_previous_id != expected_previous_snapshot_id:
        raise ScheduleChangedError("A agenda salva mudou desde a prévia. Gere uma nova proposta antes de substituir.")
    version = int(
        db.query(func.max(DailyScheduleSnapshot.version))
        .filter(DailyScheduleSnapshot.schedule_date == schedule_date)
        .scalar()
        or 0
    ) + 1
    record = DailyScheduleSnapshot(
        schedule_date=schedule_date,
        version=version,
        assistant_action_id=assistant_action_id,
        idempotency_key=idempotency_key,
        snapshot_json=snapshot,
    )
    db.add(record)
    db.flush()
    return record
