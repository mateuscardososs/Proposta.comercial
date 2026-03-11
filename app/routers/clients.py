from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Client
from app.schemas import ClientCreate, ClientRead, ClientUpdate, ProposalRecentSummary
from app.services import proposal_service

router = APIRouter(prefix="/api/clients", tags=["clients"])


@router.get("/", response_model=list[ClientRead])
def list_clients(db: Session = Depends(get_db)) -> list[Client]:
    return db.query(Client).order_by(Client.razao_social.asc()).all()


@router.get("/{client_id}", response_model=ClientRead)
def get_client(client_id: int, db: Session = Depends(get_db)) -> Client:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return client


@router.post("/", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
def create_client(payload: ClientCreate, db: Session = Depends(get_db)) -> Client:
    client = Client(**payload.model_dump())
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.put("/{client_id}", response_model=ClientRead)
def update_client(client_id: int, payload: ClientUpdate, db: Session = Depends(get_db)) -> Client:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(client, field, value)

    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.get("/{client_id}/recent-proposals", response_model=list[ProposalRecentSummary])
def recent_proposals(client_id: int, db: Session = Depends(get_db)) -> list[ProposalRecentSummary]:
    client = db.query(Client.id).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    proposals = proposal_service.get_recent_proposals_by_client(db, client_id=client_id, limit=10)
    return [
        ProposalRecentSummary(
            id=proposal.id,
            numero=proposal.numero,
            revisao=proposal.revisao,
            data_geracao=proposal.data_geracao,
            objeto_texto=proposal.objeto_texto or proposal.objeto_tipo,
            valor_total=proposal.valor_total,
            responsavel_nome=proposal.user.nome if proposal.user else "",
            client_id=proposal.client_id,
        )
        for proposal in proposals
    ]
