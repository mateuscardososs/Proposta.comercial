from __future__ import annotations

from email.message import EmailMessage

import pytest

from app.config import Settings
from app.services.promotion_campaign_service import CampaignSendUnavailable
from app.services.promotion_mail_service import SmtpCampaignMailer, campaign_smtp_ready


def _settings(**updates):
    values = {
        "promotion_smtp_host": "smtp.synthetic.test",
        "promotion_smtp_username": "synthetic-user",
        "promotion_smtp_password": "synthetic-password",
        "promotion_smtp_from_email": "campanhas@example.test",
        "promotion_smtp_starttls": True,
        "promotion_smtp_use_ssl": False,
    }
    values.update(updates)
    return Settings(**values)


def test_smtp_is_not_ready_without_separate_output_credentials():
    assert campaign_smtp_ready(Settings()) is False
    with pytest.raises(CampaignSendUnavailable, match="SMTP"):
        SmtpCampaignMailer(Settings(), output_dir=None)


def test_smtp_transport_sends_one_recipient_with_tls_and_no_real_network(tmp_path, monkeypatch):
    import app.services.promotion_mail_service as mail_service

    image = b"\x89PNG\r\n\x1a\n" + b"synthetic-image"
    image_path = tmp_path / "promotions" / "1" / "image.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(image)
    observed = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            observed.update(host=host, port=port, timeout=timeout)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def starttls(self):
            observed["starttls"] = True

        def login(self, username, password):
            observed["username"] = username
            observed["password_received"] = bool(password)

        def send_message(self, message, *, from_addr, to_addrs):
            observed["message"] = message
            observed["from"] = from_addr
            observed["to"] = to_addrs

    monkeypatch.setattr(mail_service.smtplib, "SMTP", FakeSMTP)
    settings = _settings(output_dir=tmp_path)
    mailer = SmtpCampaignMailer(settings, tmp_path)
    recipient = type("Recipient", (), {"email_snapshot": "one@example.test"})()

    result = mailer.send(
        recipient=recipient,
        subject="Assunto sintético",
        body="Texto sintético <sem HTML perigoso>",
        image_path="promotions/1/image.png",
        message_id="<synthetic-only@example.test>",
    )

    assert result == "<synthetic-only@example.test>"
    assert observed["starttls"] is True
    assert observed["to"] == ["one@example.test"]
    assert observed["password_received"] is True
    message = observed["message"]
    assert isinstance(message, EmailMessage)
    assert "&lt;sem HTML perigoso&gt;" in message.as_string()
    assert "two@example.test" not in message.as_string()
