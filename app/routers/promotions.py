from __future__ import annotations

from datetime import date, datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from starlette.datastructures import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.db import get_db
from app.models import (
    CampaignContactConsentEvent,
    Client,
    ClientCampaignContact,
    PromotionCampaign,
    PromotionRecipient,
)
from app.services.promotion_campaign_service import (
    CampaignSendUnavailable,
    CampaignValidationError,
    cancel_campaign,
    confirm_and_send_campaign,
    create_campaign_draft,
    eligible_campaign_contacts,
    is_valid_campaign_email,
    mark_generation_failure,
    normalize_email,
    promotion_form_token,
    update_campaign_preview,
    verify_promotion_form_token,
)
from app.services.promotion_generation_service import (
    GeminiPromotionGenerator,
    GeneratedImage,
    PromotionGenerationError,
    store_campaign_image,
    validate_image_bytes,
)
from app.services.promotion_mail_service import SmtpCampaignMailer, campaign_smtp_ready

router = APIRouter(tags=["promotions"])
settings = get_settings()
_MAX_CAMPAIGN_DESCRIPTION = 12000


def _templates(request: Request):
    return request.app.state.templates


def _page(request: Request, template: str, context: dict[str, object]):
    base = {"request": request, "title": "Promoções"}
    base.update(context)
    return _templates(request).TemplateResponse(template, base)


def _require_form_token(scope: str, form) -> None:
    token = str(form.get("form_token", ""))
    if not verify_promotion_form_token(scope, token):
        raise HTTPException(status_code=403, detail="Formulário expirado ou inválido. Atualize a página e tente novamente.")


async def _read_uploaded_image(upload: object, *, max_bytes: int) -> tuple[bytes, str] | None:
    if not isinstance(upload, UploadFile) or not upload.filename:
        return None
    mime = (upload.content_type or "").casefold()
    if mime not in {"image/png", "image/jpeg"}:
        raise CampaignValidationError("A imagem deve ser PNG ou JPEG.")
    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise CampaignValidationError("A imagem excede o limite configurado.")
    try:
        validate_image_bytes(data, mime)
    except PromotionGenerationError as exc:
        raise CampaignValidationError(str(exc)) from exc
    return data, mime


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


@router.get("/web/promocoes", name="web_promotions")
def promotions_page(request: Request, db: Session = Depends(get_db)):
    campaigns = db.query(PromotionCampaign).order_by(PromotionCampaign.created_at.desc(), PromotionCampaign.id.desc()).limit(30).all()
    return _page(
        request,
        "promotions.html",
        {
            "campaigns": campaigns,
            "contacts": eligible_campaign_contacts(db),
            "send_enabled": campaign_smtp_ready(settings),
            "send_unavailable_reason": "Configure SMTP de saída separadamente; a leitura IMAP não habilita envios." if not campaign_smtp_ready(settings) else "",
            "request_key": uuid4().hex,
            "generation_enabled": bool(settings.gemini_api_key.get_secret_value()),
            "max_reference_image_mb": settings.promotion_max_reference_image_bytes // 1024 // 1024,
            "form_token": promotion_form_token("new-campaign"),
        },
    )


