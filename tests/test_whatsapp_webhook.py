from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.db import SessionLocal, get_db
from app.main import app as main_app
from app.models import Client, EmailActionDraft, InboxEmail, Lancamento, Task
from app.routers.whatsapp_webhook import router
from app.security.auth import configure_authentication

APP_SECRET = "synthetic-meta-app-secret"
VERIFY_TOKEN = "synthetic-webhook-verify-token"


def _settings(*, enabled: bool = True) -> Settings:
    return Settings(
        _env_file=None,
        auth_enabled=True,
        auth_session_secret=SecretStr("synthetic-session-secret-that-is-long-enough"),
        whatsapp_webhook_enabled=enabled,
        whatsapp_app_secret=SecretStr(APP_SECRET if enabled else ""),
        whatsapp_verify_token=SecretStr(VERIFY_TOKEN if enabled else ""),
    )


def _test_app(db, *, enabled: bool = True) -> FastAPI:
    app = FastAPI()
    app.state.settings = _settings(enabled=enabled)
    app.state.auth_login_window_seconds = 900
    configure_authentication(app, app.state.settings, session_factory=SessionLocal)
    app.include_router(router)
    app.add_api_route("/api/protected-test", lambda: {"ok": True})
    app.dependency_overrides[get_db] = lambda: db
    return app


def _payload(*, body: str = "Olá, preciso de ajuda com minha balança.") -> bytes:
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "synthetic-waba",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"phone_number_id": "synthetic-phone-id"},
                                "contacts": [
                                    {
                                        "wa_id": "5511999990000",
                                        "profile": {"name": "Synthetic"},
                                    }
                                ],
                                "messages": [
                                    {
                                        "from": "5511999990000",
                                        "id": "wamid.synthetic-stable-id",
                                        "timestamp": "1792400000",
                                        "type": "text",
                                        "text": {"body": body},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        },
        separators=(",", ":"),
    ).encode()


def _signature(body: bytes) -> str:
    digest = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_meta_challenge_returns_exact_challenge_only_for_configured_token(db):
    with TestClient(_test_app(db)) as client:
        valid = client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "synthetic-challenge",
            },
        )
        invalid = client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "synthetic-challenge",
            },
        )

    assert valid.status_code == 200
    assert valid.text == "synthetic-challenge"
    assert invalid.status_code == 403


def test_signed_message_is_queued_for_review_without_operational_side_effects(
    db, caplog
):
    body = _payload()
    with TestClient(_test_app(db)) as client:
        response = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": _signature(body),
            },
        )

    assert response.status_code == 200
    message = db.query(InboxEmail).one()
    assert message.provider == "whatsapp_cloud"
    assert message.reference == "wamid.synthetic-stable-id"
    assert message.received_at == datetime.fromtimestamp(
        1792400000, tz=timezone.utc
    ).astimezone(ZoneInfo("America/Recife")).replace(tzinfo=None)
    assert message.category == "other_review"
    assert message.confidence_band == "low"
    assert message.destination == "review"
    assert message.review_status == "pending"
    assert "Olá, preciso de ajuda" in message.summary
    assert db.query(Task).count() == 0
    assert db.query(EmailActionDraft).count() == 0
    assert db.query(Lancamento).count() == 0
    assert db.query(Client).count() == 0
    assert APP_SECRET not in caplog.text
    assert "Olá, preciso de ajuda" not in caplog.text


def test_signature_is_over_raw_body_and_invalid_signature_is_rejected(db):
    body = _payload()
    with TestClient(_test_app(db)) as client:
        response = client.post(
            "/webhooks/whatsapp",
            content=body + b" ",
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": _signature(body),
            },
        )

    assert response.status_code == 401
    assert db.query(InboxEmail).count() == 0


def test_retry_with_same_meta_message_id_is_idempotent(db):
    body = _payload()
    with TestClient(_test_app(db)) as client:
        first = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": _signature(body),
            },
        )
        retry = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": _signature(body),
            },
        )

    assert first.status_code == retry.status_code == 200
    assert db.query(InboxEmail).count() == 1
    assert db.query(Task).count() == 0


def test_malformed_payload_is_rejected_without_storage(db):
    body = b'{"object":'
    with TestClient(_test_app(db)) as client:
        response = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": _signature(body),
            },
        )

    assert response.status_code == 400
    assert db.query(InboxEmail).count() == 0


def test_disabled_integration_is_not_publicly_usable_and_other_routes_remain_protected(
    db,
):
    with TestClient(_test_app(db, enabled=False)) as client:
        disabled = client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "x",
            },
        )
        protected = client.get("/api/protected-test")

    assert disabled.status_code == 404
    assert protected.status_code == 401


def test_whatsapp_is_disabled_in_default_configuration():
    assert Settings(_env_file=None).whatsapp_webhook_enabled is False


def test_text_preview_is_bounded_before_storage(db):
    body = _payload(body="x" * 600)
    with TestClient(_test_app(db)) as client:
        response = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": _signature(body),
            },
        )

    assert response.status_code == 200
    assert len(db.query(InboxEmail).one().summary) == 400


def test_whatsapp_message_is_visible_in_existing_review_queue(db):
    db.add(
        InboxEmail(
            provider="whatsapp_cloud",
            mailbox_key="inbound",
            reference="wamid.queue-visible",
            thread_reference="synthetic-sender",
            sender="WhatsApp: synthetic-sender",
            subject="Mensagem recebida pelo WhatsApp",
            received_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
            seen=False,
            awaiting_reply="unknown",
            sent_coverage=False,
            summary="Mensagem sintética para revisão",
            category="other_review",
            confidence_band="low",
            destination="review",
            classification_reason="Revisar",
            priority="normal",
            extracted_fields={},
            review_status="pending",
            last_seen_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
        )
    )
    db.commit()

    with TestClient(main_app) as client:
        response = client.get("/web/mensagens")

    assert response.status_code == 200
    assert "WhatsApp recebido" in response.text
    assert "Mensagem sintética para revisão" in response.text


def test_main_application_registers_only_exact_webhook_endpoint():
    paths = {
        (route.path, method)
        for route in main_app.routes
        for method in getattr(route, "methods", set())
    }

    assert ("/webhooks/whatsapp", "GET") in paths
    assert ("/webhooks/whatsapp", "POST") in paths
