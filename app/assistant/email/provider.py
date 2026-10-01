from __future__ import annotations

from typing import Protocol

from app.assistant.email.contracts import EmailQuery, EmailQueryResult


class EmailProviderError(RuntimeError):
    pass


class EmailAuthenticationError(EmailProviderError):
    pass


class EmailTimeoutError(EmailProviderError):
    pass


class EmailUnavailableError(EmailProviderError):
    pass


class EmailReader(Protocol):
    def query(self, query: EmailQuery) -> EmailQueryResult: ...

