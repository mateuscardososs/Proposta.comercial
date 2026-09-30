from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.schemas import TaskStatus


class TaskQueryCommand(BaseModel):
    tool: Literal["consultar_tarefas"] = "consultar_tarefas"
    status: TaskStatus | None = None
    client: str | None = Field(default=None, max_length=255)
    responsible: str | None = Field(default=None, max_length=120)
    overdue_only: bool = False
    due_before: str | None = Field(default=None, max_length=80)
    priorities: bool = False
    include_completed: bool = False
    limit: int = Field(default=20, ge=1, le=50)


class TaskCreateCommand(BaseModel):
    tool: Literal["criar_tarefa"] = "criar_tarefa"
    title: str | None = Field(default=None, max_length=255)
    description: str = Field(default="", max_length=4000)
    status: TaskStatus = "a_fazer"
    due_date: str | None = Field(default=None, max_length=80)
    client: str | None = Field(default=None, max_length=255)
    responsible: str | None = Field(default=None, max_length=120)
    proposal_number: int | None = Field(default=None, ge=1)


class UnsupportedCommand(BaseModel):
    tool: Literal["fora_do_escopo"] = "fora_do_escopo"
    message: str = Field(min_length=1, max_length=500)


AssistantCommand = Annotated[
    TaskQueryCommand | TaskCreateCommand | UnsupportedCommand,
    Field(discriminator="tool"),
]
assistant_command_adapter = TypeAdapter(AssistantCommand)


class AssistantReply(BaseModel):
    conversation_id: int
    kind: Literal["text", "confirmation", "clarification", "success", "error"]
    message: str
    action_id: int | None = None
    confirmation_token: str | None = None
    task_id: int | None = None
    task_url: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)


class AssistantMessageView(BaseModel):
    role: Literal["user", "assistant"]
    kind: str
    content: str
    created_at: str
    details: dict[str, object] = Field(default_factory=dict)


class AssistantMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    request_id: str = Field(min_length=1, max_length=100)
    conversation_id: int | None = Field(default=None, ge=1)


class AssistantHistory(BaseModel):
    conversation_id: int
    messages: list[AssistantMessageView]


class AssistantConfirmationRequest(BaseModel):
    confirmation_token: str = Field(min_length=20, max_length=100)
