from __future__ import annotations

import imaplib
import re
import socket
import ssl
from collections.abc import Callable
from datetime import timedelta
from email.header import decode_header, make_header
from email.parser import BytesHeaderParser
from email.policy import default
from email.utils import getaddresses, parsedate_to_datetime

from app.assistant.email.classification import to_result
from app.assistant.email.contracts import EmailMessageRecord, EmailQuery, EmailQueryResult


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
            records = self._read_folder(client, inbox, "inbox", query)
            sent_records: list[EmailMessageRecord] = []
            if query.awaiting_reply and sent is not None:
                sent_records = self._read_folder(client, sent, "sent", query)

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
            if query.awaiting_reply and sent is None:
                state = "partial"
                limitations.append(
                    "A pasta Enviados não foi localizada; não é possível avaliar respostas pendentes com confiança."
                )
            return EmailQueryResult(
                state=state,
                provider="imap_yahoo",
                interval_start=query.start_at,
                interval_end=query.end_at,
                messages=results,
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
        except (OSError, ValueError):
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
    ) -> list[EmailMessageRecord]:
        status, _ = client.select(mailbox, readonly=True)
        if status != "OK":
            return []
        uidvalidity = self._uidvalidity(client)
        before = query.end_at.date() + timedelta(days=1)
        criteria: list[str] = [
            "SINCE",
            query.start_at.strftime("%d-%b-%Y"),
            "BEFORE",
            before.strftime("%d-%b-%Y"),
        ]
        if query.unread_only:
            criteria.append("UNSEEN")
        status, data = client.uid("search", None, *criteria)
        if status != "OK" or not data:
            return []
        raw_uids = data[0].split()[-self.max_messages :]
        records: list[EmailMessageRecord] = []
        for raw_uid in reversed(raw_uids):
            uid = raw_uid.decode("ascii") if isinstance(raw_uid, bytes) else str(raw_uid)
            record = self._fetch_message(client, mailbox, role, uidvalidity, uid)
            if record is None:
                continue
            if not (query.start_at <= record.received_at <= query.end_at):
                continue
            if query.sender and query.sender.casefold() not in record.sender.casefold():
                continue
            if query.reference and query.reference != record.reference:
                continue
            records.append(record)
            if len(records) >= min(query.limit, self.max_messages):
                break
        return records

    def _fetch_message(
        self,
        client: object,
        mailbox: str,
        role: str,
        uidvalidity: str,
        uid: str,
    ) -> EmailMessageRecord | None:
        header_query = (
            "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID REFERENCES IN-REPLY-TO FROM TO SUBJECT DATE)])"
        )
        status, header_data = client.uid("fetch", uid, header_query)
        if status != "OK":
            return None
        header_bytes = _response_bytes(header_data)
        if not header_bytes:
            return None
        message = BytesHeaderParser(policy=default).parsebytes(header_bytes)
        received_at = parsedate_to_datetime(message.get("Date"))
        if received_at is None:
            return None
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=query_timezone_placeholder())

        _status, flags_data = client.uid("fetch", uid, "(FLAGS)")
        seen = "\\Seen" in repr(flags_data)
        body = self._fetch_text_body(client, uid)
        message_id = str(message.get("Message-ID") or "").strip()
        parent = str(message.get("In-Reply-To") or "").strip()
        references = str(message.get("References") or "").split()
        thread_reference = references[0] if references else parent or message_id or f"{mailbox}:{uid}"
        sender = str(make_header(decode_header(str(message.get("From") or ""))))
        recipients = tuple(address for _name, address in getaddresses(message.get_all("To", [])))
        subject = str(make_header(decode_header(str(message.get("Subject") or "(sem assunto)"))))
        return EmailMessageRecord(
            reference=f"imap:{mailbox}:{uidvalidity}:{uid}",
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
        section = _first_text_section(repr(structure_data))
        if section is None:
            return ""
        status, body_data = client.uid(
            "fetch",
            uid,
            f"(BODY.PEEK[{section}]<0.{self.body_preview_chars}>)",
        )
        if status != "OK":
            return ""
        raw = _response_bytes(body_data)[: self.body_preview_chars]
        return raw.decode("utf-8", errors="replace").strip()

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


def _first_text_section(structure: str) -> str | None:
    """Select only a textual section; never fall back to a whole multipart body."""
    upper = structure.upper()
    if re.search(r"BODYSTRUCTURE\s+\(\s*['\"]TEXT['\"]", upper):
        return "TEXT"
    if re.search(r"BODYSTRUCTURE\s+\(\s*\(\s*['\"]TEXT['\"]", upper):
        return "1.TEXT"
    return None


def query_timezone_placeholder():
    from datetime import timezone

    return timezone.utc
