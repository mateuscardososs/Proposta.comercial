from __future__ import annotations

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    CampaignContactConsentEvent,
    Client,
    ClientCampaignContact,
    PromotionCampaign,
    PromotionCampaignEvent,
    PromotionRecipient,
)
from app.services.promotion_campaign_service import (
    CampaignSendUnavailable,
    cancel_campaign,
    confirm_and_send_campaign,
    create_campaign_draft,
    eligible_campaign_contacts,
    promotion_form_token,
    update_campaign_preview,
)
from app.services.promotion_generation_service import GeneratedImage, PromotionCopy, PromotionGenerationError


def _contact(db, *, email="contato@example.test", enabled=False, source="", consented_at=None):
    client = Client(razao_social="Cliente Sintético")
    db.add(client)
    db.flush()
    contact = ClientCampaignContact(
        client_id=client.id,
        name="Contato Sintético",
        email=email,
        email_normalized=email.casefold(),
        marketing_enabled=enabled,
        consent_source=source,
        consented_at=consented_at,
    )
    db.add(contact)
    db.commit()
    if enabled:
        db.add(
            CampaignContactConsentEvent(
                contact_id=contact.id,
                event_key=f"test-opt-in-{contact.id}",
                event_type="opt_in",
                email_snapshot=email.casefold(),
                source=source,
                occurred_at=consented_at,
            )
        )
        db.commit()
    return contact


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, *, recipient, subject, body, image_path, message_id):
        self.sent.append((recipient.email_snapshot, subject, message_id))
        return "synthetic-accepted"


def test_existing_contacts_are_not_eligible_without_explicit_consent(db):
    legacy = _contact(db, enabled=False)
    consented = _contact(
        db,
        email="ok@example.test",
        enabled=True,
        source="Formulário de consentimento",
        consented_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )

    eligible = eligible_campaign_contacts(db)

    assert [item.id for item in eligible] == [consented.id]
    assert legacy.id not in {item.id for item in eligible}


@pytest.mark.parametrize("bad_email", ["", "sem-arroba", "a@b", "a..b@example.test"])
def test_invalid_email_is_never_campaign_eligible(db, bad_email):
    contact = _contact(
        db,
        email=bad_email,
        enabled=True,
        source="Consentimento sintético",
        consented_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )

    assert contact.id not in {item.id for item in eligible_campaign_contacts(db)}


def test_campaign_draft_is_idempotent_and_snapshots_only_eligible_recipients(db, tmp_path):
    contact = _contact(
        db,
        enabled=True,
        source="Autorização sintética",
        consented_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )
    args = dict(
        request_key="draft-request-001",
        description="Convite para conhecer a manutenção de balanças.",
        subject="Condições especiais para sua equipe",
        body="Entre em contato e agende uma conversa.",
        image_path="promotions/campaign-1/image-v1.png",
        selected_contact_ids=[contact.id],
    )

    first = create_campaign_draft(db, **args)
    again = create_campaign_draft(db, **args)

    assert first.id == again.id
    assert db.query(PromotionCampaign).count() == 1
    assert db.query(PromotionRecipient).count() == 1
    assert db.query(PromotionRecipient).one().email_snapshot == contact.email


def test_editing_preview_invalidates_old_confirmation(db):
    contact = _contact(
        db,
        enabled=True,
        source="Consentimento sintético",
        consented_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )
    campaign = create_campaign_draft(
        db,
        request_key="edit-draft-001",
        description="Texto inicial",
        subject="Assunto inicial",
        body="Corpo inicial",
        image_path="promotions/1/image-v1.png",
        selected_contact_ids=[contact.id],
    )
    campaign.confirmed_revision = campaign.revision
    db.commit()

    updated = update_campaign_preview(
        db,
        campaign.id,
        description="Texto corrigido",
        subject="Assunto revisado",
        body="Corpo revisado",
        image_path=campaign.image_path,
    )

    assert updated.revision == 2
    assert updated.confirmed_revision is None


