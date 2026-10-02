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
    return render_template(request, "services.html", {"calls": calls, "full_width": True})


@router.get("/web/services/{service_call_id}", name="web_service_detail")
def service_detail_page(service_call_id: int, request: Request, db: Session = Depends(get_db)) -> object:
    call = service_record_service.get_service_call(db, service_call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Chamado nao encontrado")
    events = sorted(call.events, key=lambda event: (event.occurred_on, event.id))
    effective = service_record_service.effective_service_events(call.events)
    transitions = sorted(call.workflow_transitions, key=lambda item: (item.created_at, item.id))
    return render_template(request, "service_detail.html", {
        "call": call,
        "events": events,
        "effective_by_source": {event.source_event_id: event for event in effective},
        "superseded_ids": {event.supersedes_event_id for event in call.events if event.supersedes_event_id},
        "steps": {step.step_type: step for step in call.workflow_steps},
        "transitions": transitions,
        "full_width": True,
    })
