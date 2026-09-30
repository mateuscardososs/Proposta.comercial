from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from app.schemas import TaskStatus


class TaskQueryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["consultar_tarefas"] = "consultar_tarefas"
    status: TaskStatus | None = Field(default=None, description="Status exato, se citado.")
    client: str | None = Field(
        default=None, max_length=255, description="Nome do cliente como foi falado."
    )
    responsible: str | None = Field(
        default=None, max_length=120, description="Nome do responsavel como foi falado."
    )
    overdue_only: bool = Field(
        default=False, description="Use true somente quando o usuario pedir tarefas atrasadas."
    )
    due_before: str | None = Field(
        default=None,
        max_length=80,
        description="Limite de prazo citado; preserve expressoes como hoje ou esta semana.",
    )
    priorities: bool = Field(default=False, description="Use true se pedir prioridades.")
    include_completed: bool = Field(
        default=False, description="Inclua concluidas apenas se solicitado explicitamente."
    )
    limit: int = Field(default=20, ge=1, le=50, description="Quantidade maxima de resultados.")


class TaskCreateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["criar_tarefa"] = "criar_tarefa"
    title: str | None = Field(
        default=None, max_length=255, description="Titulo curto extraido do pedido."
    )
    description: str = Field(default="", max_length=4000)
    status: TaskStatus = "a_fazer"
    due_date: str | None = Field(
        default=None,
        max_length=80,
        description="Prazo como foi falado; preserve amanha, sexta e depois de amanha.",
    )
    client: str | None = Field(
        default=None, max_length=255, description="Nome do cliente como foi falado."
    )
    responsible: str | None = Field(
        default=None, max_length=120, description="Nome do responsavel como foi falado."
    )
    proposal_number: int | None = Field(default=None, ge=1)


class UnsupportedCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["fora_do_escopo"] = "fora_do_escopo"
    message: str = Field(
        min_length=1,
        max_length=500,
        description="Explique que a acao nao foi executada e indique o limite aplicavel.",
    )


class ConversationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["responder_conversa"] = "responder_conversa"
    message: str = Field(
        min_length=1,
        max_length=800,
        description=(
            "Resposta natural em portugues, sem alegar consultas ou alteracoes que nao ocorreram."
        ),
    )


class ConfirmActionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["confirmar_acao"] = "confirmar_acao"


class CancelActionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["cancelar_acao"] = "cancelar_acao"


class TaskDraftCorrectionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["corrigir_tarefa"] = "corrigir_tarefa"
    title: str | None = Field(
        default=None, max_length=255, description="Novo titulo, somente se corrigido."
    )
    due_date: str | None = Field(
        default=None,
        max_length=80,
        description="Novo prazo como foi falado, somente se corrigido.",
    )
    client: str | None = Field(
        default=None, max_length=255, description="Novo cliente, somente se corrigido."
    )
    responsible: str | None = Field(
        default=None, max_length=120, description="Novo responsavel, somente se corrigido."
    )
    clear_due_date: bool = False
    clear_client: bool = False
    clear_responsible: bool = False

    @model_validator(mode="after")
    def require_change(self) -> TaskDraftCorrectionCommand:
        if not any(
            (
                self.title is not None,
                self.due_date is not None,
                self.client is not None,
                self.responsible is not None,
                self.clear_due_date,
                self.clear_client,
                self.clear_responsible,
            )
        ):
            raise ValueError("Informe ao menos uma correcao para o rascunho.")
        return self


AssistantCommand = Annotated[
    TaskQueryCommand
    | TaskCreateCommand
    | UnsupportedCommand
    | ConversationCommand
    | ConfirmActionCommand
    | CancelActionCommand
    | TaskDraftCorrectionCommand,
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


class VoiceStatus(BaseModel):
    enabled: bool
    text_available: bool = True
    transcription_available: bool
    synthesis_available: bool
    message: str
    max_duration_seconds: float = Field(gt=0)
    max_upload_bytes: int = Field(gt=0)
    silence_ms: int = Field(gt=0)
    idle_timeout_seconds: int = Field(gt=0)


class VoiceTranscriptionResponse(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    language: str = Field(max_length=20)
    language_probability: float = Field(ge=0, le=1)
    audio_duration_seconds: float = Field(gt=0)
    transcription_seconds: float = Field(ge=0)


class VoiceSpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    kind: Literal["text", "confirmation", "clarification", "success", "error"] = "text"
