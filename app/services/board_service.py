from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models import Task
from app.schemas import TaskCreate, TaskMove, TaskUpdate


def get_tasks(db: Session) -> list[Task]:
    return (
        db.query(Task)
        .options(
            joinedload(Task.client),
            joinedload(Task.proposal),
            joinedload(Task.user),
        )
        .order_by(Task.status, Task.ordem.asc(), Task.id.desc())
        .all()
    )


def get_task(db: Session, task_id: int) -> Task | None:
    return (
        db.query(Task)
        .options(
            joinedload(Task.client),
            joinedload(Task.proposal),
            joinedload(Task.user),
        )
        .filter(Task.id == task_id)
        .first()
    )


def create_task(db: Session, payload: TaskCreate) -> Task:
    # Find the current max ordem for the given status
    max_ordem = db.query(Task).filter(Task.status == payload.status).count()

    task = Task(
        titulo=payload.titulo,
        descricao=payload.descricao,
        status=payload.status,
        client_id=payload.client_id,
        proposal_id=payload.proposal_id,
        user_id=payload.user_id,
        prazo=payload.prazo,
        ordem=max_ordem,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_task(db: Session, task_id: int, payload: TaskUpdate) -> Task:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, key, value)

    db.commit()
    db.refresh(task)
    return task


def move_task(db: Session, task_id: int, payload: TaskMove) -> Task:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    old_status = task.status
    old_ordem = task.ordem
    new_status = payload.status
    new_ordem = payload.ordem

    if old_status == new_status and old_ordem == new_ordem:
        return task

    if old_status == new_status:
        # Reorder within same column
        if new_ordem > old_ordem:
            db.query(Task).filter(
                Task.status == old_status,
                Task.ordem > old_ordem,
                Task.ordem <= new_ordem,
            ).update({"ordem": Task.ordem - 1})
        else:
            db.query(Task).filter(
                Task.status == old_status,
                Task.ordem >= new_ordem,
                Task.ordem < old_ordem,
            ).update({"ordem": Task.ordem + 1})
    else:
        # Move between columns
        # Shift old column tasks up
        db.query(Task).filter(
            Task.status == old_status,
            Task.ordem > old_ordem,
        ).update({"ordem": Task.ordem - 1})

        # Shift new column tasks down
        db.query(Task).filter(
            Task.status == new_status,
            Task.ordem >= new_ordem,
        ).update({"ordem": Task.ordem + 1})

    task.status = new_status
    task.ordem = new_ordem
    db.commit()
    db.refresh(task)
    return task
