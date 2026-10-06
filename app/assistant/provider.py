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


class ProviderToolResult(BaseModel):
    tool: Literal["consultar_tarefas", "consultar_emails", "consultar_servicos"]
    evidence_id: str | None = None
    state: Literal["success", "empty", "partial", "stale", "failed"] = "success"
    payload: dict[str, object]


class ProviderPendingAction(BaseModel):
    action_type: Literal[
        "create_task", "register_service_event", "correct_service_event", "create_service_reminders"
    ]
    status: Literal["pending", "needs_clarification"]
    arguments: dict[str, object]


class ProviderInferenceTrace(BaseModel):
    """Audit-safe measurements for one local model inference."""

    attempt: int = Field(ge=1)
    queue_wait_seconds: float = Field(ge=0)
    request_seconds: float = Field(ge=0)
    ollama_total_seconds: float | None = Field(default=None, ge=0)
    model_load_seconds: float | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    prompt_eval_seconds: float | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    output_eval_seconds: float | None = Field(default=None, ge=0)
    context_messages: int = Field(ge=0)
    context_characters: int = Field(ge=0)
    tool_schema_characters: int = Field(ge=0)
    tool_result_count: int = Field(ge=0)
    outcome: str | None = Field(default=None, max_length=80)
    repair_reason: str | None = Field(default=None, max_length=80)
    grounding_adjustment: str | None = Field(default=None, max_length=80)
    provider: Literal["ollama", "gemini"] = "ollama"


class ProviderInterpretation(BaseModel):
    command: AssistantCommand
    inferences: list[ProviderInferenceTrace] = Field(default_factory=list)


class ProviderUnavailableError(RuntimeError):
    pass


class ProviderConnectionError(ProviderUnavailableError):
    """The local provider cannot be reached or returned a service-level error."""


class ProviderModelUnavailableError(ProviderUnavailableError):
    """The provider is reachable but the configured local model is absent."""


class ProviderTimeoutError(ProviderUnavailableError):
    """A request to the local provider exceeded its configured timeout."""


class ProviderAuthenticationError(ProviderUnavailableError):
    """The remote provider rejected its credential or account authorization."""


class ProviderRateLimitError(ProviderUnavailableError):
    """The provider rejected a request because of quota or rate limits."""


class ProviderResponseError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        inferences: Sequence[ProviderInferenceTrace] = (),
    ) -> None:
        super().__init__(message)
        self.inferences = tuple(inferences)


class AssistantProvider(Protocol):
    def interpret(
        self,
        messages: Sequence[ProviderMessage],
        *,
        today: date,
        timezone: str,
        tool_results: Sequence[ProviderToolResult] = (),
        pending_action: ProviderPendingAction | None = None,
        allowed_tools: set[str] | None = None,
    ) -> AssistantCommand: ...
