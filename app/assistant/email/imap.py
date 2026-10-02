from __future__ import annotations

import imaplib
import hashlib
import base64
import binascii
import quopri
import re
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from email.header import decode_header, make_header
from email.parser import BytesHeaderParser
from email.policy import default
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser

from app.assistant.email.classification import to_result
from app.assistant.email.contracts import EmailMessageRecord, EmailQuery, EmailQueryResult
from app.assistant.email.provider import EmailUnavailableError


@dataclass(frozen=True)
class _FolderRead:
    records: list[EmailMessageRecord]
    candidate_count: int
    partial: bool = False
    limitation: str = ""


class YahooImapEmailReader:
    """Read-only Yahoo IMAP adapter. It never issues STORE or mutating commands."""

    def __init__(
        self,
        *,
        username: str,
        app_password: str,
        host: str = "imap.mail.yahoo.com",
        port: int = 993,
        timeout_seconds: float = 10.0,
        max_messages: int = 30,
        body_preview_chars: int = 4000,
        client_factory: Callable[..., object] | None = None,
    ) -> None:
        self.username = username.strip()
        self._app_password = app_password
        self.host = host.strip()
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.max_messages = max(1, min(max_messages, 100))
        self.body_preview_chars = max(200, min(body_preview_chars, 12000))
        self._client_factory = client_factory or imaplib.IMAP4_SSL

    def query(self, query: EmailQuery) -> EmailQueryResult:
        client = None
        try:
            client = self._client_factory(
                host=self.host,
                port=self.port,
                ssl_context=ssl.create_default_context(),
                timeout=self.timeout_seconds,
            )
            status, _ = client.login(self.username, self._app_password)
            if status != "OK":
                return self._failure(query, "A autenticação da caixa de e-mail falhou.")
            folders = self._discover_folders(client)
            inbox = folders.get("inbox", "INBOX")
            sent = folders.get("sent")
            inbox_read = self._read_folder(client, inbox, "inbox", query)
            if isinstance(inbox_read, list):  # compatibility with focused test doubles
                inbox_read = _FolderRead(records=inbox_read, candidate_count=len(inbox_read))
            records = inbox_read.records
            candidate_count = inbox_read.candidate_count
            sent_records: list[EmailMessageRecord] = []
            sent_failed = False
            sent_partial = False
            if query.awaiting_reply and sent is not None:
                sent_query = query.model_copy(
                    update={
                        "unread_only": False,
                        "sender": None,
                        "attention_only": False,
                        "awaiting_reply": False,
                        "reference": None,
                        "limit": self.max_messages,
                    }
                )
                try:
                    sent_read = self._read_folder(client, sent, "sent", sent_query)
                    if isinstance(sent_read, list):  # compatibility with focused test doubles
                        sent_read = _FolderRead(records=sent_read, candidate_count=len(sent_read))
                    sent_records = sent_read.records
                    sent_partial = sent_read.partial
                except EmailUnavailableError:
                    sent_failed = True
                    sent = None

            results = []
            for record in records:
                awaiting = "unknown"
                limitations: list[str] = []
                if query.awaiting_reply and sent is not None:
                    later_sent = any(
                        item.thread_reference == record.thread_reference
                        and item.received_at > record.received_at
                        for item in sent_records
                    )
                    preliminary = to_result(record, awaiting_reply="unknown")
                    requests_reply = "solicita resposta" in preliminary.evidence
                    awaiting = "no" if later_sent or not requests_reply else "yes"
                elif query.awaiting_reply:
                    limitations.append(
                        "A pasta Enviados não foi localizada; a resposta pendente não pode ser avaliada com confiança."
                    )
                result = to_result(record, awaiting_reply=awaiting, limitations=limitations)
                if query.attention_only and result.priority not in {"high", "critical"}:
                    continue
                if query.awaiting_reply and sent is not None and awaiting != "yes":
                    continue
                results.append(result)
            results.sort(
                key=lambda item: (item.priority in {"critical", "high"}, item.received_at),
                reverse=True,
            )
            results = results[: min(query.limit, self.max_messages)]
            limitations = []
            state = "success" if results else "empty"
            if inbox_read.partial:
                state = "partial"
                limitations.append(inbox_read.limitation)
            if query.awaiting_reply and sent is None:
                state = "partial"
                limitations.append(
                    (
                        "A pasta Enviados falhou durante a consulta; não é possível avaliar respostas "
                        "pendentes com confiança."
                        if sent_failed
                        else "A pasta Enviados não foi localizada; não é possível avaliar respostas pendentes com confiança."
                    )
                )
            elif query.awaiting_reply and sent_partial:
                state = "partial"
                limitations.append(
                    "A cobertura da pasta Enviados foi limitada; respostas pendentes podem estar incompletas."
                )
            return EmailQueryResult(
                state=state,
                provider="imap_yahoo",
                interval_start=query.start_at,
                interval_end=query.end_at,
                messages=results,
                candidate_count=candidate_count,
                applied_filters=self._applied_filters(query),
                sent_available=sent is not None,
                partial=state == "partial",
                limitations=limitations,
            )
        except imaplib.IMAP4.error:
            return self._failure(query, "A autenticação ou a consulta IMAP falhou.")
        except (TimeoutError, socket.timeout):
            return self._failure(
                query,
                "A consulta de e-mail excedeu o tempo limite; isso não significa que a caixa está vazia.",
            )
        except (EmailUnavailableError, OSError, ValueError):
            return self._failure(query, "A caixa de e-mail está indisponível no momento.")
        finally:
            if client is not None:
                try:
                    client.logout()
                except Exception:
                    pass

    @staticmethod
    def _failure(query: EmailQuery, message: str) -> EmailQueryResult:
        return EmailQueryResult(
            state="failed",
            provider="imap_yahoo",
            interval_start=query.start_at,
            interval_end=query.end_at,
            user_message=message,
        )

    @staticmethod
    def _applied_filters(query: EmailQuery) -> list[str]:
        filters: list[str] = []
        if query.unread_only:
            filters.append("unread")
        if query.sender:
            filters.append("sender")
        if query.attention_only:
            filters.append("attention")
        if query.awaiting_reply:
            filters.append("awaiting_reply")
        if query.reference:
            filters.append("reference")
        return filters

    @staticmethod
    def _discover_folders(client: object) -> dict[str, str]:
        status, lines = client.list()
        if status != "OK":
            return {"inbox": "INBOX"}
        result: dict[str, str] = {}
        candidates: list[str] = []
        for raw in lines or []:
            line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            match = re.search(r"\((?P<attrs>[^)]*)\)\s+(?:\"[^\"]*\"|NIL)\s+(?P<name>.+)$", line)
            if not match:
                continue
            attrs = match.group("attrs").casefold()
            name = match.group("name").strip().strip('"')
            candidates.append(name)
            if "\\inbox" in attrs:
                result["inbox"] = name
            if "\\sent" in attrs:
                result["sent"] = name
        result.setdefault("inbox", "INBOX")
        if "sent" not in result:
            sent_names = {"sent", "sent items", "sent messages", "enviados", "itens enviados"}
            result["sent"] = next(
                (name for name in candidates if name.casefold() in sent_names),
                None,
            )
            if result["sent"] is None:
                result.pop("sent")
        return result

    def _read_folder(
        self,
        client: object,
        mailbox: str,
        role: str,
        query: EmailQuery,
    ) -> _FolderRead:
        status, _ = client.select(mailbox, readonly=True)
        if status != "OK":
            raise EmailUnavailableError("Falha ao selecionar pasta IMAP.")
        uidvalidity = self._uidvalidity(client)
        search_start = query.start_at.astimezone(timezone.utc).date()
        before = query.end_at.astimezone(timezone.utc).date() + timedelta(days=1)
        criteria: list[str] = [
            "SINCE",
            search_start.strftime("%d-%b-%Y"),
            "BEFORE",
            before.strftime("%d-%b-%Y"),
        ]
        if query.unread_only:
            criteria.append("UNSEEN")
        status, data = client.uid("search", None, *criteria)
        if status != "OK":
            raise EmailUnavailableError("Falha ao pesquisar pasta IMAP.")
        if not data:
            return _FolderRead(records=[], candidate_count=0)
        all_raw_uids = data[0].split()
        partial = len(all_raw_uids) > self.max_messages
        raw_uids = all_raw_uids[-self.max_messages :]
        exact_uids = self._uids_inside_interval(client, raw_uids, query)
        records: list[EmailMessageRecord] = []
        for raw_uid in reversed(exact_uids):
            uid = raw_uid.decode("ascii") if isinstance(raw_uid, bytes) else str(raw_uid)
            record = self._fetch_message(
                client,
                mailbox,
                role,
                uidvalidity,
                uid,
                query.start_at.tzinfo,
            )
            if record is None:
                continue
            if not (query.start_at <= record.received_at <= query.end_at):
                continue
            if query.sender and query.sender.casefold() not in record.sender.casefold():
                continue
            if query.reference and query.reference != record.reference:
                continue
            records.append(record)
            if (
                not query.attention_only
                and not query.awaiting_reply
                and len(records) >= min(query.limit, self.max_messages)
            ):
                break
        limitation = (
            f"A consulta foi limitada às {self.max_messages} mensagens mais recentes encontradas pelo servidor."
            if partial
            else ""
        )
        return _FolderRead(
            records=records,
            candidate_count=len(exact_uids),
            partial=partial,
            limitation=limitation,
        )

    def _uids_inside_interval(
        self,
        client: object,
        raw_uids: list[bytes],
        query: EmailQuery,
    ) -> list[bytes]:
        if not raw_uids:
            return []
        uid_set = ",".join(
            value.decode("ascii") if isinstance(value, bytes) else str(value)
            for value in raw_uids
        )
        status, data = client.uid("fetch", uid_set, "(UID INTERNALDATE)")
        if status != "OK":
            raise EmailUnavailableError("Falha ao verificar datas internas da pasta IMAP.")
        internaldates = _uid_internaldates(data)
        exact: list[bytes] = []
        for raw_uid in raw_uids:
            uid = raw_uid.decode("ascii") if isinstance(raw_uid, bytes) else str(raw_uid)
            received_at = internaldates.get(uid)
            if received_at is None or query.start_at <= received_at <= query.end_at:
                exact.append(raw_uid)
        return exact

    def _fetch_message(
        self,
        client: object,
        mailbox: str,
        role: str,
        uidvalidity: str,
        uid: str,
        default_timezone: tzinfo | None,
    ) -> EmailMessageRecord | None:
        header_query = (
            "(INTERNALDATE BODY.PEEK[HEADER.FIELDS "
            "(MESSAGE-ID REFERENCES IN-REPLY-TO FROM TO SUBJECT DATE)])"
        )
        status, header_data = client.uid("fetch", uid, header_query)
        if status != "OK":
            return None
        header_bytes = _response_bytes(header_data)
        if not header_bytes:
            return None
        message = BytesHeaderParser(policy=default).parsebytes(header_bytes)
        received_at = _internaldate_from_response(header_data)
        if received_at is None:
            raw_date = message.get("Date")
            try:
                received_at = parsedate_to_datetime(raw_date) if raw_date else None
            except (TypeError, ValueError):
                received_at = None
        if received_at is None:
            return None
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=default_timezone)
        elif default_timezone is not None:
            received_at = received_at.astimezone(default_timezone)

        _status, flags_data = client.uid("fetch", uid, "(FLAGS)")
        seen = "\\Seen" in repr(flags_data)
        body = self._fetch_text_body(client, uid)
        message_id = str(message.get("Message-ID") or "").strip()[:500]
        parent = str(message.get("In-Reply-To") or "").strip()[:500]
        references = str(message.get("References") or "").split()
        thread_reference = (references[0] if references else parent or message_id or f"{mailbox}:{uid}")[:500]
        sender = str(make_header(decode_header(str(message.get("From") or ""))))[:500]
        recipients = tuple(address for _name, address in getaddresses(message.get_all("To", [])))
        subject = str(make_header(decode_header(str(message.get("Subject") or "(sem assunto)"))))[:500]
        opaque_reference = hashlib.sha256(
            f"{mailbox}\0{uidvalidity}\0{uid}".encode("utf-8")
        ).hexdigest()[:24]
        return EmailMessageRecord(
            reference=f"imap:{opaque_reference}",
            thread_reference=thread_reference,
            folder_role=role,  # type: ignore[arg-type]
            sender=sender,
            recipients=recipients,
            subject=subject,
            received_at=received_at,
            seen=seen,
            text=body,
        )

    def _fetch_text_body(self, client: object, uid: str) -> str:
        status, structure_data = client.uid("fetch", uid, "(BODYSTRUCTURE)")
        if status != "OK":
            return ""
        text_part = _select_text_part(repr(structure_data))
        if text_part is None:
            return ""
        status, body_data = client.uid(
            "fetch",
            uid,
            f"(BODY.PEEK[{text_part.section}]<0.{self.body_preview_chars}>)",
        )
        if status != "OK":
            return ""
        raw = _response_bytes(body_data)[: self.body_preview_chars]
        return _decode_text_part(raw, text_part)[: self.body_preview_chars].strip()

    @staticmethod
    def _uidvalidity(client: object) -> str:
        try:
            _name, values = client.response("UIDVALIDITY")
            if values:
                value = values[0]
                return value.decode("ascii") if isinstance(value, bytes) else str(value)
        except Exception:
            pass
        return "unknown"


