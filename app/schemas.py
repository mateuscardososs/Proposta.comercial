from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


ProposalOrigin = Literal["sistema", "reupload_editado", "upload_externo"]
TaskStatus = Literal[
    "a_fazer",
    "em_andamento",
    "servico_feito_falta_nota_pedido",
    "aguardando_cliente",
    "concluido",
]
ServiceExecutionStatus = Literal["not_started", "in_progress", "completed"]
ServiceAdministrativeStatus = Literal["open", "closed"]
CorrectableServiceEventType = Literal[
    "call_received", "visit_started", "inspection", "execution_started",
    "execution_completed", "note",
]
ServiceEventType = Literal[
    "call_received", "visit_started", "inspection", "execution_started",
    "execution_completed", "note", "correction",
]
ServiceStepType = Literal["report", "proposal", "proposal_sent", "invoice", "receipt"]
ServiceStepStatus = Literal["unknown", "not_applicable", "pending", "waiting_customer", "completed"]


class ServiceStepChange(BaseModel):
    step_type: ServiceStepType
    status: ServiceStepStatus
    note: str = Field(default="", max_length=1000)


class ServiceEventCreate(BaseModel):
    client_id: int = Field(ge=1)
    service_call_id: int | None = Field(default=None, ge=1)
    force_new_call: bool = False
    summary: str = Field(min_length=1, max_length=500)
    event_type: ServiceEventType
    occurred_on: date
    description: str = Field(min_length=1, max_length=4000)
    step_changes: list[ServiceStepChange] = Field(default_factory=list, max_length=5)


class ServiceEventCorrectionCreate(BaseModel):
    service_call_id: int = Field(ge=1)
    supersedes_event_id: int = Field(ge=1)
    occurred_on: date
    reason: str = Field(min_length=1, max_length=1000)
    corrected_event_type: CorrectableServiceEventType | None = None
    corrected_occurred_on: date | None = None
    corrected_description: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def require_corrected_field(self) -> "ServiceEventCorrectionCreate":
        if not any((self.corrected_event_type, self.corrected_occurred_on, self.corrected_description)):
            raise ValueError("Informe ao menos um campo corrigido.")
        return self


class ServiceCallQuery(BaseModel):
    client_id: int | None = Field(default=None, ge=1)
    execution_status: ServiceExecutionStatus | None = None
    administrative_status: ServiceAdministrativeStatus | None = None
    pending_only: bool = False
    limit: int = Field(default=20, ge=1, le=50)


class ServiceReminderCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    status: TaskStatus = "a_fazer"
    due_date: date | None = None
    user_id: int | None = Field(default=None, ge=1)
    step_type: ServiceStepType | None = None


class ClientBase(BaseModel):
    razao_social: str
    cnpj: str = ""
    endereco_linha1: str = ""
    endereco_linha2: str = ""
    cep: str = ""
    cidade_uf: str = ""
    pais: str = "Brasil"
    caixa_postal: str = ""
    telefone: str = ""
    site: str = ""
    contato_padrao: str = ""


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    razao_social: str | None = None
    cnpj: str | None = None
    endereco_linha1: str | None = None
    endereco_linha2: str | None = None
    cep: str | None = None
    cidade_uf: str | None = None
    pais: str | None = None
    caixa_postal: str | None = None
    telefone: str | None = None
    site: str | None = None
    contato_padrao: str | None = None


class ClientRead(ORMModel, ClientBase):
    id: int
    created_at: datetime
    updated_at: datetime


class UserBase(BaseModel):
    nome: str
    cargo: str = ""
    email: str
    ativo: bool = True


class UserCreate(UserBase):
    senha: str = Field(min_length=4, default="123456")


class UserRead(ORMModel, UserBase):
    id: int
    created_at: datetime
    updated_at: datetime


class ProposalItemCreate(BaseModel):
    descricao: str
    unidade: str = "UN"
    qtd: Decimal = Decimal("0.00")
    valor_unit: Decimal = Decimal("0.00")


class ProposalItemRead(ORMModel):
    id: int
    ordem: int
    descricao: str
    unidade: str
    qtd: Decimal
    valor_unit: Decimal
    total: Decimal
    created_at: datetime


class ScheduleItemCreate(BaseModel):
    dia_label: str = ""
    descricao: str = ""
    horas_servico: str = ""


class ScheduleItemRead(ORMModel):
    id: int
    ordem: int
    dia_label: str
    descricao: str
    horas_servico: str
    created_at: datetime


class ProposalCreate(BaseModel):
    client_id: int
    user_id: int
    atencao: str = ""
    ref_cliente: str = ""
    objeto_tipo: str = "manutencao_calibracao"
    objeto_texto: str = ""
    canal: str = ""
    contato_nome: str = ""
    contato_datahora: str = ""
    equipamento_nome: str = ""
    equipamento_texto: str = ""
    local_servico: str = ""
    km_ida: Decimal = Decimal("0.00")
    km_volta: Decimal = Decimal("0.00")
    km_valor: Decimal = Decimal("2.95")
    alim_tecnicos: int = 1
    alim_refeicoes: int = 0
    alim_valor: Decimal = Decimal("0.00")
    condicao_pagamento_dias: int = 0
    imposto_percentual: Decimal = Decimal("0.00")
    itens: list[ProposalItemCreate] = Field(default_factory=list)
    schedule_items: list[ScheduleItemCreate] = Field(default_factory=list)


