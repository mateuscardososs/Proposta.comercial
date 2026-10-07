from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from app.schemas import (
    ServiceAdministrativeStatus,
    ServiceEventType,
    ServiceExecutionStatus,
    ServiceStepStatus,
    ServiceStepType,
    TaskStatus,
)


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


class EmailQueryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["consultar_emails"] = "consultar_emails"
    period: Literal["today", "week", "custom"] = "today"
    start_date: str | None = Field(default=None, max_length=40)
    end_date: str | None = Field(default=None, max_length=40)
    unread_only: bool = False
    sender: str | None = Field(default=None, max_length=255)
    attention_only: bool = False
    awaiting_reply: bool = False
    reference: str | None = Field(default=None, max_length=160)
    category: Literal[
        "customer_quote_request", "vendor_quotation", "purchase_order", "invoice_request",
        "invoice_received", "accounts_payable", "accounts_receivable", "payment_proof",
        "service_request", "pending_reply", "informational", "other_review",
    ] | None = None
    limit: int = Field(default=20, ge=1, le=50)


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
    source_email_reference: str | None = Field(default=None, max_length=160)
    estimated_duration_minutes: int | None = Field(default=None, ge=1, le=1440)


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
        max_length=2400,
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
    estimated_duration_minutes: int | None = Field(default=None, ge=1, le=1440)

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
                self.estimated_duration_minutes is not None,
            )
        ):
            raise ValueError("Informe ao menos uma correcao para o rascunho.")
        return self


class ServiceQueryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["consultar_servicos"] = "consultar_servicos"
    client: str | None = Field(default=None, max_length=255)
    execution_status: ServiceExecutionStatus | None = None
    administrative_status: ServiceAdministrativeStatus | None = None
    pending_only: bool = False
    return_tasks_only: bool = False
    limit: int = Field(default=20, ge=1, le=50)


class ServiceStepChangeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_type: ServiceStepType
    status: ServiceStepStatus
    note: str = Field(default="", max_length=1000)


class ServiceEventDraftCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["registrar_evento_servico"] = "registrar_evento_servico"
    client: str | None = Field(default=None, max_length=255)
    service_call_id: int | None = Field(default=None, ge=1)
    force_new_call: bool = False
    summary: str | None = Field(default=None, max_length=500)
    event_type: ServiceEventType | None = None
    occurred_on: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=4000)
    equipment: str | None = Field(default=None, max_length=255)
    reported_problem: str | None = Field(default=None, max_length=1000)
    analysis: str | None = Field(default=None, max_length=1000)
    work_performed: str | None = Field(default=None, max_length=1000)
    return_on: str | None = Field(default=None, max_length=80)
    return_task_id: int | None = Field(default=None, ge=1)
    return_result: Literal["resolved", "still_pending"] | None = None
    execution_completed_explicitly: bool = False
    step_changes: list[ServiceStepChangeCommand] = Field(default_factory=list, max_length=5)


class ServiceDraftCorrectionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["corrigir_registro_servico"] = "corrigir_registro_servico"
    event_id: int | None = Field(default=None, ge=1)
    occurred_on: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=4000)
    equipment: str | None = Field(default=None, max_length=255)
    reported_problem: str | None = Field(default=None, max_length=1000)
    analysis: str | None = Field(default=None, max_length=1000)
    work_performed: str | None = Field(default=None, max_length=1000)
    return_on: str | None = Field(default=None, max_length=80)
    event_type: ServiceEventType | None = None
    client: str | None = Field(default=None, max_length=255)
    cancel_step_changes: bool = False


class ServiceReminderItemCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    status: TaskStatus = "a_fazer"
    due_date: str | None = Field(default=None, max_length=80)
    responsible: str | None = Field(default=None, max_length=120)
    step_type: ServiceStepType | None = None


class ServiceReminderDraftCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["criar_lembretes_servico"] = "criar_lembretes_servico"
    service_call_id: int | None = Field(default=None, ge=1)
    reminders: list[ServiceReminderItemCommand] = Field(min_length=1, max_length=5)


class PrepareServiceReportCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["preparar_relatorio_tecnico"] = "preparar_relatorio_tecnico"
    service_call_id: int | None = Field(default=None, ge=1)
    client: str | None = Field(default=None, max_length=255)
    reference: str | None = Field(default=None, max_length=255)


class CorrectServiceReportCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["corrigir_previa_relatorio_tecnico"] = "corrigir_previa_relatorio_tecnico"
    client_name: str | None = Field(default=None, max_length=255)
    client_cnpj: str | None = Field(default=None, max_length=32)
    client_phone: str | None = Field(default=None, max_length=50)
    client_address: str | None = Field(default=None, max_length=1000)
    equipment: str | None = Field(default=None, max_length=1000)
    completion_date: str | None = Field(default=None, max_length=10)
    reported_problem: str | None = Field(default=None, max_length=4000)
    analysis: str | None = Field(default=None, max_length=4000)
    work_performed: str | None = Field(default=None, max_length=4000)
    verification_result: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def require_change(self) -> CorrectServiceReportCommand:
        if not any(getattr(self, name) is not None for name in type(self).model_fields if name != "tool"):
            raise ValueError("Informe ao menos um campo para corrigir a prévia.")
        return self


AssistantCommand = Annotated[
    TaskQueryCommand
    | EmailQueryCommand
    | TaskCreateCommand
    | UnsupportedCommand
    | ConversationCommand
    | ConfirmActionCommand
    | CancelActionCommand
    | TaskDraftCorrectionCommand
    | ServiceQueryCommand
    | ServiceEventDraftCommand
    | ServiceDraftCorrectionCommand
    | ServiceReminderDraftCommand
    | PrepareServiceReportCommand
    | CorrectServiceReportCommand,
    Field(discriminator="tool"),
]
assistant_command_adapter = TypeAdapter(AssistantCommand)


class AssistantReply(BaseModel):
    conversation_id: int
    kind: Literal["text", "confirmation", "clarification", "success", "error"]
    message: str
    retryable: bool = False
    action_id: int | None = None
    confirmation_token: str | None = None
    task_id: int | None = None
    task_url: str | None = None
    task_urls: list[str] = Field(default_factory=list)
    service_call_id: int | None = None
    service_url: str | None = None
    proposal_url: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)
    email_items: list[dict[str, object]] = Field(default_factory=list)
    consulted_interval: str | None = None
    limitations: list[str] = Field(default_factory=list)
    report_fields: dict[str, str] = Field(default_factory=dict)
    report_field_labels: dict[str, str] = Field(default_factory=dict)
    report_missing_fields: list[str] = Field(default_factory=list)
    report_candidates: list[dict[str, object]] = Field(default_factory=list)
    report_id: int | None = None
    report_docx_url: str | None = None
    report_pdf_url: str | None = None


class AssistantReportPreviewEditRequest(BaseModel):
    confirmation_token: str = Field(min_length=20, max_length=100)
    fields: dict[str, str]


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
    retry: bool = False
    source: Literal["text", "voice"] = "text"


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
    confidence_score: float = Field(default=0, ge=0, le=1)
    audio_duration_seconds: float = Field(gt=0)
    transcription_seconds: float = Field(ge=0)
    queue_wait_seconds: float = Field(default=0, ge=0)
    total_seconds: float = Field(default=0, ge=0)


class VoiceSpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    kind: Literal["text", "confirmation", "clarification", "success", "error"] = "text"
