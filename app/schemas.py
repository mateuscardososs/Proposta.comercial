from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


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
