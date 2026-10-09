from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Client, ClientCampaignContact, Proposal, ServiceCall
from app.routers.web_rendering import render_template
from app.services.promotion_campaign_service import promotion_form_token

router = APIRouter()


@router.get("/web/clients", name="web_clients")
def clients_page(request: Request, db: Session = Depends(get_db)) -> object:
    clients = db.query(Client).order_by(Client.razao_social.asc()).all()
    proposal_counts = dict(db.query(Proposal.client_id, func.count(Proposal.id)).group_by(Proposal.client_id).all())
    service_counts = dict(db.query(ServiceCall.client_id, func.count(ServiceCall.id)).group_by(ServiceCall.client_id).all())
    return render_template(
        request,
        "clients.html",
        {"clients": clients, "proposal_counts": proposal_counts, "service_counts": service_counts},
    )


@router.get("/web/clients/new", name="web_client_new")
def client_new_page(request: Request) -> object:
    return render_template(request, "client_form.html", {"client": None, "action_url": "/web/clients/new"})


@router.post("/web/clients/new")
async def client_new_submit(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    form = await request.form()
    client = Client(
        razao_social=str(form.get("razao_social", "")).strip(),
        cnpj=str(form.get("cnpj", "")).strip(),
        endereco_linha1=str(form.get("endereco_linha1", "")).strip(),
        endereco_linha2=str(form.get("endereco_linha2", "")).strip(),
        cep=str(form.get("cep", "")).strip(),
        cidade_uf=str(form.get("cidade_uf", "")).strip(),
        pais=str(form.get("pais", "Brasil")).strip() or "Brasil",
        caixa_postal=str(form.get("caixa_postal", "")).strip(),
        telefone=str(form.get("telefone", "")).strip(),
        site=str(form.get("site", "")).strip(),
        contato_padrao=str(form.get("contato_padrao", "")).strip(),
    )
    if not client.razao_social:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Razao social is required")
    db.add(client)
    db.commit()
    return RedirectResponse(url=request.url_for("web_clients"), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/web/clients/{client_id}", name="web_client_detail")
def client_detail_page(client_id: int, request: Request, db: Session = Depends(get_db)) -> object:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    proposals = db.query(Proposal).filter(Proposal.client_id == client_id).order_by(Proposal.data_geracao.desc(), Proposal.id.desc()).limit(10).all()
    services = db.query(ServiceCall).filter(ServiceCall.client_id == client_id).order_by(ServiceCall.opened_on.desc(), ServiceCall.id.desc()).limit(10).all()
    return render_template(
        request,
        "client_form.html",
        {
            "client": client,
            "action_url": f"/web/clients/{client_id}/edit",
            "proposals": proposals,
            "services": services,
            "campaign_contacts": db.query(ClientCampaignContact)
            .filter_by(client_id=client_id)
            .order_by(ClientCampaignContact.email.asc())
            .all(),
            "campaign_form_token": promotion_form_token(f"client-contacts:{client_id}"),
        },
    )


@router.post("/web/clients/{client_id}/edit")
async def client_edit_submit(client_id: int, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    form = await request.form()
    fields = [
        "razao_social",
        "cnpj",
        "endereco_linha1",
        "endereco_linha2",
        "cep",
        "cidade_uf",
        "pais",
        "caixa_postal",
        "telefone",
        "site",
        "contato_padrao",
    ]
    for field in fields:
        setattr(client, field, str(form.get(field, "")).strip())
    if not client.razao_social:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Razao social is required")
    db.add(client)
    db.commit()
    return RedirectResponse(url=request.url_for("web_clients"), status_code=status.HTTP_303_SEE_OTHER)
