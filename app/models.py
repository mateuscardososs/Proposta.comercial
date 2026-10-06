from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class Client(Base, TimestampMixin):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    razao_social: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    cnpj: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    endereco_linha1: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    endereco_linha2: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    cep: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    cidade_uf: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    pais: Mapped[str] = mapped_column(String(80), default="Brasil", nullable=False)
    caixa_postal: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    telefone: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    site: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    contato_padrao: Mapped[str] = mapped_column(String(120), default="", nullable=False)

    proposals: Mapped[list["Proposal"]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    cargo: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    proposals: Mapped[list["Proposal"]] = relationship(back_populates="user")
    tasks: Mapped[list["Task"]] = relationship(back_populates="user")


class Proposal(Base, TimestampMixin):
    __tablename__ = "proposals"
    __table_args__ = (UniqueConstraint("numero", "revisao", name="uq_proposal_numero_revisao"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    numero: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    revisao: Mapped[str] = mapped_column(String(2), nullable=False, default="00")
    data_geracao: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    origem: Mapped[str] = mapped_column(
        String(30),
        default="sistema",
        server_default="sistema",
        nullable=False,
    )

    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    atencao: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    ref_cliente: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    objeto_tipo: Mapped[str] = mapped_column(String(40), default="manutencao_calibracao", nullable=False)
    objeto_texto: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    canal: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    contato_nome: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    contato_datahora: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    equipamento_nome: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    equipamento_texto: Mapped[str] = mapped_column(Text, default="", nullable=False)
    local_servico: Mapped[str] = mapped_column(String(200), default="", nullable=False)

    km_ida: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    km_volta: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    km_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    km_valor: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("2.95"), nullable=False)
    desloc_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)

    alim_tecnicos: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    alim_refeicoes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    alim_valor: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    alim_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    condicao_pagamento_dias: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imposto_percentual: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=Decimal("0.00"), nullable=False)

    valor_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    docx_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    pdf_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)

    client: Mapped[Client] = relationship(back_populates="proposals")
    user: Mapped[User] = relationship(back_populates="proposals")
    items: Mapped[list["ProposalItem"]] = relationship(
        back_populates="proposal",
        cascade="all, delete-orphan",
        order_by="ProposalItem.ordem",
    )
    schedule_items: Mapped[list["ProposalScheduleItem"]] = relationship(
        back_populates="proposal",
        cascade="all, delete-orphan",
        order_by="ProposalScheduleItem.ordem",
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="proposal",
        cascade="all, delete-orphan",
    )


class ProposalItem(Base):
    __tablename__ = "proposal_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id"), nullable=False, index=True)
    ordem: Mapped[int] = mapped_column(Integer, nullable=False)
    descricao: Mapped[str] = mapped_column(String(255), nullable=False)
    unidade: Mapped[str] = mapped_column(String(30), default="UN", nullable=False)
    qtd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    valor_unit: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    proposal: Mapped[Proposal] = relationship(back_populates="items")


