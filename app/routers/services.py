from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.pages import render_template
from app.schemas import ServiceCallQuery
from app.services import service_record_service

router = APIRouter(tags=["services"])


@router.get("/web/services", name="web_services")
def services_page(request: Request, db: Session = Depends(get_db)) -> object:
    calls = service_record_service.list_service_calls(db, ServiceCallQuery(limit=50))
    service_rows = []
    pending_statuses = {"unknown", "pending", "waiting_customer"}
    for call in calls:
        pending_step = next(
            (step for step in call.workflow_steps if step.status in pending_statuses),
            None,
        )
        service_rows.append({
            "call": call,
            "next_step": pending_step,
            "last_event": max(call.events, key=lambda item: (item.occurred_on, item.id), default=None),
        })
    return render_template(
        request,
        "services.html",
        {"calls": calls, "service_rows": service_rows, "full_width": True},
    )


@router.get("/web/services/{service_call_id}", name="web_service_detail")
def service_detail_page(service_call_id: int, request: Request, db: Session = Depends(get_db)) -> object:
    call = service_record_service.get_service_call(db, service_call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Chamado nao encontrado")
    events = sorted(call.events, key=lambda event: (event.occurred_on, event.id))
    effective = service_record_service.effective_service_events(call.events)
    transitions = sorted(call.workflow_transitions, key=lambda item: (item.created_at, item.id))
    next_step = next(
        (
            step for step in call.workflow_steps
            if step.status in {"unknown", "pending", "waiting_customer"}
        ),
        None,
    )
    return render_template(request, "service_detail.html", {
        "call": call,
        "events": events,
        "effective_by_source": {event.source_event_id: event for event in effective},
        "superseded_ids": {event.supersedes_event_id for event in call.events if event.supersedes_event_id},
        "steps": {step.step_type: step for step in call.workflow_steps},
        "transitions": transitions,
        "next_step": next_step,
        "full_width": True,
    })
