from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import CampaignContactConsentEvent, Client, ClientCampaignContact
from app.routers import promotions
from app.services.promotion_campaign_service import promotion_form_token


@pytest.fixture
def contact_http(db, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Contact routes must not instantiate external transports")

    monkeypatch.setattr(promotions, "GeminiPromotionGenerator", forbidden)
    monkeypatch.setattr(promotions, "SmtpCampaignMailer", forbidden)
    record = Client(razao_social="Cliente sintético de caracterização")
    db.add(record)
    db.commit()
    with TestClient(app) as http:
        yield http, record


def _form(client_id, **changes):
    return {
        "name": "Pessoa sintética",
        "email": "pessoa@example.test",
        "form_token": promotion_form_token(f"client-contacts:{client_id}"),
        **changes,
    }


def _post(http, client_id, form, contact_id=None):
    path = f"/web/clients/{client_id}/campaign-contacts"
    if contact_id is not None:
        path += f"/{contact_id}"
    return http.post(path, data=form, follow_redirects=False)


def _redirect(response, client_id):
    assert response.status_code == 303
    assert response.headers["location"] == f"/web/clients/{client_id}#campaign-contacts"


def test_missing_records_precede_token_validation(contact_http):
    http, record = contact_http
    missing_client = _post(http, record.id + 1000, {})
    missing_contact = _post(http, record.id, {}, 999999)
    assert missing_client.status_code == 404
    assert missing_client.json() == {"detail": "Cliente não encontrado."}
    assert missing_contact.status_code == 404
    assert missing_contact.json() == {"detail": "Contato não encontrado."}


@pytest.mark.parametrize("update", [False, True])
def test_invalid_token_rejects_without_writing(contact_http, db, update):
    http, record = contact_http
    contact_id = None
    if update:
        _redirect(_post(http, record.id, _form(record.id)), record.id)
        contact_id = db.query(ClientCampaignContact).one().id
    response = _post(http, record.id, _form(record.id, form_token="invalid"), contact_id)
    assert response.status_code == 403
    assert response.json() == {
        "detail": "Formulário expirado ou inválido. Atualize a página e tente novamente."
    }
    assert db.query(ClientCampaignContact).count() == int(update)
    assert db.query(CampaignContactConsentEvent).count() == 0


@pytest.mark.parametrize(
    ("changes", "detail"),
    [
        ({"email": "invalid"}, "Informe um endereço de e-mail válido."),
        (
            {"marketing_enabled": "on", "consent_source": "Sintético", "consented_on": "invalid"},
            "Data do consentimento inválida.",
        ),
    ],
)
@pytest.mark.parametrize("update", [False, True])
def test_invalid_form_rolls_back(contact_http, db, changes, detail, update):
    http, record = contact_http
    contact_id = None
    if update:
        _redirect(_post(http, record.id, _form(record.id)), record.id)
        contact_id = db.query(ClientCampaignContact).one().id
    response = _post(http, record.id, _form(record.id, **changes), contact_id)
    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    db.expire_all()
    assert db.query(ClientCampaignContact).count() == int(update)
    if update:
        assert db.query(ClientCampaignContact).one().email == "pessoa@example.test"
    assert db.query(CampaignContactConsentEvent).count() == 0


@pytest.mark.parametrize("update", [False, True])
def test_duplicate_email_preserves_existing_contact_policy(contact_http, db, update):
    http, record = contact_http
    form = _form(record.id)
    _redirect(_post(http, record.id, form), record.id)
    contact_id = None
    if update:
        _redirect(_post(http, record.id, _form(record.id, email="other@example.test")), record.id)
        contact_id = db.query(ClientCampaignContact).filter_by(email="other@example.test").one().id
    response = _post(http, record.id, form, contact_id)
    assert response.status_code == 409
    assert response.json() == {"detail": "Este endereço já está cadastrado para o cliente."}
    assert db.query(ClientCampaignContact).count() == 1 + int(update)
    assert db.query(CampaignContactConsentEvent).count() == 0


def test_contact_starts_without_consent_and_repeated_update_is_idempotent(contact_http, db):
    http, record = contact_http
    _redirect(_post(http, record.id, _form(record.id)), record.id)
    contact = db.query(ClientCampaignContact).one()
    assert contact.marketing_enabled is False
    assert contact.consented_at is None
    assert contact.consent_source == ""
    assert db.query(CampaignContactConsentEvent).count() == 0
    consent = _form(
        record.id, marketing_enabled="on", consent_source="Autorização sintética",
        consented_on="2026-10-07",
    )
    for _ in range(2):
        _redirect(_post(http, record.id, consent, contact.id), record.id)
    assert db.query(CampaignContactConsentEvent).count() == 1
    _redirect(_post(http, record.id, {**consent, "reauthorize_consent": "on"}, contact.id), record.id)
    events = db.query(CampaignContactConsentEvent).order_by(CampaignContactConsentEvent.id).all()
    assert [event.event_type for event in events] == ["opt_in", "opt_in"]
    assert [event.email_snapshot for event in events] == ["pessoa@example.test"] * 2
    assert events[0].event_key != events[1].event_key
    _redirect(_post(http, record.id, _form(record.id, email="changed@example.test"), contact.id), record.id)
    db.refresh(contact)
    assert contact.marketing_enabled is False
    assert contact.email_normalized == "changed@example.test"
    assert contact.consent_source == "Autorização sintética"
    assert contact.consented_at.date().isoformat() == "2026-10-07"
    events = db.query(CampaignContactConsentEvent).order_by(CampaignContactConsentEvent.id).all()
    assert [event.event_type for event in events] == ["opt_in", "opt_in", "opt_out"]
    assert [event.email_snapshot for event in events] == ["pessoa@example.test"] * 3
    assert events[-1].source == "Revogado no cadastro local"
