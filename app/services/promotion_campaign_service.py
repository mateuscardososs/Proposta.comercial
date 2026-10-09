from __future__ import annotations

import re
import hmac
import secrets
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models import (
    CampaignContactConsentEvent,
    ClientCampaignContact,
    PromotionCampaign,
    PromotionCampaignEvent,
    PromotionRecipient,
)

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+$")
_FORM_TOKEN_SECRET = secrets.token_bytes(32)


def promotion_form_token(scope: str) -> str:
    return hmac.new(_FORM_TOKEN_SECRET, scope.encode("utf-8"), "sha256").hexdigest()


def verify_promotion_form_token(scope: str, token: str) -> bool:
    return hmac.compare_digest(promotion_form_token(scope), token)


class CampaignSendUnavailable(RuntimeError):
    pass


class CampaignValidationError(ValueError):
    pass


class CampaignMailer(Protocol):
    def send(
        self,
        *,
        recipient: PromotionRecipient,
        subject: str,
        body: str,
        image_path: str,
        message_id: str,
    ) -> str: ...


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def is_valid_campaign_email(value: str) -> bool:
    normalized = normalize_email(value)
    parsed = parseaddr(value.strip())[1]
    return bool(
        normalized
        and parsed == value.strip()
        and _EMAIL_RE.fullmatch(normalized)
        and ".." not in normalized
    )


def eligible_campaign_contacts(db: Session) -> list[ClientCampaignContact]:
    contacts = db.scalars(
        select(ClientCampaignContact)
        .options(joinedload(ClientCampaignContact.client))
        .where(
            ClientCampaignContact.active.is_(True),
            ClientCampaignContact.marketing_enabled.is_(True),
            ClientCampaignContact.consent_source != "",
            ClientCampaignContact.consented_at.is_not(None),
        )
        .order_by(ClientCampaignContact.client_id, ClientCampaignContact.name, ClientCampaignContact.email)
    ).unique().all()
    contact_ids = [contact.id for contact in contacts]
    latest_consent: dict[int, CampaignContactConsentEvent] = {}
    if contact_ids:
        for event in db.scalars(
            select(CampaignContactConsentEvent)
            .where(CampaignContactConsentEvent.contact_id.in_(contact_ids))
            .order_by(CampaignContactConsentEvent.created_at.desc(), CampaignContactConsentEvent.id.desc())
        ).all():
            latest_consent.setdefault(event.contact_id, event)
    return [
        contact
        for contact in contacts
        if is_valid_campaign_email(contact.email)
        and normalize_email(contact.email) == contact.email_normalized
        and latest_consent.get(contact.id) is not None
        and latest_consent[contact.id].event_type == "opt_in"
        and latest_consent[contact.id].email_snapshot == contact.email_normalized
    ]


def eligible_contacts_by_ids(db: Session, ids: list[int]) -> list[ClientCampaignContact]:
    wanted = set(ids)
    if not wanted:
        return []
    return [contact for contact in eligible_campaign_contacts(db) if contact.id in wanted]


def _record_event(
    db: Session,
    *,
    campaign: PromotionCampaign,
    event_key: str,
    event_type: str,
    details: dict[str, object],
) -> None:
    if db.query(PromotionCampaignEvent.id).filter_by(event_key=event_key).first():
        return
    db.add(
        PromotionCampaignEvent(
            campaign_id=campaign.id,
            event_key=event_key,
            event_type=event_type,
            revision=campaign.revision,
            details=details,
        )
    )


