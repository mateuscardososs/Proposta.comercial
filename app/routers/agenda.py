from __future__ import annotations

from datetime import date, time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import DailySchedulePreference, FixedCommitment, WorkAvailabilityWindow
from app.routers.pages import render_template

router = APIRouter(tags=["agenda"])
WEEKDAYS = (
    (0, "Segunda-feira"), (1, "Terça-feira"), (2, "Quarta-feira"),
    (3, "Quinta-feira"), (4, "Sexta-feira"), (5, "Sábado"), (6, "Domingo"),
)


@router.get("/web/agenda/config", name="web_agenda_config")
def agenda_config_page(request: Request, db: Session = Depends(get_db)) -> object:  # noqa: B008
    preference = db.get(DailySchedulePreference, 1)
    return render_template(
        request,
        "agenda_config.html",
        {
            "preference": preference,
            "default_duration_minutes": preference.default_task_duration_minutes if preference else 60,
            "windows": db.query(WorkAvailabilityWindow).order_by(WorkAvailabilityWindow.weekday, WorkAvailabilityWindow.start_time, WorkAvailabilityWindow.id).all(),
            "commitments": db.query(FixedCommitment).order_by(FixedCommitment.commitment_date, FixedCommitment.weekday, FixedCommitment.start_time, FixedCommitment.id).all(),
            "weekdays": WEEKDAYS,
            "saved": request.query_params.get("saved") == "1",
            "full_width": True,
            "title": "Configurar agenda",
        },
    )


@router.post("/web/agenda/config", name="web_agenda_config_save")
async def agenda_config_save(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:  # noqa: B008
    form = await request.form()
    action = str(form.get("action") or "")
    try:
        if action == "default_duration":
            duration = int(str(form.get("default_task_duration_minutes") or ""))
            if not 1 <= duration <= 1440:
                raise ValueError("A estimativa padrão deve ficar entre 1 e 1440 minutos.")
            preference = db.get(DailySchedulePreference, 1)
            if preference is None:
                preference = DailySchedulePreference(id=1, default_task_duration_minutes=duration)
                db.add(preference)
            else:
                preference.default_task_duration_minutes = duration
        elif action == "add_window":
            weekday = int(str(form.get("weekday") or ""))
            start = time.fromisoformat(str(form.get("start_time") or ""))
            end = time.fromisoformat(str(form.get("end_time") or ""))
            if weekday not in range(7) or start >= end:
                raise ValueError("Informe um dia e um intervalo de trabalho válido.")
            db.add(WorkAvailabilityWindow(
                weekday=weekday,
                start_time=start,
                end_time=end,
                label=str(form.get("label") or "Expediente").strip()[:120] or "Expediente",
            ))
        elif action == "delete_window":
            window = db.get(WorkAvailabilityWindow, int(str(form.get("id") or "")))
            if window:
                db.delete(window)
        elif action == "add_commitment":
            title = str(form.get("title") or "").strip()
            occurrence = str(form.get("occurrence_type") or "")
            start = time.fromisoformat(str(form.get("start_time") or ""))
            end = time.fromisoformat(str(form.get("end_time") or ""))
            if not title or start >= end or occurrence not in {"weekly", "dated"}:
                raise ValueError("Informe título, recorrência e horário válidos para o compromisso.")
            weekday = int(str(form.get("weekday") or "")) if occurrence == "weekly" else None
            commitment_date = date.fromisoformat(str(form.get("commitment_date") or "")) if occurrence == "dated" else None
            if occurrence == "weekly" and weekday not in range(7):
                raise ValueError("Selecione o dia do compromisso recorrente.")
            if occurrence == "dated" and commitment_date is None:
                raise ValueError("Selecione a data do compromisso.")
            db.add(FixedCommitment(
                title=title[:160],
                occurrence_type=occurrence,
                weekday=weekday,
                commitment_date=commitment_date,
                start_time=start,
                end_time=end,
            ))
        elif action == "delete_commitment":
            commitment = db.get(FixedCommitment, int(str(form.get("id") or "")))
            if commitment:
                db.delete(commitment)
        else:
            raise ValueError("Ação de configuração inválida.")
        db.commit()
        return RedirectResponse(url="/web/agenda/config?saved=1", status_code=status.HTTP_303_SEE_OTHER)
    except (TypeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
