from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Client, Proposal, User
from app.routers.pages import render_template
from app.schemas import TaskCreate, TaskMove, TaskRead, TaskUpdate
from app.services import board_service

router = APIRouter(tags=["board"])


@router.get("/web/board", name="web_board")
def board_page(request: Request, db: Session = Depends(get_db)) -> object:
    tasks = board_service.get_tasks(db)

    # Group by status
    board_data = {
        "a_fazer": [],
        "em_andamento": [],
        "aguardando_cliente": [],
        "concluido": [],
    }

    for task in tasks:
        if task.status in board_data:
            board_data[task.status].append(task)
        else:
            board_data["a_fazer"].append(task)

    return render_template(request, "board.html", {"board_data": board_data})


@router.get("/web/board/new", name="web_board_new")
def board_new_page(request: Request, db: Session = Depends(get_db)) -> object:
    clients = db.query(Client).order_by(Client.razao_social.asc()).all()
    users = db.query(User).filter(User.ativo.is_(True)).order_by(User.nome.asc()).all()
    proposals = db.query(Proposal).order_by(Proposal.numero.desc()).all()

    return render_template(
        request,
        "board_form.html",
        {
            "task": None,
            "clients": clients,
            "users": users,
            "proposals": proposals,
            "action_url": "/web/board/new",
        },
    )


@router.post("/web/board/new")
async def board_new_submit(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    form = await request.form()

    try:
        client_id_val = form.get("client_id")
        proposal_id_val = form.get("proposal_id")
        user_id_val = form.get("user_id")
        prazo_val = form.get("prazo")

        payload = TaskCreate(
            titulo=str(form.get("titulo", "")).strip(),
            descricao=str(form.get("descricao", "")).strip(),
            status=str(form.get("status", "a_fazer")).strip(),
            client_id=int(client_id_val) if client_id_val else None,
            proposal_id=int(proposal_id_val) if proposal_id_val else None,
            user_id=int(user_id_val) if user_id_val else None,
            prazo=datetime.strptime(str(prazo_val), "%Y-%m-%d").date() if prazo_val else None,
        )
        if not payload.titulo:
            raise ValueError("Título é obrigatório")

        board_service.create_task(db, payload)
        return RedirectResponse(url=request.url_for("web_board"), status_code=status.HTTP_303_SEE_OTHER)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/web/board/{task_id}/edit", name="web_board_edit")
def board_edit_page(task_id: int, request: Request, db: Session = Depends(get_db)) -> object:
    task = board_service.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    clients = db.query(Client).order_by(Client.razao_social.asc()).all()
    users = db.query(User).filter(User.ativo.is_(True)).order_by(User.nome.asc()).all()
    proposals = db.query(Proposal).order_by(Proposal.numero.desc()).all()

    return render_template(
        request,
        "board_form.html",
        {
            "task": task,
            "clients": clients,
            "users": users,
            "proposals": proposals,
            "action_url": f"/web/board/{task_id}/edit",
        },
    )


@router.post("/web/board/{task_id}/edit")
async def board_edit_submit(task_id: int, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    form = await request.form()

    try:
        client_id_val = form.get("client_id")
        proposal_id_val = form.get("proposal_id")
        user_id_val = form.get("user_id")
        prazo_val = form.get("prazo")

        payload = TaskUpdate(
            titulo=str(form.get("titulo", "")).strip(),
            descricao=str(form.get("descricao", "")).strip(),
            status=str(form.get("status", "a_fazer")).strip(),
            client_id=int(client_id_val) if client_id_val else None,
            proposal_id=int(proposal_id_val) if proposal_id_val else None,
            user_id=int(user_id_val) if user_id_val else None,
            prazo=datetime.strptime(str(prazo_val), "%Y-%m-%d").date() if prazo_val else None,
        )

        board_service.update_task(db, task_id, payload)
        return RedirectResponse(url=request.url_for("web_board"), status_code=status.HTTP_303_SEE_OTHER)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/tasks/{task_id}/move", response_model=TaskRead)
def api_move_task(task_id: int, payload: TaskMove, db: Session = Depends(get_db)) -> object:
    try:
        task = board_service.move_task(db, task_id, payload)
        return task
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
