from __future__ import annotations

from datetime import date, datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import CampaignContactConsentEvent, Client, ClientCampaignContact
from app.routers.promotion_web_support import _require_form_token
from app.services.promotion_campaign_service import (
    CampaignValidationError,
    is_valid_campaign_email,
    normalize_email,
)

router = APIRouter()
settings = get_settings()


def _parse_contact_form(form, *, previous: ClientCampaignContact | None = None) -> dict[str, object]:
    name = str(form.get("name", "")).strip()[:120]
    email = str(form.get("email", "")).strip()
    if not is_valid_campaign_email(email):
        raise CampaignValidationError("Informe um endereço de e-mail válido.")
    enabled = form.get("marketing_enabled") == "on"
    source = str(form.get("consent_source", "")).strip()[:500]
    consented_on = str(form.get("consented_on", "")).strip()
    consented_at = None
    if enabled:
        if not source or not consented_on:
            raise CampaignValidationError("Para autorizar campanhas, informe origem e data do consentimento.")
        try:
            consented_at = datetime.combine(date.fromisoformat(consented_on), time.min)
        except ValueError as exc:
            raise CampaignValidationError("Data do consentimento inválida.") from exc
    return {
        "name": name,
        "email": email,
        "email_normalized": normalize_email(email),
        "marketing_enabled": enabled,
        "consent_source": source if enabled else (previous.consent_source if previous else ""),
        "consented_at": consented_at if enabled else (previous.consented_at if previous else None),
    }


def _register_consent_event(
    db: Session,
    contact: ClientCampaignContact,
    *,
    event_type: str,
    source: str,
    occurred_at: datetime,
    email_snapshot: str | None = None,
):
    event = CampaignContactConsentEvent(
        contact_id=contact.id,
        event_key=f"contact:{contact.id}:{event_type}:{uuid4().hex}",
        event_type=event_type,
        email_snapshot=email_snapshot or contact.email_normalized,
        source=source[:500],
        occurred_at=occurred_at,
    )
    db.add(event)


@router.post("/web/clients/{client_id}/campaign-contacts")
async def create_campaign_contact(client_id: int, request: Request, db: Session = Depends(get_db)):
    client = db.query(Client).filter_by(id=client_id).one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado.")
    form = await request.form()
    _require_form_token(f"client-contacts:{client_id}", form)
    try:
        values = _parse_contact_form(form)
        contact = ClientCampaignContact(client_id=client.id, **values)
        db.add(contact)
        db.flush()
        if contact.marketing_enabled:
            _register_consent_event(
                db,
                contact,
                event_type="opt_in",
                source=contact.consent_source,
                occurred_at=contact.consented_at,
            )
        db.commit()
    except CampaignValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Este endereço já está cadastrado para o cliente.") from exc
    return RedirectResponse(f"/web/clients/{client_id}#campaign-contacts", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/web/clients/{client_id}/campaign-contacts/{contact_id}")
async def update_campaign_contact(client_id: int, contact_id: int, request: Request, db: Session = Depends(get_db)):
    contact = db.query(ClientCampaignContact).filter_by(id=contact_id, client_id=client_id).with_for_update().one_or_none()
    if contact is None:
        raise HTTPException(status_code=404, detail="Contato não encontrado.")
    form = await request.form()
    _require_form_token(f"client-contacts:{client_id}", form)
    try:
        values = _parse_contact_form(form, previous=contact)
        old_enabled = contact.marketing_enabled
        old_email_normalized = contact.email_normalized
        old_source = contact.consent_source
        old_consented_at = contact.consented_at
        new_enabled = bool(values["marketing_enabled"])
        email_changed = values["email_normalized"] != old_email_normalized
        consent_details_changed = values["consent_source"] != old_source or values["consented_at"] != old_consented_at
        new_explicit_consent = form.get("reauthorize_consent") == "on"
        if old_enabled and new_enabled and (email_changed or consent_details_changed) and not new_explicit_consent:
            raise CampaignValidationError(
                "Ao trocar o endereço ou os dados da autorização, confirme o novo consentimento e registre origem/data."
            )
        for key, value in values.items():
            setattr(contact, key, value)
        if old_enabled and not new_enabled:
            revoked_at = datetime.now(ZoneInfo(settings.assistant_timezone)).replace(tzinfo=None)
            contact.revoked_at = revoked_at
            revocation_source = str(form.get("revocation_source", "")).strip()[:500] or "Revogado no cadastro local"
            contact.revocation_source = revocation_source
            _register_consent_event(
                db,
                contact,
                event_type="opt_out",
                source=revocation_source,
                occurred_at=revoked_at,
                email_snapshot=old_email_normalized,
            )
        elif not old_enabled and new_enabled:
            contact.revoked_at = None
            contact.revocation_source = ""
            _register_consent_event(
                db,
                contact,
                event_type="opt_in",
                source=contact.consent_source,
                occurred_at=contact.consented_at,
            )
        elif old_enabled and new_enabled and new_explicit_consent:
            _register_consent_event(
                db,
                contact,
                event_type="opt_in",
                source=contact.consent_source,
                occurred_at=contact.consented_at,
            )
        db.commit()
    except CampaignValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Este endereço já está cadastrado para o cliente.") from exc
    return RedirectResponse(f"/web/clients/{client_id}#campaign-contacts", status_code=status.HTTP_303_SEE_OTHER)
