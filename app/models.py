from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
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


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    cargo: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    proposals: Mapped[list["Proposal"]] = relationship(back_populates="user")


class Proposal(Base, TimestampMixin):
    __tablename__ = "proposals"
    __table_args__ = (UniqueConstraint("numero", "revisao", name="uq_proposal_numero_revisao"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    numero: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    revisao: Mapped[str] = mapped_column(String(2), nullable=False, default="00")
    data_geracao: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)

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