def test_send_is_disabled_without_outbound_provider_and_does_not_call_mailer(db):
    contact = _contact(
        db,
        enabled=True,
        source="Consentimento sintético",
        consented_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )
    campaign = create_campaign_draft(
        db,
        request_key="disabled-send-001",
        description="Campanha sintética",
        subject="Condições especiais",
        body="Fale conosco e agende.",
        image_path="promotions/1/image-v1.png",
        selected_contact_ids=[contact.id],
    )
    mailer = FakeMailer()

    with pytest.raises(CampaignSendUnavailable):
        confirm_and_send_campaign(
            db,
            campaign_id=campaign.id,
            confirmation="CONFIRMAR",
            send_enabled=False,
            mailer=mailer,
        )

    assert mailer.sent == []
    assert db.query(PromotionRecipient).one().status == "pending"


def test_explicit_confirmation_sends_once_and_retry_does_not_duplicate(db):
    contact = _contact(
        db,
        enabled=True,
        source="Consentimento sintético",
        consented_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )
    campaign = create_campaign_draft(
        db,
        request_key="send-once-001",
        description="Campanha sintética",
        subject="Condições especiais",
        body="Entre em contato e agende.",
        image_path="promotions/1/image-v1.png",
        selected_contact_ids=[contact.id],
    )
    mailer = FakeMailer()

    first = confirm_and_send_campaign(
        db,
        campaign_id=campaign.id,
        confirmation="CONFIRMAR",
        send_enabled=True,
        mailer=mailer,
    )
    retry = confirm_and_send_campaign(
        db,
        campaign_id=campaign.id,
        confirmation="CONFIRMAR",
        send_enabled=True,
        mailer=mailer,
    )

    assert first.status == retry.status == "sent"
    assert len(mailer.sent) == 1
    assert db.query(PromotionRecipient).one().status == "sent"
    assert db.query(PromotionRecipient).one().provider_message_id == "synthetic-accepted"


def test_confirmation_is_required_even_when_transport_is_ready(db):
    contact = _contact(
        db,
        enabled=True,
        source="Consentimento sintético",
        consented_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )
    campaign = create_campaign_draft(
        db,
        request_key="wrong-confirmation-001",
        description="Campanha sintética",
        subject="Condições especiais",
        body="Entre em contato e agende.",
        image_path="promotions/1/image-v1.png",
        selected_contact_ids=[contact.id],
    )
    mailer = FakeMailer()

    with pytest.raises(ValueError, match="Confirmação explícita"):
        confirm_and_send_campaign(
            db,
            campaign_id=campaign.id,
            confirmation="talvez",
            send_enabled=True,
            mailer=mailer,
        )

    assert mailer.sent == []
    assert db.query(PromotionRecipient).one().status == "pending"


def test_revoked_contact_is_suppressed_at_send_after_recipient_snapshot(db):
    contact = _contact(
        db,
        enabled=True,
        source="Consentimento sintético",
        consented_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )
    campaign = create_campaign_draft(
        db,
        request_key="revoked-before-send-001",
        description="Campanha sintética",
        subject="Assunto",
        body="Convite para contato.",
        image_path="promotions/1/image-v1.png",
        selected_contact_ids=[contact.id],
    )
    db.add(
        CampaignContactConsentEvent(
            contact_id=contact.id,
            event_key="test-opt-out-before-send",
            event_type="opt_out",
            email_snapshot=contact.email_normalized,
            source="Pedido de não receber",
            occurred_at=datetime(2026, 10, 7, 12),
        )
    )
    contact.marketing_enabled = False
    db.commit()
    mailer = FakeMailer()

    result = confirm_and_send_campaign(
        db,
        campaign_id=campaign.id,
        confirmation="CONFIRMAR",
        send_enabled=True,
        mailer=mailer,
    )

    assert result.status == "partial"
    assert mailer.sent == []
    assert db.query(PromotionRecipient).one().status == "suppressed"


