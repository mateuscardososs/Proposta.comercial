from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Client, User
from app.schemas import (
    ImportProposalFileResult,
    ImportProposalItemPreview,
    ImportProposalPreview,
    ImportProposalsResponse,
    ImportSchedulePreview,
)
from app.services import pdf_import_service, proposal_service

router = APIRouter(tags=["imports"])
logger = logging.getLogger(__name__)


def _find_client_by_name(db: Session, client_name: str) -> Client | None:
    normalized = client_name.strip()
    if not normalized:
        return None
    return (
        db.query(Client)
        .filter(func.lower(Client.razao_social) == normalized.lower())
        .first()
    )


def _ensure_active_user(db: Session, user_id: int | None) -> User:
    query = db.query(User).filter(User.ativo.is_(True))
    if user_id:
        user = query.filter(User.id == user_id).first()
        if not user:
            raise ValueError("Active user for import not found.")
        return user

    first_active = query.order_by(User.id.asc()).first()
    if not first_active:
        raise ValueError("No active user available for import.")
    return first_active


def _preview_from_parsed(parsed: pdf_import_service.ParsedProposalData, client: Client | None) -> ImportProposalPreview:
    return ImportProposalPreview(
        filename=parsed.filename,
        client_name=parsed.client_name,
        atencao=parsed.atencao,
        objeto_texto=parsed.objeto_texto,
        condicao_pagamento_dias=parsed.condicao_pagamento_dias,
        imposto_percentual=parsed.imposto_percentual,
        items=[
            ImportProposalItemPreview(
                descricao=item.descricao,
                unidade=item.unidade,
                qtd=item.qtd,
                valor_unit=item.valor_unit,
            )
            for item in parsed.items
        ],
        schedule_rows=[
            ImportSchedulePreview(
                dia_label=row.dia_label,
                descricao=row.descricao,
                horas_servico=row.horas_servico,
            )
            for row in parsed.schedule_rows
        ],
        warnings=parsed.warnings,
        matched_client_id=client.id if client else None,
        matched_client_name=client.razao_social if client else None,
    )


def _ensure_client(db: Session, parsed: pdf_import_service.ParsedProposalData) -> Client:
    existing = _find_client_by_name(db, parsed.client_name)
    if existing:
        return existing
    client = Client(
        razao_social=parsed.client_name.strip(),
        contato_padrao=parsed.atencao.strip(),
    )
    db.add(client)
    db.flush()
    return client


@router.post("/api/import-proposals", response_model=ImportProposalsResponse)
async def import_proposals(
    files: list[UploadFile] = File(...),
    confirm: bool = Form(default=False),
    user_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
) -> ImportProposalsResponse:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files were uploaded.")

    import_user: User | None = None
    if confirm:
        try:
            import_user = _ensure_active_user(db, user_id=user_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    imported_count = 0
    results: list[ImportProposalFileResult] = []

    for upload in files:
        filename = upload.filename or "unknown.pdf"
        try:
            payload = await upload.read()
            if not payload:
                raise ValueError("Empty file.")
            parsed, parse_error = pdf_import_service.parse_pdf_bytes_safe(payload, filename=filename)
            if parse_error or not parsed:
                results.append(
                    ImportProposalFileResult(
                        filename=filename,
                        success=False,
                        message=parse_error or "Unknown parse error.",
                    )
                )
                continue

            matched_client = _find_client_by_name(db, parsed.client_name)
            preview = _preview_from_parsed(parsed, matched_client)

            if not confirm:
                results.append(
                    ImportProposalFileResult(
                        filename=filename,
                        success=True,
                        message="Preview parsed successfully.",
                        preview=preview,
                    )
                )
                continue

            client = _ensure_client(db, parsed)
            proposal_payload = parsed.to_proposal_payload(
                client_id=client.id,
                user_id=import_user.id if import_user else 0,
            )
            proposal_payload.objeto_tipo = "outro"
            if not proposal_payload.objeto_texto:
                proposal_payload.objeto_texto = "Importado de PDF legado"
            created = proposal_service.create_proposal(db, proposal_payload, mode="new")
            imported_count += 1

            results.append(
                ImportProposalFileResult(
                    filename=filename,
                    success=True,
                    message="Imported successfully.",
                    proposal_id=created.id,
                    proposal_numero=created.numero,
                    proposal_revisao=created.revisao,
                    preview=preview,
                )
            )
        except Exception as exc:
            db.rollback()
            logger.exception("Import failed for file '%s': %s", filename, exc)
            results.append(
                ImportProposalFileResult(
                    filename=filename,
                    success=False,
                    message=str(exc),
                )
            )

    return ImportProposalsResponse(
        confirm=confirm,
        processed=len(files),
        imported=imported_count,
        results=results,
    )
