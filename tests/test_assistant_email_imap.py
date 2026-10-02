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
        if command == "fetch" and args[-1] == "(UID INTERNALDATE)":
            return "OK", []
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


class MultipleMessageImap(FakeImap):
    def uid(self, command, *args):
        self.calls.append(("uid", command, *args))
        if command == "search":
            return "OK", [b"10 11"]
        if command == "fetch" and args[-1] == "(UID INTERNALDATE)":
            return "OK", []
        uid = str(args[0])
        if command == "fetch" and "BODYSTRUCTURE" in str(args):
            return "OK", [
                (f'{uid} (BODYSTRUCTURE ("TEXT" "PLAIN" ("CHARSET" "UTF-8") NIL NIL "7BIT" 90 2))'.encode(), b"")
            ]
        if command == "fetch" and "HEADER.FIELDS" in str(args):
            subject = "Pedido com prazo" if uid == "10" else "Informativo"
            raw = (
                f"Message-ID: <m{uid}@example>\r\n"
                "From: Remetente <remetente@example.invalid>\r\n"
                "To: ad@example.invalid\r\n"
                f"Subject: {subject}\r\n"
                "Date: Fri, 02 Oct 2026 08:00:00 -0300\r\n\r\n"
            ).encode()
            return "OK", [(f'{uid} (INTERNALDATE "02-Oct-2026 11:00:00 +0000" BODY[HEADER.FIELDS ...]'.encode(), raw)]
        if command == "fetch" and "BODY.PEEK[TEXT]" in str(args):
            body = b"Favor responder. Prazo explicito: 02/10/2026." if uid == "10" else b"Newsletter informativa."
            return "OK", [(f"{uid} (BODY[TEXT] {{{len(body)}}}".encode(), body)]
        if command == "fetch" and "FLAGS" in str(args):
            return "OK", [f"{uid} (FLAGS ())".encode()]
        raise AssertionError((command, args))


class InternalDateImap(FakeImap):
    def uid(self, command, *args):
        self.calls.append(("uid", command, *args))
        if command == "search":
            return "OK", [b"12"]
        if command == "fetch" and args[-1] == "(UID INTERNALDATE)":
            return "OK", [b'1 (UID 12 INTERNALDATE "02-Oct-2026 04:00:00 +0000")']
        if command == "fetch" and "BODYSTRUCTURE" in str(args):
            return "OK", [(b'12 (BODYSTRUCTURE ("TEXT" "PLAIN" ("CHARSET" "UTF-8") NIL NIL "7BIT" 20 1))', b"")]
        if command == "fetch" and "HEADER.FIELDS" in str(args):
            raw = (
                b"Message-ID: <internal-date@example>\r\n"
                b"From: Remetente <remetente@example.invalid>\r\n"
                b"To: ad@example.invalid\r\n"
                b"Subject: Data recebida\r\n"
                b"Date: Thu, 01 Oct 2026 10:00:00 -0300\r\n\r\n"
            )
            return "OK", [
                (b'12 (INTERNALDATE "02-Oct-2026 04:00:00 +0000" BODY[HEADER.FIELDS ...]', raw)
            ]
        if command == "fetch" and "BODY.PEEK[TEXT]" in str(args):
            return "OK", [(b"12 (BODY[TEXT] {5}", b"Teste")]
        if command == "fetch" and "FLAGS" in str(args):
            return "OK", [b"12 (FLAGS ())"]
        raise AssertionError((command, args))


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


def test_imap_uses_internaldate_as_received_date_instead_of_sender_header_date():
    client = InternalDateImap()
    reader = YahooImapEmailReader(
        username="empresa@yahoo.com",
        app_password="secret-app-password",
        client_factory=lambda **_kwargs: client,
    )
    start = datetime(2026, 10, 2, 0, 0, tzinfo=ZoneInfo("America/Recife"))
    end = datetime(2026, 10, 2, 23, 59, 59, tzinfo=ZoneInfo("America/Recife"))

    result = reader.query(EmailQuery(start_at=start, end_at=end))

    assert result.state == "success"
    assert len(result.messages) == 1
    assert result.messages[0].received_at.astimezone(ZoneInfo("America/Recife")) == datetime(
        2026, 10, 2, 1, 0, tzinfo=ZoneInfo("America/Recife")
    )


def test_imap_search_converts_local_end_boundary_to_utc_calendar_day():
    client = InternalDateImap()
    reader = YahooImapEmailReader(
        username="empresa@yahoo.com",
        app_password="secret-app-password",
        client_factory=lambda **_kwargs: client,
    )
    start = datetime(2026, 10, 2, 0, 0, tzinfo=ZoneInfo("America/Recife"))
    end = datetime(2026, 10, 2, 23, 59, 59, tzinfo=ZoneInfo("America/Recife"))

    reader.query(EmailQuery(start_at=start, end_at=end))

    search = next(call for call in client.calls if call[:2] == ("uid", "search"))
    assert search[3:] == ("SINCE", "02-Oct-2026", "BEFORE", "04-Oct-2026")


def test_attention_filter_scans_candidates_before_applying_output_limit():
    client = MultipleMessageImap()
    reader = YahooImapEmailReader(
        username="empresa@yahoo.com",
        app_password="secret-app-password",
        max_messages=10,
        client_factory=lambda **_kwargs: client,
    )
    start = datetime(2026, 10, 2, 0, 0, tzinfo=ZoneInfo("America/Recife"))
    end = datetime(2026, 10, 2, 23, 59, 59, tzinfo=ZoneInfo("America/Recife"))

    result = reader.query(
        EmailQuery(start_at=start, end_at=end, attention_only=True, limit=1)
    )

    assert result.state == "success"
    assert len(result.messages) == 1
    assert result.messages[0].priority in {"high", "critical"}


def test_candidate_count_is_not_reduced_by_visual_output_limit():
    client = MultipleMessageImap()
    reader = YahooImapEmailReader(
        username="empresa@yahoo.com",
        app_password="secret-app-password",
        max_messages=10,
        client_factory=lambda **_kwargs: client,
    )
    start = datetime(2026, 10, 2, 0, 0, tzinfo=ZoneInfo("America/Recife"))
    end = datetime(2026, 10, 2, 23, 59, 59, tzinfo=ZoneInfo("America/Recife"))

    result = reader.query(EmailQuery(start_at=start, end_at=end, limit=1))

    assert result.state == "success"
    assert len(result.messages) == 1
    assert result.candidate_count == 2


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
