from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.assistant.email.contracts import EmailQuery
from app.assistant.email.imap import (
    YahooImapEmailReader,
    _TextPart,
    _decode_text_part,
    _first_text_section,
)


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
    assert result.messages[0].reference.startswith("imap:")
    assert "Inbox" not in result.messages[0].reference
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


def test_imap_body_selector_never_falls_back_to_non_text_attachment():
    image_first = "BODYSTRUCTURE ((\"IMAGE\" \"PNG\" NIL NIL NIL \"BASE64\" 500) \"MIXED\")"
    text_first = "BODYSTRUCTURE ((\"TEXT\" \"PLAIN\" NIL NIL NIL \"7BIT\" 20 1) \"MIXED\")"

    assert _first_text_section(image_first) is None
    assert _first_text_section(text_first) == "1"
    nested = (
        'BODYSTRUCTURE ((("TEXT" "PLAIN" ("CHARSET" "UTF-8") NIL NIL "QUOTED-PRINTABLE" 20 1) '
        '("TEXT" "HTML" ("CHARSET" "UTF-8") NIL NIL "BASE64" 30 1) "ALTERNATIVE") '
        '("APPLICATION" "PDF" NIL NIL NIL "BASE64" 500) "MIXED")'
    )
    assert _first_text_section(nested) == "1.1"


def test_imap_text_decoder_handles_transfer_encoding_charset_and_html():
    quoted = _TextPart(section="1", charset="iso-8859-1", encoding="QUOTED-PRINTABLE", subtype="PLAIN")
    html = _TextPart(section="2", charset="utf-8", encoding="BASE64", subtype="HTML")

    assert _decode_text_part(b"Relat=F3rio at=E9 amanh=E3", quoted) == "Relatório até amanhã"
    assert _decode_text_part(b"PHA+UHJhem8gPGI+YW1hbmjDozwvYj48L3A+", html) == "Prazo amanhã"


def test_sent_folder_query_does_not_reuse_inbox_filters():
    client = FakeImap()

    class RecordingReader(YahooImapEmailReader):
        def __init__(self):
            super().__init__(
                username="empresa@yahoo.com",
                app_password="secret-app-password",
                client_factory=lambda **_kwargs: client,
            )
            self.folder_queries = []

        def _read_folder(self, client, mailbox, role, query):
            self.folder_queries.append((role, query))
            return []

    reader = RecordingReader()
    reader.query(
        EmailQuery(
            start_at=NOW.replace(hour=0),
            end_at=NOW,
            unread_only=True,
            sender="Alfa",
            awaiting_reply=True,
            reference="opaque-ref",
        )
    )

    sent_query = reader.folder_queries[1][1]
    assert sent_query.unread_only is False
    assert sent_query.sender is None
    assert sent_query.reference is None


def test_inbox_select_failure_is_failed_not_empty():
    client = FakeImap()
    client.select = lambda _mailbox, readonly=False: ("NO", [b"unavailable"])
    reader = YahooImapEmailReader(
        username="empresa@yahoo.com",
        app_password="secret-app-password",
        client_factory=lambda **_kwargs: client,
    )

    result = reader.query(EmailQuery(start_at=NOW.replace(hour=0), end_at=NOW))

    assert result.state == "failed"
    assert "indisponível" in result.user_message


def test_sent_select_failure_is_partial_and_not_reported_available():
    client = FakeImap()
    original_select = client.select

    def select(mailbox, readonly=False):
        if mailbox == "Enviados":
            return "NO", [b"sent unavailable"]
        return original_select(mailbox, readonly=readonly)

    client.select = select
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
    assert "falhou" in result.limitations[0]
