from __future__ import annotations

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import and_, case
from sqlalchemy.orm import Session, joinedload

from app.models import Client, Proposal, Task, User
from app.schemas import TaskCreate, TaskMove, TaskStatus, TaskUpdate


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


def _validate_references(
    db: Session,
    payload: TaskCreate | TaskUpdate,
    *,
    current_task: Task | None = None,
) -> tuple[int | None, int | None, int | None]:
    values = payload.model_dump(exclude_unset=True)
    client_id = values.get("client_id", current_task.client_id if current_task else None)
    proposal_id = values.get("proposal_id", current_task.proposal_id if current_task else None)
    user_id = values.get("user_id", current_task.user_id if current_task else None)

    if client_id is not None and db.get(Client, int(client_id)) is None:
        raise ValueError("Cliente nao encontrado.")
    proposal = db.get(Proposal, int(proposal_id)) if proposal_id is not None else None
    if proposal_id is not None and proposal is None:
        raise ValueError("Proposta nao encontrada.")
    if user_id is not None and db.get(User, int(user_id)) is None:
        raise ValueError("Responsavel nao encontrado.")
    if proposal is not None and client_id is None:
        client_id = proposal.client_id
    if proposal is not None and client_id is not None and proposal.client_id != int(client_id):
        raise ValueError("A proposta informada pertence a outro cliente.")
    return (
        int(client_id) if client_id is not None else None,
        int(proposal_id) if proposal_id is not None else None,
        int(user_id) if user_id is not None else None,
    )


def create_task(db: Session, payload: TaskCreate, *, commit: bool = True) -> Task:
    client_id, proposal_id, user_id = _validate_references(db, payload)
    # Find the current max ordem for the given status
    max_ordem = db.query(Task).filter(Task.status == payload.status).count()

    task = Task(
        titulo=payload.titulo,
        descricao=payload.descricao,
        status=payload.status,
        client_id=client_id,
        client_name=(payload.client_name.strip() or None) if payload.client_name else None,
        client_link_status=(
            "linked" if client_id is not None and payload.client_link_status == "unlinked"
            else "pending_review" if client_id is None and payload.client_name and payload.client_link_status == "unlinked"
            else payload.client_link_status
        ),
        proposal_id=proposal_id,
        user_id=user_id,
        prazo=payload.prazo,
        estimated_duration_minutes=payload.estimated_duration_minutes,
        ordem=max_ordem,
    )
    db.add(task)
    if commit:
        db.commit()
        db.refresh(task)
    else:
        db.flush()
    return task


def update_task(db: Session, task_id: int, payload: TaskUpdate) -> Task:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    client_id, proposal_id, user_id = _validate_references(
        db,
        payload,
        current_task=task,
    )
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, key, value)
    task.client_id = client_id
    task.proposal_id = proposal_id
    task.user_id = user_id
    if "client_name" in payload.model_fields_set:
        task.client_name = (payload.client_name.strip() or None) if payload.client_name else None
    if "client_link_status" in payload.model_fields_set and payload.client_link_status:
        task.client_link_status = payload.client_link_status
    elif "client_id" in payload.model_fields_set or "client_name" in payload.model_fields_set:
        task.client_link_status = "linked" if client_id is not None else (
            "pending_review" if task.client_name else "unlinked"
        )

    db.commit()
    db.refresh(task)
    return task


def query_tasks(
    db: Session,
    *,
    today: date,
    status_value: TaskStatus | None = None,
    client_id: int | None = None,
    user_id: int | None = None,
    overdue_only: bool = False,
    due_before: date | None = None,
    priorities: bool = False,
    include_completed: bool = False,
    limit: int = 20,
) -> list[Task]:
    query = db.query(Task).options(
        joinedload(Task.client),
        joinedload(Task.proposal),
        joinedload(Task.user),
    )
    if status_value is not None:
        query = query.filter(Task.status == status_value)
    elif not include_completed:
        query = query.filter(Task.status != "concluido")
    if client_id is not None:
        query = query.filter(Task.client_id == client_id)
    if user_id is not None:
        query = query.filter(Task.user_id == user_id)
    if overdue_only:
        query = query.filter(Task.prazo.is_not(None), Task.prazo < today)
    if due_before is not None:
        query = query.filter(Task.prazo.is_not(None), Task.prazo <= due_before)

    order_columns: list[object] = []
    if priorities:
        order_columns.append(
            case(
                (Task.status == "servico_feito_falta_nota_pedido", 0),
                (
                    and_(
                        Task.status != "concluido",
                        Task.prazo.is_not(None),
                        Task.prazo < today,
                    ),
                    1,
                ),
                (Task.status == "em_andamento", 2),
                (Task.status == "a_fazer", 3),
                (Task.status == "aguardando_cliente", 4),
                else_=5,
            )
        )
    order_columns.extend(
        [
            case((Task.prazo.is_(None), 1), else_=0),
            Task.prazo.asc(),
            Task.ordem.asc(),
            Task.id.asc(),
        ]
    )
    return query.order_by(*order_columns).limit(max(1, min(limit, 50))).all()


def delete_task(db: Session, task_id: int) -> None:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    task_status = task.status
    task_order = task.ordem
    db.delete(task)
    db.query(Task).filter(
        Task.status == task_status,
        Task.ordem > task_order,
    ).update({"ordem": Task.ordem - 1}, synchronize_session=False)
    db.commit()


def move_task(db: Session, task_id: int, payload: TaskMove, *, commit: bool = True) -> Task:
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
    if commit:
        db.commit()
        db.refresh(task)
    return task
