from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.db import get_db
from app.models import Proposal
from app.schemas import ProposalCloneResponse, ProposalCreate, ProposalRead, ProposalSummary
from app.services import proposal_service, suggestion_service
from app.utils.currency import format_brl

router = APIRouter(prefix="/api/proposals", tags=["proposals"])
settings = get_settings()


@router.get("/", response_model=list[ProposalSummary])
def list_proposals(db: Session = Depends(get_db)) -> list[Proposal]:
    return (
        db.query(Proposal)
        .order_by(Proposal.data_geracao.desc(), Proposal.id.desc())
        .all()
    )


@router.get("/{proposal_id}", response_model=ProposalRead)
def get_proposal(proposal_id: int, db: Session = Depends(get_db)) -> Proposal:
    proposal = proposal_service.get_proposal_with_details(db, proposal_id)
    if not proposal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    return proposal


@router.post("/", response_model=ProposalRead, status_code=status.HTTP_201_CREATED)
def create_proposal(
    payload: ProposalCreate,
    mode: str = Query(default="new", pattern="^(new|revision)$"),
    base_proposal_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Proposal:
    try:
        created = proposal_service.create_proposal(
            db,
            payload=payload,
            mode=mode,
            base_proposal_id=base_proposal_id,
        )
        proposal_service.generate_documents(db, proposal_id=created.id, settings=settings)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    proposal = proposal_service.get_proposal_with_details(db, created.id)
    if not proposal:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to load proposal")
    return proposal


@router.post("/{proposal_id}/duplicate", response_model=ProposalRead, status_code=status.HTTP_201_CREATED)
def duplicate_proposal(proposal_id: int, db: Session = Depends(get_db)) -> Proposal:
    try:
        created = proposal_service.duplicate_proposal(db, proposal_id=proposal_id)
        proposal_service.generate_documents(db, proposal_id=created.id, settings=settings)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    proposal = proposal_service.get_proposal_with_details(db, created.id)
    if not proposal:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to load proposal")
    return proposal


@router.post("/{proposal_id}/clone", response_model=ProposalCloneResponse, status_code=status.HTTP_201_CREATED)
def clone_proposal(proposal_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        created = proposal_service.clone_proposal(db, proposal_id=proposal_id)
        proposal_service.generate_documents(db, proposal_id=created.id, settings=settings)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return {
        "id": created.id,
        "numero": created.numero,
        "revisao": created.revisao,
        "redirect_url": f"/web/proposals/{created.id}",
    }


@router.get("/clients/{client_id}/last", response_model=ProposalRead | None)
def get_last_proposal_for_client(client_id: int, db: Session = Depends(get_db)) -> Proposal | None:
    return suggestion_service.get_last_proposal_for_client(db, client_id=client_id)


@router.get("/clients/{client_id}/suggest-item")
def suggest_item_value(client_id: int, descricao: str, db: Session = Depends(get_db)) -> dict[str, str | None]:
    value = suggestion_service.suggest_last_item_value(db, client_id=client_id, descricao=descricao)
    return {"descricao": descricao, "valor_unit": format_brl(value) if value is not None else None}
