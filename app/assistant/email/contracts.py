from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


EmailResultState = Literal[
    "not_implemented",
    "not_configured",
    "failed",
    "empty",
    "success",
    "partial",
    "stale",
]
EmailPriority = Literal["low", "normal", "high", "critical"]
AwaitingReply = Literal["yes", "no", "unknown"]


class EmailQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_at: datetime
    end_at: datetime
    unread_only: bool = False
    sender: str | None = Field(default=None, max_length=255)
    attention_only: bool = False
    awaiting_reply: bool = False
    reference: str | None = Field(default=None, max_length=160)
    limit: int = Field(default=20, ge=1, le=100)


class EmailMessageRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: str = Field(max_length=160)
    thread_reference: str = Field(max_length=500)
    folder_role: Literal["inbox", "sent", "other"]
    sender: str = Field(max_length=500)
    recipients: tuple[str, ...] = ()
    subject: str = Field(max_length=500)
    received_at: datetime
    seen: bool
    text: str = Field(default="", max_length=12000)


class EmailMessageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str = Field(max_length=160)
    sender: str = Field(max_length=500)
    subject: str = Field(max_length=500)
    received_at: datetime
    seen: bool
    summary: str = Field(max_length=400)
    priority: EmailPriority
    priority_reason: str
    action_suggested: str | None = None
    explicit_deadline: str | None = None
    inferred_deadline: str | None = None
    awaiting_reply: AwaitingReply = "unknown"
    evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class EmailQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: EmailResultState
    provider: str
    interval_start: datetime
    interval_end: datetime
    messages: list[EmailMessageResult] = Field(default_factory=list)
    candidate_count: int = Field(default=0, ge=0)
    applied_filters: list[str] = Field(default_factory=list)
    sent_available: bool = False
    partial: bool = False
    stale: bool = False
    limitations: list[str] = Field(default_factory=list)
    user_message: str = ""