def test_cancelled_campaign_never_sends(db):
    contact = _contact(
        db,
        enabled=True,
        source="Consentimento sintético",
        consented_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )
    campaign = create_campaign_draft(
        db,
        request_key="cancel-draft-001",
        description="Campanha sintética",
        subject="Assunto",
        body="Corpo",
        image_path="promotions/1/image-v1.png",
        selected_contact_ids=[contact.id],
    )
    mailer = FakeMailer()

    cancel_campaign(db, campaign_id=campaign.id)

    assert mailer.sent == []
    assert db.query(PromotionCampaign).one().status == "cancelled"
    assert db.query(PromotionRecipient).one().status == "cancelled"


def test_promotions_page_has_optional_description_and_discloses_disabled_send():
    with TestClient(app) as client:
        response = client.get("/web/promocoes")

    assert response.status_code == 200
    assert 'name="description"' in response.text
    assert "período" in response.text.casefold()
    assert "envio" in response.text.casefold()


def test_promotion_detail_renders_editable_preview_and_sends_are_disabled(db, monkeypatch):
    import app.routers.promotions as promotions_router

    contact = _contact(
        db,
        enabled=True,
        source="Consentimento sintético",
        consented_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )
    campaign = create_campaign_draft(
        db,
        request_key="detail-preview-001",
        description="Campanha sintética",
        subject="Assunto revisável",
        body="Texto revisável",
        image_path="promotions/1/image-v1.png",
        selected_contact_ids=[contact.id],
    )
    monkeypatch.setattr(promotions_router, "campaign_smtp_ready", lambda _settings: False)

    with TestClient(app) as client:
        response = client.get(f"/web/promocoes/{campaign.id}")

    assert response.status_code == 200
    assert "Assunto revisável" in response.text
    assert "Texto revisável" in response.text
    assert "image-v1.png" in response.text
    assert "Envio desativado" in response.text
    assert 'name="form_token"' in response.text


def test_navigation_exposes_promotions_tab():
    with TestClient(app) as client:
        response = client.get("/web/promocoes")

    assert response.status_code == 200
    assert 'href="/web/promocoes"' in response.text
    assert "Promoções" in response.text


def test_generation_post_requires_server_form_token(db):
    with TestClient(app) as client:
        response = client.post(
            "/web/promocoes",
            data={"request_key": "missing-token", "description": "Campanha sintética"},
        )

    assert response.status_code == 403
    assert db.query(PromotionCampaign).count() == 0


def test_contact_cannot_opt_in_without_source_and_date(db):
    client_record = Client(razao_social="Cliente Contato")
    db.add(client_record)
    db.commit()

    with TestClient(app) as client:
        response = client.post(
            f"/web/clients/{client_record.id}/campaign-contacts",
            data={"name": "Pessoa", "email": "pessoa@example.test", "marketing_enabled": "on", "form_token": promotion_form_token(f"client-contacts:{client_record.id}")},
        )

    assert response.status_code == 422
    assert db.query(ClientCampaignContact).count() == 0


def test_contact_opt_in_records_origin_and_date_before_becoming_eligible(db):
    client_record = Client(razao_social="Cliente Consentido")
    db.add(client_record)
    db.commit()

    with TestClient(app) as client:
        response = client.post(
            f"/web/clients/{client_record.id}/campaign-contacts",
            data={
                "name": "Pessoa",
                "email": "pessoa@example.test",
                "marketing_enabled": "on",
                "consent_source": "Formulário sintético",
                "consented_on": "2026-10-07",
                "form_token": promotion_form_token(f"client-contacts:{client_record.id}"),
            },
            follow_redirects=False,
        )

    contact = db.query(ClientCampaignContact).one()
    assert response.status_code == 303
    assert contact.marketing_enabled is True
    assert contact.consented_at.date().isoformat() == "2026-10-07"
    assert contact.consent_source == "Formulário sintético"
    event = db.query(CampaignContactConsentEvent).one()
    assert event.event_type == "opt_in"
    assert event.source == "Formulário sintético"
    assert contact.id in {item.id for item in eligible_campaign_contacts(db)}