class ProposalRead(ORMModel):
    id: int
    numero: int
    revisao: str
    data_geracao: date
    origem: ProposalOrigin
    client_id: int
    user_id: int
    atencao: str
    ref_cliente: str
    objeto_tipo: str
    objeto_texto: str
    canal: str
    contato_nome: str
    contato_datahora: str
    equipamento_nome: str
    equipamento_texto: str
    local_servico: str
    km_ida: Decimal
    km_volta: Decimal
    km_total: Decimal
    km_valor: Decimal
    desloc_total: Decimal
    alim_tecnicos: int
    alim_refeicoes: int
    alim_valor: Decimal
    alim_total: Decimal
    condicao_pagamento_dias: int
    imposto_percentual: Decimal
    valor_total: Decimal
    docx_path: str
    pdf_path: str
    created_at: datetime
    updated_at: datetime
    items: list[ProposalItemRead] = Field(default_factory=list)
    schedule_items: list[ScheduleItemRead] = Field(default_factory=list)


class ProposalSummary(ORMModel):
    id: int
    numero: int
    revisao: str
    data_geracao: date
    origem: ProposalOrigin
    client_id: int
    user_id: int
    valor_total: Decimal
    condicao_pagamento_dias: int
    imposto_percentual: Decimal


class ProposalRecentSummary(BaseModel):
    id: int
    numero: int
    revisao: str
    data_geracao: date
    objeto_texto: str
    valor_total: Decimal
    responsavel_nome: str
    client_id: int


class ProposalCloneResponse(BaseModel):
    id: int
    numero: int
    revisao: str
    redirect_url: str


class WordReuploadPreviewResponse(BaseModel):
    filename: str
    valor_total: Decimal | None
    marker_found: bool
    warnings: list[str] = Field(default_factory=list)


class ExternalUploadPreviewResponse(BaseModel):
    filename: str
    file_type: Literal["docx", "pdf"]
    suggested_client_id: int | None = None
    suggested_client_name: str | None = None
    client_confidence: float | None = None
    suggested_valor_total: Decimal | None = None
    warnings: list[str] = Field(default_factory=list)


class ImportProposalItemPreview(BaseModel):
    descricao: str
    unidade: str
    qtd: Decimal
    valor_unit: Decimal


class ImportSchedulePreview(BaseModel):
    dia_label: str
    descricao: str
    horas_servico: str


class ImportProposalPreview(BaseModel):
    filename: str
    client_name: str
    atencao: str
    objeto_texto: str
    condicao_pagamento_dias: int
    imposto_percentual: Decimal
    items: list[ImportProposalItemPreview] = Field(default_factory=list)
    schedule_rows: list[ImportSchedulePreview] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    matched_client_id: int | None = None
    matched_client_name: str | None = None


class ImportProposalFileResult(BaseModel):
    filename: str
    success: bool
    message: str = ""
    proposal_id: int | None = None
    proposal_numero: int | None = None
    proposal_revisao: str | None = None
    preview: ImportProposalPreview | None = None


class ImportProposalsResponse(BaseModel):
    confirm: bool
    processed: int
    imported: int
    results: list[ImportProposalFileResult]


class TaskBase(BaseModel):
    titulo: str
    descricao: str = ""
    status: TaskStatus = "a_fazer"
    client_id: int | None = None
    client_name: str | None = Field(default=None, max_length=255)
    client_link_status: Literal["unlinked", "linked", "pending_review", "needs_confirmation"] = "unlinked"
    proposal_id: int | None = None
    user_id: int | None = None
    prazo: date | None = None


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    titulo: str | None = None
    descricao: str | None = None
    status: TaskStatus | None = None
    client_id: int | None = None
    client_name: str | None = Field(default=None, max_length=255)
    client_link_status: Literal["unlinked", "linked", "pending_review", "needs_confirmation"] | None = None
    proposal_id: int | None = None
    user_id: int | None = None
    prazo: date | None = None
    ordem: int | None = None


class TaskRead(ORMModel, TaskBase):
    id: int
    ordem: int
    created_at: datetime
    updated_at: datetime
    client: ClientRead | None = None
    proposal: ProposalSummary | None = None
    user: UserRead | None = None


class TaskMove(BaseModel):
    status: TaskStatus
    ordem: int


TipoLancamento = Literal["receber", "pagar"]
StatusLancamento = Literal["pendente", "pago"]
DescricaoLancamento = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
ValorLancamento = Annotated[
    Decimal,
    Field(gt=Decimal("0.00"), max_digits=14, decimal_places=2),
]


class LancamentoBase(BaseModel):
    descricao: DescricaoLancamento
    client_id: int | None = None
    proposal_id: int | None = None
    fornecedor: str | None = Field(default=None, max_length=255)
    valor: ValorLancamento
    data_emissao: date = Field(default_factory=date.today)
    data_vencimento: date
    status: StatusLancamento = "pendente"
    data_pagamento: date | None = None


class LancamentoCreate(LancamentoBase):
    tipo: TipoLancamento


class LancamentoUpdate(LancamentoBase):
    pass


class LancamentoRead(ORMModel, LancamentoBase):
    id: int
    tipo: TipoLancamento
    arquivado_em: date | None = None
    created_at: datetime
    updated_at: datetime
    client: ClientRead | None = None
    proposal: ProposalSummary | None = None


class LancamentoMove(BaseModel):
    status: StatusLancamento
