from __future__ import annotations

import html
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from app.config import Settings
from app.services.promotion_campaign_service import CampaignSendUnavailable, is_valid_campaign_email
from app.services.promotion_generation_service import validate_image_bytes


def campaign_smtp_ready(settings: Settings) -> bool:
    return all(
        (
            settings.promotion_smtp_host.strip(),
            settings.promotion_smtp_username.strip(),
            bool(settings.promotion_smtp_password.get_secret_value()),
            settings.promotion_smtp_from_email.strip(),
        )
    ) and not (settings.promotion_smtp_starttls and settings.promotion_smtp_use_ssl) and (
        settings.promotion_smtp_starttls or settings.promotion_smtp_use_ssl
    ) and is_valid_campaign_email(settings.promotion_smtp_from_email) and "\r" not in settings.promotion_smtp_from_name and "\n" not in settings.promotion_smtp_from_name


class SmtpCampaignMailer:
    """One-recipient SMTP transport; it never reads or modifies the IMAP mailbox."""

    def __init__(self, settings: Settings, output_dir: Path):
        if not campaign_smtp_ready(settings):
            raise CampaignSendUnavailable(
                "Envio indisponível: configure host, usuário, senha e remetente SMTP da campanha."
            )
        self.settings = settings
        self.output_dir = output_dir.resolve()

    def send(self, *, recipient, subject: str, body: str, image_path: str, message_id: str) -> str:
        relative = Path(image_path)
        image_file = (self.output_dir / relative).resolve()
        if not image_file.is_relative_to(self.output_dir) or not image_file.is_file():
            raise CampaignSendUnavailable("Imagem da campanha não encontrada no armazenamento da aplicação.")
        image_data = image_file.read_bytes()
        suffix = image_file.suffix.casefold()
        image_mime = "image/png" if suffix == ".png" else "image/jpeg" if suffix in {".jpg", ".jpeg"} else ""
        validate_image_bytes(image_data, image_mime)

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((self.settings.promotion_smtp_from_name, self.settings.promotion_smtp_from_email))
        message["To"] = recipient.email_snapshot
        message["Message-ID"] = message_id
        message.set_content(body)
        html_body = (
            "<html><body><p>"
            + html.escape(body).replace("\n", "<br>")
            + '</p><img src="cid:campaign-image" alt="Imagem da campanha"></body></html>'
        )
        message.add_alternative(html_body, subtype="html")
        html_part = message.get_payload()[-1]
        html_part.add_related(
            image_data,
            maintype="image",
            subtype="png" if image_mime == "image/png" else "jpeg",
            cid="<campaign-image>",
            filename=image_file.name,
            disposition="inline",
        )

        host = self.settings.promotion_smtp_host.strip()
        port = self.settings.promotion_smtp_port
        timeout = self.settings.promotion_smtp_timeout_seconds
        password = self.settings.promotion_smtp_password.get_secret_value()
        client_cls = smtplib.SMTP_SSL if self.settings.promotion_smtp_use_ssl else smtplib.SMTP
        with client_cls(host, port, timeout=timeout) as server:
            if self.settings.promotion_smtp_starttls and not self.settings.promotion_smtp_use_ssl:
                server.starttls()
            server.login(self.settings.promotion_smtp_username, password)
            server.send_message(
                message,
                from_addr=self.settings.promotion_smtp_from_email,
                to_addrs=[recipient.email_snapshot],
            )
        return message_id
