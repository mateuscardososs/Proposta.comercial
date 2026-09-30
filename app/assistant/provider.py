from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from app.assistant.contracts import AssistantCommand


class ProviderMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    # User input remains capped at 4,000 characters by AssistantMessageRequest.
    # Internal system instructions and contextual envelopes need their own bound.
    content: str = Field(min_length=1, max_length=12000)


class ProviderUnavailableError(RuntimeError):
    pass


class ProviderResponseError(RuntimeError):
    pass


class AssistantProvider(Protocol):
    def interpret(
        self,
        messages: Sequence[ProviderMessage],
        *,
        today: date,
        timezone: str,
    ) -> AssistantCommand: ...
