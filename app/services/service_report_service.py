from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AssistantAction,
    AssistantConversation,
    AssistantMessage,
    Client,
    ServiceCall,
    ServiceTechnicalReport,
    ServiceWorkflowStep,
    ServiceWorkflowTransition,
)
from app.schemas import ServiceTechnicalReportFields
from app.services import (
    pdf_service,
    service_record_service,
    technical_report_document_service,
)

FIELD_LABELS = {
    "client_name": "Cliente",
    "client_cnpj": "CNPJ do cliente",
    "client_phone": "Telefone do cliente",
    "client_address": "Endereço do cliente",
    "equipment": "Equipamento",
    "completion_date": "Data da execução",
    "reported_problem": "Problema relatado",
    "analysis": "Análise registrada",
    "work_performed": "Serviço executado",
    "verification_result": "Resultado da verificação",
}
MAX_SERVICE_CALL_ID = 2_147_483_647
EVENT_LABELS = {
    "call_received": "Chamado recebido",
    "visit_started": "Visita iniciada",
    "inspection": "Inspeção",
    "execution_started": "Execução iniciada",
    "execution_completed": "Execução concluída",
    "note": "Observação",
    "correction": "Correção",
}
NARRATIVE_LABELS = {
    "equipamento": "equipment",
    "problema relatado": "reported_problem",
    "analise": "analysis",
    "servico executado": "work_performed",
}


class ServiceReportError(ValueError):
    pass


class ServiceReportNotFound(ServiceReportError):
    pass


class ServiceReportNotReady(ServiceReportError):
    pass


class ReportConfirmationRequired(ServiceReportError):
    pass


class ReportPreviewOutdated(ServiceReportError):
    pass


class ReportGenerationError(ServiceReportError):
    pass


@dataclass(frozen=True)
class ReportGenerationSettings:
    output_dir: Path
    template_path: Path
    libreoffice_cmd: str
    timezone: str
    libreoffice_docker_image: str = ""


@dataclass(frozen=True)
class ServiceReportPreview:
    service_call: ServiceCall
    fields: ServiceTechnicalReportFields
    client_snapshot: dict[str, object]
    completion_date_from_source: str
    source_fingerprint: str
    source_event_ids: list[int]
    event_timeline: list[dict[str, str]]
    missing_fields: list[str]


@dataclass(frozen=True)
class ReportGenerationResult:
    report: ServiceTechnicalReport
    docx_path: Path
    pdf_path: Path
    replayed: bool = False


def assistant_generation_settings() -> ReportGenerationSettings:
    from app.config import get_settings

    settings = get_settings()
    return ReportGenerationSettings(
        output_dir=settings.output_dir,
        template_path=settings.technical_report_template_path,
        libreoffice_cmd=settings.libreoffice_cmd,
        timezone=settings.assistant_timezone,
        libreoffice_docker_image=settings.technical_report_pdf_converter_image,
    )


def completed_service_calls(
    db: Session,
    *,
    service_call_id: int | None = None,
    client: str | None = None,
    reference: str | None = None,
) -> list[ServiceCall]:
    query = (
        select(ServiceCall)
        .options(selectinload(ServiceCall.client))
        .where(ServiceCall.execution_status == "completed")
    )
    if service_call_id is not None:
        if not 1 <= service_call_id <= MAX_SERVICE_CALL_ID:
            return []
        query = query.where(ServiceCall.id == service_call_id)
    else:
        if client:
            query = query.where(
                ServiceCall.client.has(
                    _contains_accent_insensitive(Client.razao_social, client)
                )
            )
        if reference:
            value = reference.strip()
            matching_reference = [
                _contains_accent_insensitive(ServiceCall.summary, value)
            ]
            if value.isdecimal() and len(value) <= 10:
                numeric_reference = int(value)
                if numeric_reference <= MAX_SERVICE_CALL_ID:
                    matching_reference.append(ServiceCall.id == numeric_reference)
            matching_reference.append(
                ServiceCall.client.has(
                    _contains_accent_insensitive(Client.razao_social, value)
                )
            )
            query = query.where(or_(*matching_reference))
    return list(
        db.scalars(
            query.order_by(ServiceCall.opened_on.desc(), ServiceCall.id.desc()).limit(11)
        ).all()
    )


def _normalize_label(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char)).strip()


