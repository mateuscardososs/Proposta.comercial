from __future__ import annotations

import hmac
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.assistant.whatsapp_webhook import (
    WHATSAPP_MAILBOX,
    WHATSAPP_PROVIDER,
    WHATSAPP_WEBHOOK_PATH,
    InvalidWhatsAppPayload,
    parse_meta_messages,
    verify_meta_signature,
)
from app.db import get_db
from app.models import InboxEmail

router = APIRouter(tags=["whatsapp-webhook"])


async def _read_limited_body(request: Request, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(
                status_code=413, detail="Payload do webhook acima do limite permitido."
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _settings(request: Request):
    return request.app.state.settings


@router.get(WHATSAPP_WEBHOOK_PATH, include_in_schema=False)
def verify_webhook(request: Request) -> Response:
    settings = _settings(request)
    if not settings.whatsapp_webhook_enabled:
        raise HTTPException(status_code=404, detail="Webhook desativado.")
    expected = settings.whatsapp_verify_token.get_secret_value()
    supplied = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")
    if (
        request.query_params.get("hub.mode") != "subscribe"
        or not expected
        or not supplied
        or not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
        or not challenge
        or len(challenge) > 1024
        or any(ord(char) < 32 for char in challenge)
    ):
        raise HTTPException(status_code=403, detail="Verificação do webhook recusada.")
    return Response(content=challenge, media_type="text/plain")


@router.post(WHATSAPP_WEBHOOK_PATH, include_in_schema=False)
async def receive_webhook(
    request: Request,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, str]:
    settings = _settings(request)
    if not settings.whatsapp_webhook_enabled:
        raise HTTPException(status_code=404, detail="Webhook desativado.")
    secret = settings.whatsapp_app_secret.get_secret_value()
    if not secret:
        raise HTTPException(
            status_code=503, detail="Webhook sem segredo de assinatura configurado."
        )
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise HTTPException(
            status_code=415, detail="Tipo de conteúdo do webhook inválido."
        )
    raw_body = await _read_limited_body(
        request, settings.whatsapp_webhook_max_payload_bytes
    )
    if not verify_meta_signature(
        raw_body, request.headers.get("x-hub-signature-256"), secret
    ):
        raise HTTPException(status_code=401, detail="Assinatura do webhook inválida.")
    try:
        incoming = parse_meta_messages(
            raw_body,
            preview_chars=settings.whatsapp_message_preview_chars,
            max_messages=settings.whatsapp_webhook_max_messages,
            timezone_name=settings.assistant_timezone,
        )
    except InvalidWhatsAppPayload:
        raise HTTPException(
            status_code=400, detail="Payload do webhook inválido."
        ) from None

    try:
        for message in incoming:
            try:
                with db.begin_nested():
                    db.add(
                        InboxEmail(
                            provider=WHATSAPP_PROVIDER,
                            mailbox_key=WHATSAPP_MAILBOX,
                            reference=message.message_id,
                            thread_reference="",
                            sender=f"WhatsApp: {message.sender}"[:500],
                            subject="Mensagem recebida pelo WhatsApp",
                            received_at=message.received_at,
                            seen=False,
                            awaiting_reply="unknown",
                            sent_coverage=False,
                            summary=message.preview,
                            category="other_review",
                            confidence_band="low",
                            destination="review",
                            classification_reason=(
                                "Mensagem recebida pela API oficial; revisão humana necessária."
                            ),
                            priority="normal",
                            extracted_fields={},
                            review_status="pending",
                            last_seen_at=datetime.now(timezone.utc)
                            .astimezone(ZoneInfo(settings.assistant_timezone))
                            .replace(tzinfo=None),
                        )
                    )
                    db.flush()
            except IntegrityError:
                # Only the stable origin constraint means an already-accepted Meta retry.
                existing = (
                    db.query(InboxEmail.id)
                    .filter_by(
                        provider=WHATSAPP_PROVIDER,
                        mailbox_key=WHATSAPP_MAILBOX,
                        reference=message.message_id,
                    )
                    .one_or_none()
                )
                if existing is None:
                    raise
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        # Do not emit exception text or SQL parameters; they may contain message content.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Não foi possível registrar a mensagem na fila.",
        ) from None
    except Exception:  # noqa: BLE001 - suppress provider/database values that may contain message text
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Não foi possível registrar a mensagem na fila.",
        ) from None
    return {"status": "ok"}