def _response_bytes(data: object) -> bytes:
    if not isinstance(data, (list, tuple)):
        return b""
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
        if isinstance(item, bytes) and b"\r\n" in item:
            return item
    return b""


def _internaldate_from_response(data: object) -> datetime | None:
    if not isinstance(data, (list, tuple)):
        return None
    for item in data:
        metadata = item[0] if isinstance(item, tuple) and item else item
        if not isinstance(metadata, bytes):
            continue
        match = re.search(rb'INTERNALDATE\s+"([^"]+)"', metadata, flags=re.IGNORECASE)
        if match is None:
            continue
        try:
            return datetime.strptime(
                match.group(1).decode("ascii"),
                "%d-%b-%Y %H:%M:%S %z",
            )
        except (UnicodeDecodeError, ValueError):
            continue
    return None


def _uid_internaldates(data: object) -> dict[str, datetime]:
    result: dict[str, datetime] = {}
    if not isinstance(data, (list, tuple)):
        return result
    for item in data:
        metadata = item[0] if isinstance(item, tuple) and item else item
        if not isinstance(metadata, bytes):
            continue
        uid_match = re.search(rb"\bUID\s+(\d+)\b", metadata, flags=re.IGNORECASE)
        date_match = re.search(
            rb'INTERNALDATE\s+"([^"]+)"', metadata, flags=re.IGNORECASE
        )
        if uid_match is None or date_match is None:
            continue
        try:
            received_at = datetime.strptime(
                date_match.group(1).decode("ascii"),
                "%d-%b-%Y %H:%M:%S %z",
            )
        except (UnicodeDecodeError, ValueError):
            continue
        result[uid_match.group(1).decode("ascii")] = received_at
    return result