def test_revoking_contact_appends_history_and_removes_eligibility(db):
    contact = _contact(
        db,
        enabled=True,
        source="Formulário sintético",
        consented_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )
    first_consent_date = contact.consented_at

    with TestClient(app) as client:
        response = client.post(
            f"/web/clients/{contact.client_id}/campaign-contacts/{contact.id}",
            data={"name": contact.name, "email": contact.email, "consent_source": contact.consent_source, "consented_on": "2026-10-07", "form_token": promotion_form_token(f"client-contacts:{contact.client_id}")},
            follow_redirects=False,
        )

    db.refresh(contact)
    assert response.status_code == 303
    assert contact.marketing_enabled is False
    assert contact.consented_at.replace(tzinfo=first_consent_date.tzinfo) == first_consent_date
    assert [event.event_type for event in db.query(CampaignContactConsentEvent).order_by(CampaignContactConsentEvent.id)] == ["opt_in", "opt_out"]
    assert contact.id not in {item.id for item in eligible_campaign_contacts(db)}


def test_changing_authorized_email_requires_new_explicit_consent_and_snapshots_address(db):
    contact = _contact(
        db,
        enabled=True,
        source="Formulário sintético",
        consented_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )
    old_email = contact.email_normalized

    with TestClient(app) as client:
        rejected = client.post(
            f"/web/clients/{contact.client_id}/campaign-contacts/{contact.id}",
            data={
                "name": contact.name,
                "email": "novo@example.test",
                "marketing_enabled": "on",
                "consent_source": "Formulário sintético",
                "consented_on": "2026-10-07",
                "form_token": promotion_form_token(f"client-contacts:{contact.client_id}"),
            },
        )
        accepted = client.post(
            f"/web/clients/{contact.client_id}/campaign-contacts/{contact.id}",
            data={
                "name": contact.name,
                "email": "novo@example.test",
                "marketing_enabled": "on",
                "reauthorize_consent": "on",
                "consent_source": "Confirmação do contato",
                "consented_on": "2026-10-07",
                "form_token": promotion_form_token(f"client-contacts:{contact.client_id}"),
            },
            follow_redirects=False,
        )

    db.refresh(contact)
    assert rejected.status_code == 422
    assert accepted.status_code == 303
    assert contact.id in {item.id for item in eligible_campaign_contacts(db)}
    events = db.query(CampaignContactConsentEvent).filter_by(contact_id=contact.id).order_by(CampaignContactConsentEvent.id).all()
    assert events[0].email_snapshot == old_email
    assert events[-1].email_snapshot == "novo@example.test"


def test_campaign_history_is_append_only(db):
    contact = _contact(
        db,
        enabled=True,
        source="Consentimento sintético",
        consented_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )
    campaign = create_campaign_draft(
        db,
        request_key="immutable-event-001",
        description="Campanha sintética",
        subject="Assunto",
        body="Corpo revisável",
        image_path="promotions/1/image-v1.png",
        selected_contact_ids=[contact.id],
    )
    event = db.query(PromotionCampaignEvent).filter_by(campaign_id=campaign.id).one()

    event.event_type = "rewritten"
    with pytest.raises(ValueError, match="imutável"):
        db.commit()


def test_campaign_generation_route_uses_synthetic_generator_and_persists_preview(db, tmp_path, monkeypatch):
    import app.routers.promotions as promotions_router

    monkeypatch.setattr(promotions_router.settings, "output_dir", tmp_path)

    class FakeGenerator:
        def generate_copy(self, description):
            assert "sem datas" in description
            return PromotionCopy(subject="Condições especiais", body="Entre em contato e agende uma conversa.")

        def generate_image(self, description, **_kwargs):
            return GeneratedImage(b"\x89PNG\r\n\x1a\n" + b"synthetic-image", "image/png")

    app.state.promotion_generator_factory = FakeGenerator
    try:
        with TestClient(app) as client:
            response = client.post(
                "/web/promocoes",
                data={"request_key": "route-generate-no-date", "description": "Campanha sem datas", "form_token": promotion_form_token("new-campaign")},
                follow_redirects=False,
            )
        campaign = db.query(PromotionCampaign).one()
        assert response.status_code == 303
        assert campaign.status == "draft"
        assert campaign.subject == "Condições especiais"
        assert campaign.image_path.endswith("image-v2.png")
        assert (tmp_path / campaign.image_path).is_file()
    finally:
        del app.state.promotion_generator_factory