def _contains_accent_insensitive(column, value: str):
    search_term = _normalize_label(value)
    escaped = search_term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    expression = column
    accent_map = {
        "àáâãäå": "a",
        "èéêë": "e",
        "ìíîï": "i",
        "òóôõöø": "o",
        "ùúûü": "u",
        "ç": "c",
        "ñ": "n",
        "ýÿ": "y",
    }
    for accented, plain in accent_map.items():
        for character in accented:
            expression = func.replace(expression, character, plain)
            expression = func.replace(expression, character.upper(), plain)
    return func.lower(expression).like(f"%{escaped}%", escape="\\")


def _parse_narrative(description: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in description.splitlines():
        label, separator, value = line.partition(":")
        if not separator:
            continue
        field = NARRATIVE_LABELS.get(_normalize_label(label))
        if field and value.strip():
            result[field] = value.strip()
    return result


def _verification_from_event(description: str) -> str:
    match = re.search(
        r"verificacao de retorno\s*[—-].*?:\s*(resolvido|continua pendente)\.",
        _normalize_label(description),
        re.IGNORECASE,
    )
    if not match:
        return ""
    outcome = match.group(1)
    observation = description.split("\n", 1)[1].strip() if "\n" in description else ""
    outcome_text = "Retorno registrado como resolvido." if outcome == "resolvido" else "Retorno registrado como ainda pendente."
    return f"{outcome_text} {observation}".strip()


def _format_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def _serialize_source(call: ServiceCall, effective_events) -> dict[str, object]:
    fields = {name: "" for name in FIELD_LABELS}
    timeline: list[dict[str, str]] = []
    completion_date = call.technically_completed_at.date() if call.technically_completed_at else None
    for item in effective_events:
        timeline.append({
            "date": _format_date(item.occurred_on),
            "type": EVENT_LABELS.get(item.event_type, item.event_type),
            "description": item.description.strip(),
        })
        for field, value in _parse_narrative(item.description).items():
            if value:
                fields[field] = value
        verification = _verification_from_event(item.description)
        if verification:
            fields["verification_result"] = verification
        if item.event_type == "execution_completed":
            completion_date = item.occurred_on
    fields["completion_date"] = completion_date.isoformat() if completion_date else ""
    address = " · ".join(value for value in (
        call.client.endereco_linha1.strip(),
        call.client.endereco_linha2.strip(),
        call.client.cep.strip(),
        call.client.cidade_uf.strip(),
    ) if value)
    client_snapshot = {
        "client_id": call.client_id,
        "name": call.client.razao_social.strip(),
        "cnpj": call.client.cnpj.strip(),
        "phone": call.client.telefone.strip(),
        "address": address,
    }
    fields.update({
        "client_name": client_snapshot["name"],
        "client_cnpj": client_snapshot["cnpj"],
        "client_phone": client_snapshot["phone"],
        "client_address": client_snapshot["address"],
    })
    return {
        "client": call.client.razao_social.strip(),
        "client_details": client_snapshot,
        "summary": call.summary.strip(),
        "opened_on": call.opened_on.isoformat(),
        "fields": fields,
        "event_timeline": timeline,
        "source_event_ids": sorted(event.id for event in call.events),
    }


def _fingerprint(source: dict[str, object]) -> str:
    payload = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fields_model(values: dict[str, object]) -> ServiceTechnicalReportFields:
    return ServiceTechnicalReportFields(**{
        field: str(values.get(field) or "")
        for field in FIELD_LABELS
    })


def _missing_fields(fields: ServiceTechnicalReportFields) -> list[str]:
    return [name for name in FIELD_LABELS if not getattr(fields, name).strip()]


def build_preview(db: Session, service_call_id: int) -> ServiceReportPreview:
    call = service_record_service.get_service_call(db, service_call_id, populate_existing=True)
    if call is None:
        raise ServiceReportNotFound("Chamado não encontrado.")
    if call.execution_status != "completed":
        raise ServiceReportNotReady("Relatório técnico só pode ser preparado após a conclusão explícita da execução.")
    effective = service_record_service.effective_service_events(call.events)
    source = _serialize_source(call, effective)
    fields = _fields_model(source["fields"])
    client_snapshot = dict(source["client_details"])
    missing = _missing_fields(fields)
    return ServiceReportPreview(
        service_call=call,
        fields=fields,
        client_snapshot=client_snapshot,
        completion_date_from_source=fields.completion_date,
        source_fingerprint=_fingerprint(source),
        source_event_ids=list(source["source_event_ids"]),
        event_timeline=list(source["event_timeline"]),
        missing_fields=missing,
    )


def _file_path(relative_path: str, output_root: Path, suffix: str) -> Path:
    root = output_root.resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root) or candidate.suffix.lower() != suffix or not candidate.is_file():
        raise ReportGenerationError("Arquivo do relatório não está disponível.")
    return candidate