class ProposalScheduleItem(Base):
    __tablename__ = "proposal_schedule_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id"), nullable=False, index=True)
    ordem: Mapped[int] = mapped_column(Integer, nullable=False)
    dia_label: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    descricao: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    horas_servico: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    proposal: Mapped[Proposal] = relationship(back_populates="schedule_items")


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    titulo: Mapped[str] = mapped_column(String(255), nullable=False)
    descricao: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="a_fazer", nullable=False)

    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_link_status: Mapped[str] = mapped_column(String(30), default="unlinked", nullable=False)
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("proposals.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    prazo: Mapped[date | None] = mapped_column(Date, nullable=True)
    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ordem: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    client: Mapped[Client | None] = relationship(back_populates="tasks")
    proposal: Mapped[Proposal | None] = relationship(back_populates="tasks")
    user: Mapped[User | None] = relationship(back_populates="tasks")


class DailySchedulePreference(Base, TimestampMixin):
    __tablename__ = "daily_schedule_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    default_task_duration_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)


class WorkAvailabilityWindow(Base, TimestampMixin):
    __tablename__ = "work_availability_windows"
    __table_args__ = (
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_work_window_weekday"),
        CheckConstraint("start_time < end_time", name="ck_work_window_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    label: Mapped[str] = mapped_column(String(120), default="Expediente", nullable=False)


class FixedCommitment(Base, TimestampMixin):
    __tablename__ = "fixed_commitments"
    __table_args__ = (
        CheckConstraint(
            "(occurrence_type = 'weekly' AND weekday IS NOT NULL AND commitment_date IS NULL) OR "
            "(occurrence_type = 'dated' AND weekday IS NULL AND commitment_date IS NOT NULL)",
            name="ck_commitment_occurrence_target",
        ),
        CheckConstraint("start_time < end_time", name="ck_commitment_positive"),
        CheckConstraint("weekday IS NULL OR (weekday >= 0 AND weekday <= 6)", name="ck_commitment_weekday"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    occurrence_type: Mapped[str] = mapped_column(String(20), nullable=False)
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commitment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)


class DailyScheduleSnapshot(Base):
    __tablename__ = "daily_schedule_snapshots"
    __table_args__ = (
        UniqueConstraint("assistant_action_id", name="uq_daily_schedule_action"),
        UniqueConstraint("idempotency_key", name="uq_daily_schedule_idempotency_key"),
        UniqueConstraint("schedule_date", "version", name="uq_daily_schedule_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    assistant_action_id: Mapped[int] = mapped_column(
        ForeignKey("assistant_actions.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AssistantConversation(Base, TimestampMixin):
    __tablename__ = "assistant_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    messages: Mapped[list["AssistantMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AssistantMessage.id",
    )
    actions: Mapped[list["AssistantAction"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AssistantAction.id",
    )


class AssistantRequest(Base, TimestampMixin):
    __tablename__ = "assistant_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    request_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_message_id: Mapped[int] = mapped_column(
        ForeignKey("assistant_messages.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    reply_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("assistant_messages.id", ondelete="SET NULL"),
        unique=True,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), default="text", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    reply_to_request_id: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
    )
    details_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    conversation: Mapped[AssistantConversation] = relationship(back_populates="messages")


class AssistantAction(Base, TimestampMixin):
    __tablename__ = "assistant_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    confirmation_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    arguments_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    result_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"),
        unique=True,
        nullable=True,
        index=True,
    )

    conversation: Mapped[AssistantConversation] = relationship(back_populates="actions")
    task: Mapped[Task | None] = relationship()


class AssistantEmailTaskLink(Base, TimestampMixin):
    __tablename__ = "assistant_email_task_links"
    __table_args__ = (UniqueConstraint("task_id", "email_reference"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    email_reference: Mapped[str] = mapped_column(String(160), nullable=False, index=True)

    task: Mapped[Task] = relationship()


class InboxEmail(Base, TimestampMixin):
    """Minimal persisted projection of a message; the full body is never stored."""

    __tablename__ = "inbox_emails"
    __table_args__ = (UniqueConstraint("provider", "mailbox_key", "reference", name="uq_inbox_email_origin"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    mailbox_key: Mapped[str] = mapped_column(String(160), nullable=False)
    reference: Mapped[str] = mapped_column(String(160), nullable=False)
    thread_reference: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    sender: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    subject: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    seen: Mapped[bool] = mapped_column(Boolean, nullable=False)
    awaiting_reply: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    sent_coverage: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    summary: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    category: Mapped[str] = mapped_column(String(40), default="other_review", nullable=False, index=True)
    confidence_band: Mapped[str] = mapped_column(String(20), default="low", nullable=False)
    destination: Mapped[str] = mapped_column(String(30), default="review", nullable=False)
    classification_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    explicit_deadline: Mapped[str | None] = mapped_column(String(20), nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EmailTaskLink(Base, TimestampMixin):
    __tablename__ = "email_task_links"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "mailbox_key",
            "reference",
            "action_type",
            name="uq_email_task_origin_action",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    mailbox_key: Mapped[str] = mapped_column(String(160), nullable=False)
    reference: Mapped[str] = mapped_column(String(160), nullable=False)
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    task_title_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)


class EmailSyncState(Base, TimestampMixin):
    __tablename__ = "email_sync_states"
    __table_args__ = (UniqueConstraint("provider", "mailbox_key", name="uq_email_sync_mailbox"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    mailbox_key: Mapped[str] = mapped_column(String(160), nullable=False)
    paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    activation_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Lancamento(Base, TimestampMixin):
    __tablename__ = "lancamentos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    descricao: Mapped[str] = mapped_column(String(255), nullable=False)

    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    proposal_id: Mapped[int | None] = mapped_column(
        ForeignKey("proposals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    fornecedor: Mapped[str | None] = mapped_column(String(255), nullable=True)

    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    data_emissao: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    data_vencimento: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pendente", nullable=False, index=True)
    data_pagamento: Mapped[date | None] = mapped_column(Date, nullable=True)
    arquivado_em: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    client: Mapped[Client | None] = relationship()
    proposal: Mapped[Proposal | None] = relationship()


class LancamentoHistorico(Base):
    """Append-only audit trail for explicit and automatic financial transitions."""

    __tablename__ = "lancamento_historicos"
    __table_args__ = (
        UniqueConstraint("lancamento_id", "event_key", name="uq_lancamento_historico_event_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lancamento_id: Mapped[int] = mapped_column(
        ForeignKey("lancamentos.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_key: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status_anterior: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status_novo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    data_emissao_anterior: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_emissao_nova: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_vencimento_anterior: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_vencimento_nova: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_pagamento_anterior: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_pagamento_nova: Mapped[date | None] = mapped_column(Date, nullable=True)
    arquivado_em_anterior: Mapped[date | None] = mapped_column(Date, nullable=True)
    arquivado_em_novo: Mapped[date | None] = mapped_column(Date, nullable=True)
    acao_confirmada: Mapped[str] = mapped_column(String(80), nullable=False)
    observacao: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ServiceCall(Base, TimestampMixin):
    __tablename__ = "service_calls"
    __table_args__ = (
        CheckConstraint(
            "execution_status IN ('not_started', 'in_progress', 'completed')",
            name="ck_service_call_execution_status",
        ),
        CheckConstraint(
            "administrative_status IN ('open', 'closed')",
            name="ck_service_call_administrative_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    opened_on: Mapped[date] = mapped_column(Date, nullable=False)
    execution_status: Mapped[str] = mapped_column(String(30), default="not_started", nullable=False)
    administrative_status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    technically_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    administratively_closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    client: Mapped[Client] = relationship()
    conversation: Mapped[AssistantConversation | None] = relationship()
    events: Mapped[list["ServiceEvent"]] = relationship(
        back_populates="service_call",
        cascade="save-update, merge",
        passive_deletes=True,
        foreign_keys="ServiceEvent.service_call_id",
        order_by="ServiceEvent.id",
    )
    workflow_steps: Mapped[list["ServiceWorkflowStep"]] = relationship(
        back_populates="service_call",
        cascade="save-update, merge",
        passive_deletes=True,
        order_by="ServiceWorkflowStep.id",
    )
    workflow_transitions: Mapped[list["ServiceWorkflowTransition"]] = relationship(
        back_populates="service_call",
        cascade="save-update, merge",
        passive_deletes=True,
        foreign_keys="ServiceWorkflowTransition.service_call_id",
        order_by="ServiceWorkflowTransition.id",
    )
    task_links: Mapped[list["ServiceTaskLink"]] = relationship(
        back_populates="service_call",
        cascade="save-update, merge",
        passive_deletes=True,
        order_by="ServiceTaskLink.id",
    )


class ServiceEvent(Base):
    __tablename__ = "service_events"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "service_call_id",
            "assistant_action_id",
            name="uq_service_event_call_action",
        ),
        CheckConstraint(
            "event_type IN ('call_received', 'visit_started', 'inspection', 'execution_started', 'execution_completed', 'note', 'correction')",
            name="ck_service_event_type",
        ),
        CheckConstraint(
            "event_type = 'correction' OR (supersedes_event_id IS NULL AND correction_reason IS NULL "
            "AND corrected_event_type IS NULL AND corrected_occurred_on IS NULL "
            "AND corrected_description IS NULL)",
            name="ck_service_event_correction_fields",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_call_id: Mapped[int] = mapped_column(ForeignKey("service_calls.id", ondelete="RESTRICT"), nullable=False, index=True)
    assistant_action_id: Mapped[int] = mapped_column(
        ForeignKey("assistant_actions.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    supersedes_event_id: Mapped[int | None] = mapped_column(ForeignKey("service_events.id", ondelete="RESTRICT"), unique=True, nullable=True)
    correction_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    corrected_event_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    corrected_occurred_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    corrected_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    service_call: Mapped[ServiceCall] = relationship(back_populates="events", foreign_keys=[service_call_id])
    assistant_action: Mapped[AssistantAction] = relationship()
    conversation: Mapped[AssistantConversation | None] = relationship()
    supersedes_event: Mapped["ServiceEvent | None"] = relationship(remote_side=[id], foreign_keys=[supersedes_event_id])


class ServiceWorkflowStep(Base, TimestampMixin):
    __tablename__ = "service_workflow_steps"
    __table_args__ = (
        UniqueConstraint("service_call_id", "step_type", name="uq_service_workflow_step_call_type"),
        CheckConstraint(
            "step_type IN ('report', 'proposal', 'proposal_sent', 'invoice', 'receipt')",
            name="ck_service_workflow_step_type",
        ),
        CheckConstraint(
            "status IN ('unknown', 'not_applicable', 'pending', 'waiting_customer', 'completed')",
            name="ck_service_workflow_step_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_call_id: Mapped[int] = mapped_column(ForeignKey("service_calls.id", ondelete="RESTRICT"), nullable=False, index=True)
    step_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)

    service_call: Mapped[ServiceCall] = relationship(back_populates="workflow_steps")


class ServiceWorkflowTransition(Base):
    __tablename__ = "service_workflow_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["service_call_id", "step_type"],
            [
                "service_workflow_steps.service_call_id",
                "service_workflow_steps.step_type",
            ],
            ondelete="RESTRICT",
            name="fk_service_transition_step",
        ),
        ForeignKeyConstraint(
            ["service_event_id", "service_call_id", "assistant_action_id"],
            [
                "service_events.id",
                "service_events.service_call_id",
                "service_events.assistant_action_id",
            ],
            ondelete="RESTRICT",
            name="fk_service_transition_event_call_action",
        ),
        UniqueConstraint("assistant_action_id", "step_type", name="uq_service_transition_action_step"),
        CheckConstraint("previous_status <> new_status", name="ck_service_transition_changes_status"),
        CheckConstraint(
            "previous_status IN ('unknown', 'not_applicable', 'pending', 'waiting_customer', 'completed')",
            name="ck_service_transition_previous_status",
        ),
        CheckConstraint(
            "new_status IN ('unknown', 'not_applicable', 'pending', 'waiting_customer', 'completed')",
            name="ck_service_transition_new_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_call_id: Mapped[int] = mapped_column(ForeignKey("service_calls.id", ondelete="RESTRICT"), nullable=False, index=True)
    step_type: Mapped[str] = mapped_column(String(30), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(30), nullable=False)
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    observation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    service_event_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    assistant_action_id: Mapped[int] = mapped_column(
        ForeignKey("assistant_actions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    service_call: Mapped[ServiceCall] = relationship(
        back_populates="workflow_transitions",
        foreign_keys=[service_call_id],
        overlaps="service_event",
    )
    service_event: Mapped[ServiceEvent] = relationship(
        foreign_keys=[service_event_id, service_call_id, assistant_action_id],
        overlaps="service_call,workflow_transitions",
    )
    assistant_action: Mapped[AssistantAction] = relationship(foreign_keys=[assistant_action_id], overlaps="service_event")
    workflow_step: Mapped[ServiceWorkflowStep] = relationship(
        foreign_keys=[service_call_id, step_type],
        overlaps="service_call,workflow_transitions,service_event",
    )


class ServiceTaskLink(Base, TimestampMixin):
    __tablename__ = "service_task_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["service_call_id", "step_type"],
            [
                "service_workflow_steps.service_call_id",
                "service_workflow_steps.step_type",
            ],
            ondelete="RESTRICT",
            name="fk_service_task_link_step",
        ),
        UniqueConstraint("task_id", name="uq_service_task_link_task"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_call_id: Mapped[int] = mapped_column(ForeignKey("service_calls.id", ondelete="RESTRICT"), nullable=False, index=True)
    step_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    service_event_id: Mapped[int | None] = mapped_column(ForeignKey("service_events.id", ondelete="RESTRICT"), nullable=True, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    assistant_action_id: Mapped[int] = mapped_column(
        ForeignKey("assistant_actions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    service_call: Mapped[ServiceCall] = relationship(back_populates="task_links", foreign_keys=[service_call_id])
    workflow_step: Mapped[ServiceWorkflowStep | None] = relationship(foreign_keys=[service_call_id, step_type], overlaps="service_call,task_links")
    service_event: Mapped[ServiceEvent | None] = relationship()
    task: Mapped[Task | None] = relationship()
    assistant_action: Mapped[AssistantAction] = relationship()