@dataclass(frozen=True)
class _TextPart:
    section: str
    charset: str
    encoding: str
    subtype: str


def _first_text_section(structure: str) -> str | None:
    part = _select_text_part(structure)
    return part.section if part else None


def _select_text_part(structure: str) -> _TextPart | None:
    marker = re.search(r"BODYSTRUCTURE\s*", structure, flags=re.IGNORECASE)
    if marker is None:
        return None
    tokens = re.findall(r'\(|\)|"(?:\\.|[^"\\])*"|NIL|[^\s()]+', structure[marker.end() :])
    if not tokens:
        return None
    position = 0

    def parse() -> object:
        nonlocal position
        if position >= len(tokens):
            raise ValueError("BODYSTRUCTURE incompleto")
        token = tokens[position]
        position += 1
        if token == "(":
            values = []
            while position < len(tokens) and tokens[position] != ")":
                values.append(parse())
            if position >= len(tokens):
                raise ValueError("BODYSTRUCTURE sem fechamento")
            position += 1
            return values
        if token == ")":
            raise ValueError("BODYSTRUCTURE invalido")
        if token.upper() == "NIL":
            return None
        if token.startswith('"'):
            return bytes(token[1:-1], "utf-8").decode("unicode_escape")
        return token

    try:
        root = parse()
    except (UnicodeDecodeError, ValueError):
        return None
    candidates: list[_TextPart] = []

    def visit(node: object, prefix: str, *, root_part: bool = False) -> None:
        if not isinstance(node, list) or not node:
            return
        if isinstance(node[0], list):
            child_index = 1
            for child in node:
                if not isinstance(child, list):
                    break
                child_prefix = f"{prefix}.{child_index}" if prefix else str(child_index)
                visit(child, child_prefix)
                child_index += 1
            return
        media_type = str(node[0] or "").upper()
        subtype = str(node[1] or "").upper() if len(node) > 1 else ""
        if media_type != "TEXT":
            return
        params = node[2] if len(node) > 2 and isinstance(node[2], list) else []
        charset = "utf-8"
        for index in range(0, len(params) - 1, 2):
            if str(params[index]).upper() == "CHARSET":
                charset = str(params[index + 1])
                break
        encoding = str(node[5] or "8BIT").upper() if len(node) > 5 else "8BIT"
        candidates.append(
            _TextPart(
                section="TEXT" if root_part else prefix,
                charset=charset,
                encoding=encoding,
                subtype=subtype,
            )
        )

    visit(root, "", root_part=True)
    return next((part for part in candidates if part.subtype == "PLAIN"), None) or (
        next((part for part in candidates if part.subtype == "HTML"), None)
    )


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _decode_text_part(raw: bytes, part: _TextPart) -> str:
    try:
        if part.encoding == "BASE64":
            decoded = base64.b64decode(raw, validate=False)
        elif part.encoding == "QUOTED-PRINTABLE":
            decoded = quopri.decodestring(raw)
        else:
            decoded = raw
    except (ValueError, binascii.Error):
        decoded = raw
    try:
        text = decoded.decode(part.charset or "utf-8", errors="replace")
    except LookupError:
        text = decoded.decode("utf-8", errors="replace")
    if part.subtype == "HTML":
        parser = _HTMLTextExtractor()
        parser.feed(text)
        text = " ".join(parser.parts)
    return " ".join(text.split())
