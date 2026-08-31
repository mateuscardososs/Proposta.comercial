from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Client, Proposal, User
from app.schemas import ExternalUploadPreviewResponse, WordReuploadPreviewResponse
from app.services import proposal_file_service
from app.utils.formatters import decimal_from_str
from app.utils.currency import format_brl
from app.utils.dates import format_date_br


router = APIRouter(tags=["proposal-files"])
settings = get_settings()
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _read_upload_limited(upload: UploadFile) -> bytes:
    payload = await upload.read(proposal_file_service.MAX_UPLOAD_BYTES + 1)
    if len(payload) > proposal_file_service.MAX_UPLOAD_BYTES:
        raise proposal_file_service.ProposalFileValidationError(
            "O arquivo excede o limite de 20 MB."
        )
    return payload


def _proposal_or_404(db: Session, proposal_id: int) -> Proposal:
    proposal = db.get(Proposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposta não encontrada.")
    return proposal


def _resolve_output_file(relative_path: str, output_root: Path) -> Path:
    if not relative_path:
        raise HTTPException(status_code=404, detail="Arquivo Word não encontrado.")
    root = output_root.resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        raise HTTPException(status_code=404, detail="Arquivo Word não encontrado.")
    if candidate.suffix.lower() != ".docx" or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Arquivo Word não encontrado.")
    return candidate


def _ensure_word_source(proposal: Proposal) -> None:
    try:
        _resolve_output_file(proposal.docx_path, settings.output_dir)
    except HTTPException as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A proposta não possui um arquivo Word disponível para reenvio.",
        ) from exc


def _validation_http_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=str(exc),
    )


def _parse_positive_id(value: str, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise proposal_file_service.ProposalFileValidationError(
            f"Dados de {label.lower()} inválidos."
        ) from exc
    if parsed <= 0:
        raise proposal_file_service.ProposalFileValidationError(
            f"Dados de {label.lower()} inválidos."
        )
    return parsed


def _parse_proposal_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise proposal_file_service.ProposalFileValidationError(
            "Data da proposta inválida."
        ) from exc


def _parse_total(value: str) -> Decimal:
    try:
        return decimal_from_str(value)
    except ValueError as exc:
        raise proposal_file_service.ProposalFileValidationError(
            "Valor total inválido."
        ) from exc


def _render_template(request: Request, template_name: str, context: dict) -> object:
    base_context = {
        "request": request,
        "format_brl": format_brl,
        "format_date_br": format_date_br,
    }
    base_context.update(context)
    return request.app.state.templates.TemplateResponse(template_name, base_context)


@router.get("/web/proposals/upload-externo", name="web_proposal_external_upload")
def external_upload_page(
    request: Request,
    db: Session = Depends(get_db),
) -> object:
    clients = db.query(Client).order_by(Client.razao_social.asc()).all()
    users = db.query(User).filter(User.ativo.is_(True)).order_by(User.nome.asc()).all()
    return _render_template(
        request,
        "proposal_external_upload.html",
        {
            "clients": clients,
            "users": users,
            "default_user_id": users[0].id if users else None,
            "today": date.today(),
        },
    )


@router.get(
    "/web/proposals/{proposal_id}/reenviar-word",
    name="web_proposal_word_reupload",
)
def word_reupload_page(
    proposal_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> object:
    proposal = _proposal_or_404(db, proposal_id)
    _ensure_word_source(proposal)
    return _render_template(
        request,
        "proposal_word_reupload.html",
        {
            "proposal": proposal,
            "download_url": f"/web/proposals/{proposal.id}/baixar-word",
            "today": date.today(),
        },
    )


@router.post(
    "/api/proposal-files/upload-externo/preview",
    response_model=ExternalUploadPreviewResponse,
)
async def external_preview(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> ExternalUploadPreviewResponse:
    try:
        payload = await _read_upload_limited(file)
        analysis = proposal_file_service.analyze_external_upload(
            db,
            file.filename or "",
            payload,
        )
    except proposal_file_service.ProposalFileValidationError as exc:
        raise _validation_http_error(exc) from exc
    suggestion = analysis.suggested_client
    return ExternalUploadPreviewResponse(
        filename=analysis.filename,
        file_type=analysis.file_type,
        suggested_client_id=suggestion.client_id if suggestion else None,
        suggested_client_name=suggestion.client_name if suggestion else None,
        client_confidence=suggestion.confidence if suggestion else None,
        suggested_valor_total=analysis.suggested_valor_total,
        warnings=list(analysis.warnings),
    )


@router.post(
    "/api/proposal-files/{proposal_id}/word-preview",
    response_model=WordReuploadPreviewResponse,
)
async def word_preview(
    proposal_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> WordReuploadPreviewResponse:
    proposal = _proposal_or_404(db, proposal_id)
    _ensure_word_source(proposal)
    try:
        payload = await _read_upload_limited(file)
        analysis = proposal_file_service.analyze_word_reupload(
            file.filename or "",
            payload,
        )
    except proposal_file_service.ProposalFileValidationError as exc:
        raise _validation_http_error(exc) from exc
    return WordReuploadPreviewResponse(
        filename=analysis.filename,
        valor_total=analysis.valor_total,
        marker_found=analysis.marker_found,
        warnings=list(analysis.warnings),
    )


@router.get("/web/proposals/{proposal_id}/baixar-word")
def download_word(
    proposal_id: int,
    db: Session = Depends(get_db),
) -> FileResponse:
    proposal = _proposal_or_404(db, proposal_id)
    candidate = _resolve_output_file(proposal.docx_path, settings.output_dir)
    return FileResponse(
        candidate,
        filename=candidate.name,
        media_type=DOCX_MEDIA_TYPE,
    )


@router.post("/web/proposals/{proposal_id}/reenviar-word")
async def confirm_word_reupload(
    proposal_id: int,
    file: UploadFile = File(...),
    valor_total: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    proposal = _proposal_or_404(db, proposal_id)
    _ensure_word_source(proposal)
    try:
        payload = await _read_upload_limited(file)
        created = proposal_file_service.create_word_revision(
            db,
            proposal_id,
            file.filename or "",
            payload,
            _parse_total(valor_total),
            settings,
        )
    except proposal_file_service.ProposalFileConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (proposal_file_service.ProposalFileValidationError, ValueError) as exc:
        raise _validation_http_error(exc) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Não foi possível gerar o PDF da nova revisão.",
        ) from exc
    return RedirectResponse(
        url=f"/web/proposals/{created.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/web/proposals/upload-externo")
async def confirm_external_upload(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    user_id: str = Form(...),
    data_geracao: str = Form(...),
    valor_total: str = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        payload = await _read_upload_limited(file)
        created = proposal_file_service.create_external_proposal(
            db,
            file.filename or "",
            payload,
            _parse_positive_id(client_id, "cliente"),
            _parse_positive_id(user_id, "responsável"),
            _parse_proposal_date(data_geracao),
            _parse_total(valor_total),
            settings,
        )
    except proposal_file_service.ProposalFileConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (proposal_file_service.ProposalFileValidationError, ValueError) as exc:
        raise _validation_http_error(exc) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Não foi possível processar o arquivo da proposta.",
        ) from exc
    return RedirectResponse(
        url=f"/web/proposals/{created.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
