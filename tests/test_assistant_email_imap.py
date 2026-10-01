from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.assistant.email.contracts import EmailQuery
from app.assistant.email.imap import YahooImapEmailReader


NOW = datetime(2026, 10, 1, 10, 0, tzinfo=ZoneInfo("America/Recife"))


class FakeImap:
    def __init__(self):
        self.calls = []
        self.selected = None

    def login(self, username, password):
        self.calls.append(("login", username, password))
        return "OK", [b"logged in"]

    def list(self):
        self.calls.append(("list",))
        return "OK", [
            b'(\\HasNoChildren \\Inbox) "/" "Inbox"',
            b'(\\HasNoChildren \\Sent) "/" "Enviados"',
        ]

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        self.selected = mailbox
        return "OK", [b"1"]

    def response(self, name):
        return ("UIDVALIDITY", [b"44"])

    def uid(self, command, *args):
        self.calls.append(("uid", command, *args))
        if command == "search":
            return "OK", [b"12"] if self.selected == "Inbox" else [b""]
        if command == "fetch" and "BODYSTRUCTURE" in str(args):
            return "OK", [(b'12 (BODYSTRUCTURE ("TEXT" "PLAIN" ("CHARSET" "UTF-8") NIL NIL "7BIT" 90 2))', b"")]
        if command == "fetch" and "HEADER.FIELDS" in str(args):
            raw = (
                b"Message-ID: <m1@example>\r\n"
                b"From: Marina <marina@alfa.example>\r\n"
                b"To: ad@example\r\n"
                b"Subject: Prazo de relatorio\r\n"
                b"Date: Thu, 01 Oct 2026 09:00:00 -0300\r\n\r\n"
            )
            return "OK", [(b"12 (BODY[HEADER.FIELDS ...] {120}", raw)]
        if command == "fetch" and "BODY.PEEK[TEXT]" in str(args):
            return "OK", [(b"12 (BODY[TEXT] {49}", b"Favor responder. Prazo explicito: 02/10/2026.")]
        if command == "fetch" and "FLAGS" in str(args):
            return "OK", [b"12 (FLAGS ())"]
        raise AssertionError((command, args))

    def logout(self):
        self.calls.append(("logout",))


def test_yahoo_imap_uses_readonly_select_peek_and_special_use_folders():
    client = FakeImap()
    reader = YahooImapEmailReader(
        username="empresa@yahoo.com",
        app_password="secret-app-password",
        host="imap.mail.yahoo.com",
        port=993,
        timeout_seconds=5,
        max_messages=20,
        body_preview_chars=4000,
        client_factory=lambda **_kwargs: client,
    )

    result = reader.query(EmailQuery(start_at=NOW.replace(hour=0), end_at=NOW, limit=10))

    assert result.state == "success"
    assert result.messages[0].reference == "imap:Inbox:44:12"
    assert result.messages[0].seen is False
    selects = [call for call in client.calls if call[0] == "select"]
    assert selects == [("select", "Inbox", True)]
    serialized_calls = repr(client.calls)
    assert "BODY.PEEK" in serialized_calls
    assert "store" not in serialized_calls.casefold()
    assert "secret-app-password" not in result.model_dump_json()


def test_yahoo_imap_reports_missing_sent_folder_for_pending_reply_query():
    client = FakeImap()
    client.list = lambda: ("OK", [b'(\\HasNoChildren \\Inbox) "/" "Inbox"'])
    reader = YahooImapEmailReader(
        username="empresa@yahoo.com",
        app_password="secret-app-password",
        client_factory=lambda **_kwargs: client,
    )

    result = reader.query(
        EmailQuery(start_at=NOW.replace(hour=0), end_at=NOW, awaiting_reply=True)
    )

    assert result.state == "partial"
    assert result.sent_available is False
    assert "Enviados" in result.limitations[0]