def test_campaign_generation_failure_leaves_revisable_record_without_sending(db, tmp_path, monkeypatch):
    import app.routers.promotions as promotions_router

    monkeypatch.setattr(promotions_router.settings, "output_dir", tmp_path)

    class FailedGenerator:
        def generate_copy(self, _description):
            raise PromotionGenerationError("synthetic_unavailable", "synthetic provider error")

    app.state.promotion_generator_factory = FailedGenerator
    try:
        with TestClient(app) as client:
            response = client.post(
                "/web/promocoes",
                data={"request_key": "route-generation-failure", "description": "Campanha sintética sem período", "form_token": promotion_form_token("new-campaign")},
                follow_redirects=False,
            )
        campaign = db.query(PromotionCampaign).one()
        assert response.status_code == 303
        assert campaign.status == "generation_failed"
        assert campaign.generation_error == "synthetic_unavailable"
        assert db.query(PromotionRecipient).count() == 0
    finally:
        del app.state.promotion_generator_factory


def test_image_generation_failure_preserves_successful_copy_for_review(db, tmp_path, monkeypatch):
    import app.routers.promotions as promotions_router

    monkeypatch.setattr(promotions_router.settings, "output_dir", tmp_path)

    class ImageFailureGenerator:
        def generate_copy(self, _description):
            return PromotionCopy(subject="Assunto revisável", body="Texto sintético que pode ser revisado.")

        def generate_image(self, _description, **_kwargs):
            raise PromotionGenerationError("image_unavailable", "synthetic provider error")

    app.state.promotion_generator_factory = ImageFailureGenerator
    try:
        with TestClient(app) as client:
            response = client.post(
                "/web/promocoes",
                data={
                    "request_key": "route-image-failure-keeps-copy",
                    "description": "Campanha sintética para revisão",
                    "form_token": promotion_form_token("new-campaign"),
                },
                follow_redirects=False,
            )
        campaign = db.query(PromotionCampaign).one()
        assert response.status_code == 303
        assert campaign.status == "generation_failed"
        assert campaign.generation_error == "image_unavailable"
        assert campaign.subject == "Assunto revisável"
        assert campaign.body == "Texto sintético que pode ser revisado."
        assert campaign.image_path == ""
        assert db.query(PromotionRecipient).count() == 0
    finally:
        del app.state.promotion_generator_factory


def test_send_route_stays_disabled_and_does_not_create_mailer_without_smtp(db, monkeypatch):
    import app.routers.promotions as promotions_router

    contact = _contact(
        db,
        enabled=True,
        source="Consentimento sintético",
        consented_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )
    campaign = create_campaign_draft(
        db,
        request_key="route-disabled-send",
        description="Campanha sintética",
        subject="Condições especiais",
        body="Fale conosco e agende.",
        image_path="promotions/1/image-v1.png",
        selected_contact_ids=[contact.id],
    )
    monkeypatch.setattr(promotions_router, "campaign_smtp_ready", lambda _settings: False)
    form_token = promotion_form_token(f"campaign:{campaign.id}:revision:{campaign.revision}")

    with TestClient(app) as client:
        response = client.post(
            f"/web/promocoes/{campaign.id}/confirm-send",
            data={"confirmation": "CONFIRMAR", "form_token": form_token},
        )

    assert response.status_code == 503
    assert db.query(PromotionRecipient).one().status == "pending"