@router.post("/web/promocoes")
async def generate_campaign(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    _require_form_token("new-campaign", form)
    request_key = str(form.get("request_key", "")).strip()
    description = str(form.get("description", "")).strip()
    if not request_key or len(request_key) > 80:
        raise HTTPException(status_code=422, detail="Chave da solicitação inválida. Atualize a página e tente novamente.")
    if not description or len(description) > _MAX_CAMPAIGN_DESCRIPTION:
        raise HTTPException(status_code=422, detail="Descreva a campanha (até 12.000 caracteres).")
    existing = db.query(PromotionCampaign).filter_by(request_key=request_key).one_or_none()
    if existing is not None:
        return RedirectResponse(f"/web/promocoes/{existing.id}", status_code=status.HTTP_303_SEE_OTHER)
    selected: list[int] = []
    for raw_id in form.getlist("contact_ids"):
        try:
            selected.append(int(raw_id))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Seleção de contato inválida.") from exc
    try:
        campaign = create_campaign_draft(
            db,
            request_key=request_key,
            description=description,
            subject="",
            body="",
            image_path="",
            selected_contact_ids=selected,
            status="generating",
        )
    except CampaignValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if campaign.status != "generating" or campaign.subject or campaign.image_path:
        return RedirectResponse(f"/web/promocoes/{campaign.id}", status_code=status.HTTP_303_SEE_OTHER)

    copy = None
    try:
        reference = await _read_uploaded_image(
            form.get("reference_image"), max_bytes=settings.promotion_max_reference_image_bytes
        )
        generator_factory = getattr(request.app.state, "promotion_generator_factory", None)
        generator = generator_factory() if callable(generator_factory) else GeminiPromotionGenerator(settings)
        copy = generator.generate_copy(description)
        image = generator.generate_image(
            description,
            reference_image=reference[0] if reference else None,
            reference_mime=reference[1] if reference else None,
        )
        image_path = store_campaign_image(settings.output_dir, campaign_id=campaign.id, revision=2, image=image)
        update_campaign_preview(
            db,
            campaign.id,
            description=description,
            subject=copy.subject,
            body=copy.body,
            image_path=image_path,
            image_mime=image.mime_type,
        )
    except PromotionGenerationError as exc:
        if copy is not None:
            update_campaign_preview(
                db,
                campaign.id,
                description=description,
                subject=copy.subject,
                body=copy.body,
                image_path="",
                image_mime="",
            )
        mark_generation_failure(db, campaign_id=campaign.id, code=exc.code)
    except CampaignValidationError:
        mark_generation_failure(db, campaign_id=campaign.id, code="invalid_reference")
    except OSError:
        if copy is not None:
            update_campaign_preview(
                db,
                campaign.id,
                description=description,
                subject=copy.subject,
                body=copy.body,
                image_path="",
                image_mime="",
            )
        mark_generation_failure(db, campaign_id=campaign.id, code="image_storage_failed")
    return RedirectResponse(f"/web/promocoes/{campaign.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/web/promocoes/{campaign_id}", name="web_promotion_detail")
def promotion_detail(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    campaign = (
        db.query(PromotionCampaign)
        .options(joinedload(PromotionCampaign.recipients).joinedload(PromotionRecipient.contact))
        .filter_by(id=campaign_id)
        .one_or_none()
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campanha não encontrada.")
    return _page(
        request,
        "promotion_detail.html",
        {
            "campaign": campaign,
            "send_enabled": campaign_smtp_ready(settings),
            "send_unavailable_reason": "Configure SMTP de saída separadamente; a leitura IMAP não habilita envios." if not campaign_smtp_ready(settings) else "",
            "output_image_url": f"/output/{campaign.image_path}" if campaign.image_path else "",
            "generation_enabled": bool(settings.gemini_api_key.get_secret_value()),
            "max_reference_image_bytes": settings.promotion_max_reference_image_bytes,
            "form_token": promotion_form_token(f"campaign:{campaign.id}:revision:{campaign.revision}"),
        },
    )


@router.post("/web/promocoes/{campaign_id}/edit")
async def edit_campaign(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    campaign = db.query(PromotionCampaign).filter_by(id=campaign_id).one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campanha não encontrada.")
    if campaign.status not in {"draft", "generation_failed"}:
        raise HTTPException(status_code=422, detail="Campanha bloqueada para edição após início do envio.")
    form = await request.form()
    _require_form_token(f"campaign:{campaign.id}:revision:{campaign.revision}", form)
    try:
        current_image = campaign.image_path
        image_mime = campaign.image_mime
        upload = await _read_uploaded_image(
            form.get("replacement_image"), max_bytes=settings.promotion_max_reference_image_bytes
        )
        if upload:
            next_revision = campaign.revision + 1
            current_image = store_campaign_image(
                settings.output_dir,
                campaign_id=campaign.id,
                revision=next_revision,
                image=GeneratedImage(data=upload[0], mime_type=upload[1]),
            )
            image_mime = upload[1]
        update_campaign_preview(
            db,
            campaign.id,
            description=str(form.get("description", "")),
            subject=str(form.get("subject", "")),
            body=str(form.get("body", "")),
            image_path=current_image,
            image_mime=image_mime,
        )
    except CampaignValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(f"/web/promocoes/{campaign.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/web/promocoes/{campaign_id}/regenerate-image")
async def regenerate_campaign_image(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    campaign = db.query(PromotionCampaign).filter_by(id=campaign_id).one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campanha não encontrada.")
    if campaign.status not in {"draft", "generation_failed"}:
        raise HTTPException(status_code=422, detail="Campanha bloqueada para edição após início do envio.")
    form = await request.form()
    _require_form_token(f"campaign:{campaign.id}:revision:{campaign.revision}", form)
    try:
        reference = await _read_uploaded_image(form.get("reference_image"), max_bytes=settings.promotion_max_reference_image_bytes)
        generator_factory = getattr(request.app.state, "promotion_generator_factory", None)
        generator = generator_factory() if callable(generator_factory) else GeminiPromotionGenerator(settings)
        image = generator.generate_image(
            campaign.description,
            reference_image=reference[0] if reference else None,
            reference_mime=reference[1] if reference else None,
        )
        new_path = store_campaign_image(
            settings.output_dir,
            campaign_id=campaign.id,
            revision=campaign.revision + 1,
            image=image,
        )
        update_campaign_preview(
            db,
            campaign.id,
            description=campaign.description,
            subject=campaign.subject,
            body=campaign.body,
            image_path=new_path,
            image_mime=image.mime_type,
        )
    except PromotionGenerationError as exc:
        raise HTTPException(status_code=503, detail=f"Não foi possível gerar a imagem ({exc.code}).") from exc
    except CampaignValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(f"/web/promocoes/{campaign.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/web/promocoes/{campaign_id}/confirm-send")
async def confirm_send_campaign(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    campaign = db.query(PromotionCampaign).filter_by(id=campaign_id).one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campanha não encontrada.")
    _require_form_token(f"campaign:{campaign.id}:revision:{campaign.revision}", form)
    confirmation = str(form.get("confirmation", ""))
    try:
        mailer = SmtpCampaignMailer(settings, settings.output_dir) if campaign_smtp_ready(settings) else None
        campaign = confirm_and_send_campaign(
            db,
            campaign_id=campaign_id,
            confirmation=confirmation,
            send_enabled=mailer is not None,
            mailer=mailer,
        )
    except CampaignSendUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CampaignValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(f"/web/promocoes/{campaign.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/web/promocoes/{campaign_id}/cancel")
async def cancel_promotion_campaign(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    campaign = db.query(PromotionCampaign).filter_by(id=campaign_id).one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campanha não encontrada.")
    form = await request.form()
    _require_form_token(f"campaign:{campaign.id}:revision:{campaign.revision}", form)
    try:
        campaign = cancel_campaign(db, campaign_id=campaign_id)
    except CampaignValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(f"/web/promocoes/{campaign.id}", status_code=status.HTTP_303_SEE_OTHER)
