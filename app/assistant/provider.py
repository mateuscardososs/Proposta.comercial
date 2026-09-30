from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from app.assistant.contracts import AssistantCommand


class ProviderMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


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
