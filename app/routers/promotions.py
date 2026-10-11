from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from starlette.datastructures import UploadFile
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.db import get_db
from app.models import PromotionCampaign, PromotionRecipient
from app.routers import campaign_contacts, promotion_web_support
from app.services.promotion_campaign_service import (
    CampaignSendUnavailable,
    CampaignValidationError,
    cancel_campaign,
    confirm_and_send_campaign,
    create_campaign_draft,
    eligible_campaign_contacts,
    mark_generation_failure,
    promotion_form_token,
    update_campaign_preview,
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

CampaignContactConsentEvent = campaign_contacts.CampaignContactConsentEvent
Client = campaign_contacts.Client
ClientCampaignContact = campaign_contacts.ClientCampaignContact
_parse_contact_form = campaign_contacts._parse_contact_form
_register_consent_event = campaign_contacts._register_consent_event
create_campaign_contact = campaign_contacts.create_campaign_contact
update_campaign_contact = campaign_contacts.update_campaign_contact
_require_form_token = promotion_web_support._require_form_token


def _templates(request: Request):
    return request.app.state.templates


def _page(request: Request, template: str, context: dict[str, object]):
    base = {"request": request, "title": "Promoções"}
    base.update(context)
    return _templates(request).TemplateResponse(template, base)


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


router.include_router(campaign_contacts.router)


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