def resolve_report_file(relative_path: str, output_root: Path, suffix: str | None = None) -> Path:
    root = output_root.resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ReportGenerationError("Arquivo do relatório não está disponível.")
    if suffix and candidate.suffix.lower() != suffix:
        raise ReportGenerationError("Arquivo do relatório não está disponível.")
    if candidate.suffix.lower() not in {".docx", ".pdf"}:
        raise ReportGenerationError("Arquivo do relatório não está disponível.")
    return candidate


def _result_from_record(record: ServiceTechnicalReport, output_root: Path, *, replayed: bool) -> ReportGenerationResult:
    docx_path = _file_path(record.docx_path, output_root, ".docx")
    pdf_path = _file_path(record.pdf_path, output_root, ".pdf")
    return ReportGenerationResult(record, docx_path, pdf_path, replayed)


def _promote_exclusive(source: Path, destination: Path) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
        return True
    except FileExistsError:
        source_digest = hashlib.sha256(source.read_bytes()).digest()
        existing_digest = hashlib.sha256(destination.read_bytes()).digest()
        if source_digest != existing_digest:
            raise ReportGenerationError("Há um arquivo anterior diferente no destino; nada foi sobrescrito.")
        return False


def _check_idempotency_key(value: str) -> str:
    key = value.strip()
    if not key or len(key) > 100 or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        raise ReportGenerationError("Identificador de confirmação inválido.")
    return key


def _render_context(call: ServiceCall, fields: ServiceTechnicalReportFields, preview: ServiceReportPreview,
                    report_date: date, manual_overrides: list[str]) -> dict[str, object]:
    values: dict[str, object] = {
        "CALL_ID": call.id,
        "SUMMARY": call.summary,
        "CLIENT": fields.client_name,
        "CLIENT_CNPJ": fields.client_cnpj,
        "CLIENT_PHONE": fields.client_phone,
        "CLIENT_ADDRESS": fields.client_address,
        "EQUIPMENT": fields.equipment,
        "OPENED_ON": _format_date(call.opened_on),
        "COMPLETED_ON": _format_date(date.fromisoformat(fields.completion_date)) if fields.completion_date else "",
        "REPORT_DATE": _format_date(report_date),
        "REPORTED_PROBLEM": fields.reported_problem,
        "ANALYSIS": fields.analysis,
        "WORK_PERFORMED": fields.work_performed,
        "VERIFICATION_RESULT": fields.verification_result,
        "EVENT_TIMELINE": "\n".join(
            f"{event['date']} · {event['type']}: {event['description']}".strip()
            for event in preview.event_timeline
        ),
        "MANUAL_OVERRIDES": ", ".join(FIELD_LABELS[name] for name in manual_overrides) or "Nenhum",
    }
    missing = _missing_fields(fields)
    if not fields.completion_date:
        missing.append("completion_date")
    values["__MISSING__"] = missing
    return values


