from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.routers.pages import render_template
from app.schemas import ServiceCallQuery, ServiceTechnicalReportFields
from app.services import service_record_service, service_report_service

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
        "reports": service_report_service.list_reports(db, call.id),
        "full_width": True,
    })


@router.get("/web/services/{service_call_id}/relatorio/previa", name="web_service_report_preview")
def service_report_preview_page(
    service_call_id: int, request: Request, db: Session = Depends(get_db),
) -> object:
    try:
        preview = service_report_service.build_preview(db, service_call_id)
    except service_report_service.ServiceReportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service_report_service.ServiceReportNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    import secrets

    return render_template(request, "service_report_preview.html", {
        "preview": preview,
        "fields": preview.fields,
        "missing_fields": set(preview.missing_fields),
        "field_labels": service_report_service.FIELD_LABELS,
        "idempotency_key": secrets.token_urlsafe(24),
        "error": None,
        "full_width": True,
    })


@router.post("/web/services/{service_call_id}/relatorio/gerar", name="web_service_report_generate")
def generate_service_report(
    service_call_id: int,
    request: Request,
    db: Session = Depends(get_db),
    client_name: str = Form(default="", max_length=255),
    client_cnpj: str = Form(default="", max_length=32),
    client_phone: str = Form(default="", max_length=50),
    client_address: str = Form(default="", max_length=1000),
    equipment: str = Form(default="", max_length=1000),
    completion_date: str = Form(default="", max_length=10),
    reported_problem: str = Form(default="", max_length=4000),
    analysis: str = Form(default="", max_length=4000),
    work_performed: str = Form(default="", max_length=4000),
    verification_result: str = Form(default="", max_length=4000),
    idempotency_key: str = Form(min_length=1, max_length=100),
    source_fingerprint: str = Form(min_length=64, max_length=64),
    confirmed: str | None = Form(default=None),
) -> object:
    try:
        fields = ServiceTechnicalReportFields(
            client_name=client_name,
            client_cnpj=client_cnpj,
            client_phone=client_phone,
            client_address=client_address,
            equipment=equipment,
            completion_date=completion_date,
            reported_problem=reported_problem,
            analysis=analysis,
            work_performed=work_performed,
            verification_result=verification_result,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Revise os campos do relatório e tente novamente.") from exc

    if confirmed != "yes":
        try:
            preview = service_report_service.build_preview(db, service_call_id)
        except service_report_service.ServiceReportNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except service_report_service.ServiceReportNotReady as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return render_template(request, "service_report_preview.html", {
            "preview": preview,
            "fields": fields,
            "missing_fields": set(preview.missing_fields) | {
                name for name in service_report_service.FIELD_LABELS
                if not getattr(fields, name).strip()
            },
            "field_labels": service_report_service.FIELD_LABELS,
            "idempotency_key": idempotency_key,
            "error": "Marque a confirmação explícita para gerar os arquivos.",
            "full_width": True,
        })

    settings = get_settings()
    generation_settings = service_report_service.ReportGenerationSettings(
        output_dir=settings.output_dir,
        template_path=settings.technical_report_template_path,
        libreoffice_cmd=settings.libreoffice_cmd,
        timezone=settings.assistant_timezone,
        libreoffice_docker_image=getattr(settings, "technical_report_pdf_converter_image", ""),
    )
    try:
        result = service_report_service.generate_report(
            db,
            service_call_id,
            fields,
            idempotency_key=idempotency_key,
            settings=generation_settings,
            confirmed=True,
            expected_fingerprint=source_fingerprint,
        )
    except service_report_service.ServiceReportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (service_report_service.ServiceReportNotReady,
            service_report_service.ReportPreviewOutdated) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (service_report_service.ReportConfirmationRequired,
            service_report_service.ReportGenerationError) as exc:
        try:
            preview = service_report_service.build_preview(db, service_call_id)
        except service_report_service.ServiceReportError:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return render_template(request, "service_report_preview.html", {
            "preview": preview,
            "fields": fields,
            "missing_fields": set(preview.missing_fields) | {
                name for name in service_report_service.FIELD_LABELS
                if not getattr(fields, name).strip()
            },
            "field_labels": service_report_service.FIELD_LABELS,
            "idempotency_key": idempotency_key,
            "error": str(exc),
            "full_width": True,
        }, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return RedirectResponse(
        url=f"/web/services/{service_call_id}?report={result.report.id}", status_code=303
    )


@router.get("/web/services/relatorios/{report_id}/{file_kind}", name="web_service_report_file")
def service_report_file(
    report_id: int, file_kind: str, db: Session = Depends(get_db),
) -> FileResponse:
    report = db.get(service_report_service.ServiceTechnicalReport, report_id)
    if report is None or file_kind not in {"docx", "pdf"}:
        raise HTTPException(status_code=404, detail="Relatório não encontrado.")
    relative_path = report.docx_path if file_kind == "docx" else report.pdf_path
    suffix = ".docx" if file_kind == "docx" else ".pdf"
    try:
        path = service_report_service.resolve_report_file(relative_path, get_settings().output_dir, suffix)
    except service_report_service.ReportGenerationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if file_kind == "docx" else "application/pdf"
    )
    return FileResponse(path, media_type=media_type, filename=path.name)