def create_campaign_draft(
    db: Session,
    *,
    request_key: str,
    description: str,
    subject: str,
    body: str,
    image_path: str,
    selected_contact_ids: list[int],
    image_mime: str = "image/png",
    status: str = "draft",
) -> PromotionCampaign:
    request_key = request_key.strip()
    description = description.strip()
    if not request_key:
        raise CampaignValidationError("Identificador da solicitação ausente.")
    if not description:
        raise CampaignValidationError("Descreva a campanha antes de gerar a prévia.")
    existing = db.query(PromotionCampaign).filter_by(request_key=request_key).first()
    if existing:
        return existing

    contacts = eligible_contacts_by_ids(db, selected_contact_ids)
    if len(contacts) != len(set(selected_contact_ids)):
        raise CampaignValidationError("Há contatos selecionados sem autorização válida para campanhas.")
    normalized_emails = [normalize_email(contact.email) for contact in contacts]
    if len(normalized_emails) != len(set(normalized_emails)):
        raise CampaignValidationError(
            "O mesmo endereço aparece em mais de um cliente selecionado; revise os contatos antes de continuar."
        )

    campaign = PromotionCampaign(
        request_key=request_key,
        description=description,
        subject=subject.strip()[:255],
        body=body.strip(),
        image_path=image_path,
        image_mime=image_mime,
        status=status,
        revision=1,
    )
    db.add(campaign)
    try:
        db.flush()
        for contact in contacts:
            normalized = normalize_email(contact.email)
            db.add(
                PromotionRecipient(
                    campaign_id=campaign.id,
                    contact_id=contact.id,
                    client_id=contact.client_id,
                    client_name_snapshot=contact.client.razao_social,
                    contact_name_snapshot=contact.name,
                    email_snapshot=contact.email,
                    email_normalized=normalized,
                    status="pending",
                )
            )
        _record_event(
            db,
            campaign=campaign,
            event_key=f"campaign:{request_key}:created",
            event_type="draft_created",
            details={"recipient_count": len(contacts)},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(PromotionCampaign).filter_by(request_key=request_key).first()
        if existing:
            return existing
        raise
    db.refresh(campaign)
    return campaign


def mark_generation_failure(db: Session, *, campaign_id: int, code: str) -> PromotionCampaign:
    campaign = db.query(PromotionCampaign).filter_by(id=campaign_id).with_for_update().one()
    campaign.status = "generation_failed"
    campaign.generation_error = re.sub(r"[^a-zA-Z0-9_-]", "", code)[:80]
    _record_event(
        db,
        campaign=campaign,
        event_key=f"campaign:{campaign.id}:generation-failed:revision:{campaign.revision}",
        event_type="generation_failed",
        details={"error_code": campaign.generation_error},
    )
    db.commit()
    return campaign


def update_campaign_preview(
    db: Session,
    campaign_id: int,
    *,
    description: str,
    subject: str,
    body: str,
    image_path: str,
    image_mime: str | None = None,
) -> PromotionCampaign:
    campaign = db.query(PromotionCampaign).filter_by(id=campaign_id).with_for_update().one_or_none()
    if campaign is None:
        raise CampaignValidationError("Campanha não encontrada.")
    if campaign.status not in {"draft", "generating", "generation_failed"}:
        raise CampaignValidationError("Esta campanha não pode mais ser editada após iniciar o envio.")
    values = {
        "description": description.strip(),
        "subject": subject.strip()[:255],
        "body": body.strip(),
        "image_path": image_path,
    }
    if not values["description"]:
        raise CampaignValidationError("A descrição da campanha é obrigatória para revisão.")
    changed = any(getattr(campaign, key) != value for key, value in values.items())
    changed = changed or (image_mime is not None and campaign.image_mime != image_mime)
    if changed:
        old_revision = campaign.revision
        previous_snapshot = {
            "description": campaign.description,
            "subject": campaign.subject,
            "body": campaign.body,
            "image_path": campaign.image_path,
            "image_mime": campaign.image_mime,
        }
        for key, value in values.items():
            setattr(campaign, key, value)
        if image_mime is not None:
            campaign.image_mime = image_mime
        campaign.revision += 1
        campaign.confirmed_revision = None
        campaign.confirmed_at = None
        campaign.status = "draft"
        _record_event(
            db,
            campaign=campaign,
            event_key=f"campaign:{campaign.id}:revision:{campaign.revision}:edited",
            event_type="preview_edited",
            details={
                "previous_revision": old_revision,
                "revision": campaign.revision,
                "previous_preview": previous_snapshot,
            },
        )
        db.commit()
    return campaign


def cancel_campaign(db: Session, *, campaign_id: int) -> PromotionCampaign:
    campaign = db.query(PromotionCampaign).filter_by(id=campaign_id).with_for_update().one_or_none()
    if campaign is None:
        raise CampaignValidationError("Campanha não encontrada.")
    if campaign.status in {"sending", "sent", "partial"}:
        raise CampaignValidationError("O envio já começou; esta campanha não pode ser cancelada por completo.")
    if campaign.status != "cancelled":
        campaign.status = "cancelled"
        for recipient in campaign.recipients:
            if recipient.status == "pending":
                recipient.status = "cancelled"
        _record_event(
            db,
            campaign=campaign,
            event_key=f"campaign:{campaign.id}:cancelled",
            event_type="cancelled",
            details={"recipient_count": len(campaign.recipients)},
        )
        db.commit()
    return campaign


def confirm_and_send_campaign(
    db: Session,
    *,
    campaign_id: int,
    confirmation: str,
    send_enabled: bool,
    mailer: CampaignMailer,
) -> PromotionCampaign:
    if not send_enabled:
        raise CampaignSendUnavailable(
            "Envio indisponível: configure separadamente o provedor SMTP e as credenciais de saída."
        )
    campaign = (
        db.query(PromotionCampaign)
        .options(joinedload(PromotionCampaign.recipients).joinedload(PromotionRecipient.contact))
        .filter_by(id=campaign_id)
        .with_for_update()
        .one_or_none()
    )
    if campaign is None:
        raise CampaignValidationError("Campanha não encontrada.")
    if campaign.status == "sent":
        return campaign
    if campaign.status == "cancelled":
        raise CampaignValidationError("Esta campanha foi cancelada.")
    if campaign.confirmed_revision == campaign.revision and campaign.status in {"sending", "partial"}:
        # A previous request may have been interrupted after SMTP accepted a message.
        # Never blindly send again; sending rows become unknown and require review.
        for recipient in campaign.recipients:
            if recipient.status == "sending":
                recipient.status = "unknown"
                recipient.error_code = "interrupted_after_send_started"
        if any(recipient.status == "unknown" for recipient in campaign.recipients):
            campaign.status = "partial"
            db.commit()
        return campaign
    if confirmation.strip().casefold() != "confirmar":
        raise CampaignValidationError("Confirmação explícita não reconhecida.")
    if campaign.status not in {"draft", "generation_failed", "partial"}:
        raise CampaignValidationError("Estado da campanha não permite confirmação.")
    if not campaign.subject or not campaign.body or not campaign.image_path:
        raise CampaignValidationError("A prévia precisa estar completa antes da confirmação.")
    if not campaign.recipients:
        raise CampaignValidationError("Selecione ao menos um contato autorizado.")

    if campaign.confirmed_revision != campaign.revision:
        campaign.confirmed_revision = campaign.revision
        campaign.confirmed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        _record_event(
            db,
            campaign=campaign,
            event_key=f"campaign:{campaign.id}:confirmed:revision:{campaign.revision}",
            event_type="confirmed",
            details={
                "recipient_count": len(campaign.recipients),
                "revision": campaign.revision,
                "description": campaign.description,
                "subject": campaign.subject,
                "body": campaign.body,
                "image_path": campaign.image_path,
                "image_mime": campaign.image_mime,
            },
        )
    campaign.status = "sending"
    db.commit()

    for recipient in campaign.recipients:
        if recipient.status != "pending":
            continue
        contact = recipient.contact
        latest_consent = (
            db.query(CampaignContactConsentEvent)
            .filter_by(contact_id=contact.id if contact else -1)
            .order_by(CampaignContactConsentEvent.created_at.desc(), CampaignContactConsentEvent.id.desc())
            .first()
        )
        if (
            contact is None
            or not contact.active
            or not contact.marketing_enabled
            or not contact.consent_source
            or not contact.consented_at
            or latest_consent is None
            or latest_consent.event_type != "opt_in"
            or latest_consent.email_snapshot != contact.email_normalized
            or not is_valid_campaign_email(contact.email)
            or normalize_email(contact.email) != recipient.email_normalized
        ):
            recipient.status = "suppressed"
            recipient.error_code = "contact_consent_or_address_changed"
            db.commit()
            continue
        recipient.status = "sending"
        recipient.attempts += 1
        recipient.last_attempt_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        message_id = f"<promotion-{campaign.id}-{recipient.id}@adbalancas.local>"
        try:
            provider_id = mailer.send(
                recipient=recipient,
                subject=campaign.subject,
                body=campaign.body,
                image_path=campaign.image_path,
                message_id=message_id,
            )
        except Exception as exc:  # Do not log or expose provider payload/credentials.
            recipient.status = "unknown"
            recipient.error_code = type(exc).__name__[:80]
            db.commit()
            continue
        recipient.status = "sent"
        recipient.provider_message_id = str(provider_id or message_id)[:255]
        recipient.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()

    if campaign.recipients and all(item.status == "sent" for item in campaign.recipients):
        campaign.status = "sent"
    else:
        campaign.status = "partial"
    _record_event(
        db,
        campaign=campaign,
        event_key=f"campaign:{campaign.id}:delivery:revision:{campaign.revision}",
        event_type="delivery_finished",
        details={
            "sent": sum(item.status == "sent" for item in campaign.recipients),
            "failed_or_review": sum(item.status in {"unknown", "suppressed"} for item in campaign.recipients),
        },
    )
    db.commit()
    return campaign