def generate_report(
    db: Session,
    service_call_id: int,
    fields: ServiceTechnicalReportFields,
    *,
    idempotency_key: str,
    settings: ReportGenerationSettings,
    confirmed: bool,
    expected_fingerprint: str | None = None,
    assistant_action: AssistantAction | None = None,
) -> ReportGenerationResult:
    if not confirmed:
        raise ReportConfirmationRequired("Confirme explicitamente a geração do relatório.")
    key = _check_idempotency_key(idempotency_key)
    existing = db.scalar(select(ServiceTechnicalReport).where(ServiceTechnicalReport.idempotency_key == key))
    if existing is not None:
        if existing.service_call_id != service_call_id:
            raise ReportGenerationError("Este identificador de confirmação pertence a outro chamado.")
        return _result_from_record(existing, settings.output_dir, replayed=True)

    preview = build_preview(db, service_call_id)
    if expected_fingerprint and expected_fingerprint != preview.source_fingerprint:
        raise ReportPreviewOutdated("O histórico do chamado mudou desde a prévia. Revise os dados atualizados antes de gerar.")
    call = preview.service_call
    source_fields = preview.fields.model_dump()
    reviewed_fields = fields.model_dump()
    for name, label in FIELD_LABELS.items():
        reviewed_fields[name] = reviewed_fields[name].strip()
    if reviewed_fields["completion_date"]:
        try:
            date.fromisoformat(reviewed_fields["completion_date"])
        except ValueError as exc:
            raise ReportGenerationError("Data da execução inválida.") from exc
    overrides = [
        name for name in FIELD_LABELS
        if reviewed_fields[name] != source_fields[name]
    ]
    reviewed_model = ServiceTechnicalReportFields(**reviewed_fields)
    missing = _missing_fields(reviewed_model)

    try:
        business_today = datetime.now(ZoneInfo(settings.timezone)).date()
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ReportGenerationError("Fuso horário da aplicação inválido.") from exc

    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    report_relative_dir = Path("service-reports") / str(call.id)
    report_dir = settings.output_dir / report_relative_dir
    report_base = f"relatorio_tecnico_chamado_{call.id}_{key_hash}"
    report_base = f"{report_base}_{secrets.token_hex(6)}"
    docx_relative = (report_relative_dir / f"{report_base}.docx").as_posix()
    pdf_relative = (report_relative_dir / f"{report_base}.pdf").as_posix()
    docx_final = settings.output_dir / docx_relative
    pdf_final = settings.output_dir / pdf_relative
    report_dir.mkdir(parents=True, exist_ok=True)

    conversation: AssistantConversation | None = None
    action: AssistantAction | None = None
    promoted: list[Path] = []
    commit_attempted = False
    try:
        with db.begin_nested():
            if assistant_action is None:
                conversation = AssistantConversation()
                db.add(conversation)
                db.flush()
                request_id = f"service-report:{key}"
                action = AssistantAction(
                    conversation_id=conversation.id,
                    request_id=request_id,
                    confirmation_token_hash=hashlib.sha256(f"service-report-confirm:{key}".encode()).hexdigest(),
                    action_type="generate_service_report",
                    status="executing",
                    arguments_json={
                        "service_call_id": call.id,
                        "source_fingerprint": preview.source_fingerprint,
                        "manual_overrides": overrides,
                    },
                )
                db.add(action)
                db.flush()
                db.add(AssistantMessage(
                    conversation_id=conversation.id,
                    role="user",
                    content=f"Confirmação explícita para gerar o relatório técnico do chamado #{call.id}.",
                    request_id=request_id,
                ))
            else:
                if assistant_action.action_type != "generate_service_report":
                    raise ReportGenerationError("A ação de confirmação não corresponde a um relatório técnico.")
                if assistant_action.status != "executing":
                    raise ReportGenerationError("A ação de relatório não está em execução confirmada.")
                action = assistant_action
                action.arguments_json = {
                    **action.arguments_json,
                    "service_call_id": call.id,
                    "source_fingerprint": preview.source_fingerprint,
                    "manual_overrides": overrides,
                }

            with tempfile.TemporaryDirectory(prefix=f".report-{key_hash}-", dir=report_dir) as temporary:
                temp_dir = Path(temporary)
                temp_docx = temp_dir / f"{report_base}.docx"
                temp_pdf = temp_dir / f"{report_base}.pdf"
                render_context = _render_context(call, reviewed_model, preview, business_today, overrides)
                missing_for_document = list(render_context.pop("__MISSING__"))
                technical_report_document_service.render_technical_report(
                    template_path=settings.template_path,
                    context=render_context,
                    missing_fields=missing_for_document,
                    output_path=temp_docx,
                )
                pdf_service.convert_docx_to_pdf(
                    docx_path=temp_docx,
                    pdf_path=temp_pdf,
                    libreoffice_cmd=settings.libreoffice_cmd,
                    docker_image=settings.libreoffice_docker_image,
                )
                if not temp_pdf.is_file() or temp_pdf.stat().st_size == 0 or temp_pdf.read_bytes()[:5] != b"%PDF-":
                    raise ReportGenerationError("A conversão não produziu um PDF válido; nenhum relatório foi registrado.")
                if _promote_exclusive(temp_docx, docx_final):
                    promoted.append(docx_final)
                if _promote_exclusive(temp_pdf, pdf_final):
                    promoted.append(pdf_final)

            report = ServiceTechnicalReport(
                service_call_id=call.id,
                assistant_action_id=action.id,
                document_event_id=None,
                idempotency_key=key,
                source_fingerprint=preview.source_fingerprint,
                source_event_ids=preview.source_event_ids,
                client_snapshot_json=preview.client_snapshot,
                fields_json=reviewed_fields,
                source_fields_json=source_fields,
                manual_overrides_json=overrides,
                missing_fields_json=missing,
                docx_path=docx_relative,
                pdf_path=pdf_relative,
                confirmed_at=datetime.now(UTC).replace(tzinfo=None),
            )
            db.add(report)
            db.flush()

            report_step = db.scalar(select(ServiceWorkflowStep).where(
                ServiceWorkflowStep.service_call_id == call.id,
                ServiceWorkflowStep.step_type == "report",
            ).with_for_update())
            if report_step is not None and report_step.status != "completed":
                db.add(ServiceWorkflowTransition(
                    service_call_id=call.id,
                    step_type="report",
                    previous_status=report_step.status,
                    new_status="completed",
                    observation="Relatório técnico DOCX/PDF gerado após confirmação explícita.",
                    service_event_id=None,
                    assistant_action_id=action.id,
                ))
            action.status = "executed"
            action.result_json = {
                "service_call_id": call.id,
                "service_technical_report_id": report.id,
                "docx_path": docx_relative,
                "pdf_path": pdf_relative,
                "report_id": report.id,
                "report_docx_url": f"/web/services/relatorios/{report.id}/docx",
                "report_pdf_url": f"/web/services/relatorios/{report.id}/pdf",
            }
            if conversation is not None:
                db.add(AssistantMessage(
                    conversation_id=conversation.id,
                    role="assistant",
                    kind="tool_result",
                    content=f"Relatório técnico do chamado #{call.id} gerado em DOCX e PDF.",
                    reply_to_request_id=request_id,
                    details_json={"service_technical_report_id": report.id},
                ))
            service_record_service.rebuild_current_projection(db, call)
        commit_attempted = True
        db.commit()
        db.refresh(report)
        return ReportGenerationResult(report, docx_final, pdf_final)
    except IntegrityError as exc:
        db.rollback()
        for path in promoted:
            path.unlink(missing_ok=True)
        existing = db.scalar(select(ServiceTechnicalReport).where(ServiceTechnicalReport.idempotency_key == key))
        if existing is not None:
            if existing.service_call_id != service_call_id:
                raise ReportGenerationError("Este identificador de confirmação pertence a outro chamado.") from exc
            return _result_from_record(existing, settings.output_dir, replayed=True)
        raise ReportGenerationError("A confirmação já está sendo processada ou conflitou com outro pedido.") from exc
    except Exception as exc:
        db.rollback()
        if commit_attempted:
            try:
                with Session(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as recovery_db:
                    recovered = recovery_db.scalar(
                        select(ServiceTechnicalReport).where(
                            ServiceTechnicalReport.idempotency_key == key
                        )
                    )
                    if recovered is not None:
                        if recovered.service_call_id != service_call_id:
                            raise ReportGenerationError(
                                "Este identificador de confirmação pertence a outro chamado."
                            ) from exc
                        return _result_from_record(
                            recovered, settings.output_dir, replayed=True
                        )
            except ReportGenerationError:
                raise
            except Exception:
                # The database may have accepted COMMIT but be temporarily unreachable.
                # Keep promoted files so a later retry can reconcile the same key.
                raise ReportGenerationError(
                    "Não foi possível confirmar se o relatório foi registrado. "
                    "Tente novamente com o mesmo identificador de confirmação."
                ) from None
        for path in promoted:
            path.unlink(missing_ok=True)
        if isinstance(exc, ServiceReportError):
            raise
        raise ReportGenerationError("Não foi possível gerar DOCX e PDF. Nenhum relatório foi registrado.") from exc


def list_reports(db: Session, service_call_id: int) -> list[ServiceTechnicalReport]:
    return list(db.scalars(
        select(ServiceTechnicalReport)
        .where(ServiceTechnicalReport.service_call_id == service_call_id)
        .order_by(ServiceTechnicalReport.created_at.desc(), ServiceTechnicalReport.id.desc())
    ))
