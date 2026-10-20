from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_SIGNATURE_RE = re.compile(r"sha256=[0-9a-f]{64}\Z")
WHATSAPP_PROVIDER = "whatsapp_cloud"
WHATSAPP_MAILBOX = "inbound"
WHATSAPP_WEBHOOK_PATH = "/webhooks/whatsapp"


class InvalidWhatsAppPayload(ValueError):
    """A sanitized marker for an invalid Meta webhook payload."""


@dataclass(frozen=True)
class IncomingWhatsAppMessage:
    message_id: str
    sender: str
    received_at: datetime
    preview: str


def verify_meta_signature(
    raw_body: bytes, signature: str | None, app_secret: str
) -> bool:
    if (
        not signature
        or len(signature) != 71
        or not app_secret
        or not _SIGNATURE_RE.fullmatch(signature)
    ):
        return False
    expected = (
        "sha256="
        + hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(expected, signature)


def parse_meta_messages(
    raw_body: bytes,
    *,
    preview_chars: int = 400,
    max_messages: int = 100,
    timezone_name: str = "America/Recife",
) -> list[IncomingWhatsAppMessage]:
    """Extract bounded inbox projections; never retain the original webhook JSON."""
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InvalidWhatsAppPayload from None
    if (
        not isinstance(payload, dict)
        or payload.get("object") != "whatsapp_business_account"
    ):
        raise InvalidWhatsAppPayload
    entries = payload.get("entry")
    if not isinstance(entries, list):
        raise InvalidWhatsAppPayload

    messages: list[IncomingWhatsAppMessage] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("changes"), list):
            raise InvalidWhatsAppPayload
        for change in entry["changes"]:
            if not isinstance(change, dict):
                raise InvalidWhatsAppPayload
            if change.get("field") != "messages":
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                raise InvalidWhatsAppPayload
            if value.get("messaging_product") != "whatsapp":
                raise InvalidWhatsAppPayload
            # Delivery/status events can use the same field and contain no messages.
            event_messages = value.get("messages", [])
            if event_messages is None:
                continue
            if not isinstance(event_messages, list):
                raise InvalidWhatsAppPayload
            if not event_messages:
                continue
            metadata = value.get("metadata")
            phone_number_id = (
                metadata.get("phone_number_id") if isinstance(metadata, dict) else None
            )
            if (
                not isinstance(phone_number_id, str)
                or not phone_number_id
                or len(phone_number_id) > 160
            ):
                raise InvalidWhatsAppPayload
            for message in event_messages:
                if not isinstance(message, dict):
                    raise InvalidWhatsAppPayload
                message_id = message.get("id")
                sender = message.get("from")
                timestamp = message.get("timestamp")
                message_type = message.get("type")
                if (
                    not isinstance(message_id, str)
                    or not message_id
                    or len(message_id) > 160
                    or not isinstance(sender, str)
                    or not sender
                    or len(sender) > 500
                    or not isinstance(timestamp, str)
                    or not timestamp.isdigit()
                    or not isinstance(message_type, str)
                    or not message_type
                    or len(message_type) > 40
                ):
                    raise InvalidWhatsAppPayload
                try:
                    received_at = (
                        datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
                        .astimezone(ZoneInfo(timezone_name))
                        .replace(tzinfo=None)
                    )
                except (OverflowError, OSError, ValueError):
                    raise InvalidWhatsAppPayload from None
                if message_type == "text":
                    text = message.get("text")
                    body_text = text.get("body") if isinstance(text, dict) else None
                    if not isinstance(body_text, str):
                        raise InvalidWhatsAppPayload
                    preview = body_text.strip()[:preview_chars]
                else:
                    # Media is not fetched or retained; the human review queue gets only its type.
                    preview = f"Mensagem recebida pelo WhatsApp ({message_type}); conteúdo não importado."
                messages.append(
                    IncomingWhatsAppMessage(
                        message_id=message_id,
                        sender=sender,
                        received_at=received_at,
                        preview=preview or "Mensagem sem texto.",
                    )
                )
                if len(messages) > max_messages:
                    raise InvalidWhatsAppPayload
    return messages
