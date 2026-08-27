from __future__ import annotations

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models import Client, Lancamento, Proposal
from app.schemas import LancamentoCreate, LancamentoMove, LancamentoUpdate


TIPOS = {"receber", "pagar"}


def today() -> date:
    return date.today()


def _validate_tipo(tipo: str) -> None:
    if tipo not in TIPOS:
        raise ValueError("Tipo de lancamento invalido.")


def _validate_references(
    db: Session,
    client_id: int | None,
    proposal_id: int | None,
) -> None:
    if client_id is not None and db.get(Client, client_id) is None:
        raise ValueError("Cliente nao encontrado.")
    if proposal_id is not None and db.get(Proposal, proposal_id) is None:
        raise ValueError("Proposta nao encontrada.")


def _payment_date(status_value: str, supplied: date | None) -> date | None:
    if status_value == "pendente":
        return None
    return supplied or today()


def _supplier_for(tipo: str, supplied: str | None) -> str | None:
    if tipo != "pagar":
        return None
    return (supplied or "").strip() or None


def list_lancamentos(db: Session, tipo: str) -> list[Lancamento]:
    _validate_tipo(tipo)
    return (
        db.query(Lancamento)
        .options(
            joinedload(Lancamento.client),
            joinedload(Lancamento.proposal),
        )
        .filter(Lancamento.tipo == tipo)
        .order_by(Lancamento.data_vencimento.asc(), Lancamento.id.desc())
        .all()
    )


def get_lancamento(
    db: Session,
    lancamento_id: int,
    tipo: str | None = None,
) -> Lancamento:
    query = (
        db.query(Lancamento)
        .options(
            joinedload(Lancamento.client),
            joinedload(Lancamento.proposal),
        )
        .filter(Lancamento.id == lancamento_id)
    )
    if tipo is not None:
        _validate_tipo(tipo)
        query = query.filter(Lancamento.tipo == tipo)

    entry = query.first()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lancamento nao encontrado.",
        )
    return entry


def create_lancamento(db: Session, payload: LancamentoCreate) -> Lancamento:
    client_id = payload.client_id if payload.tipo == "receber" else None
    fornecedor = _supplier_for(payload.tipo, payload.fornecedor)
    _validate_references(db, client_id, payload.proposal_id)

    entry = Lancamento(
        tipo=payload.tipo,
        descricao=payload.descricao,
        client_id=client_id,
        proposal_id=payload.proposal_id,
        fornecedor=fornecedor,
        valor=payload.valor,
        data_emissao=payload.data_emissao,
        data_vencimento=payload.data_vencimento,
        status=payload.status,
        data_pagamento=_payment_date(payload.status, payload.data_pagamento),
    )
    db.add(entry)
    db.commit()
    return get_lancamento(db, entry.id)


def update_lancamento(
    db: Session,
    lancamento_id: int,
    tipo: str,
    payload: LancamentoUpdate,
) -> Lancamento:
    entry = get_lancamento(db, lancamento_id, tipo=tipo)
    client_id = payload.client_id if tipo == "receber" else None
    fornecedor = _supplier_for(tipo, payload.fornecedor)
    _validate_references(db, client_id, payload.proposal_id)

    entry.descricao = payload.descricao
    entry.client_id = client_id
    entry.proposal_id = payload.proposal_id
    entry.fornecedor = fornecedor
    entry.valor = payload.valor
    entry.data_emissao = payload.data_emissao
    entry.data_vencimento = payload.data_vencimento
    entry.status = payload.status
    entry.data_pagamento = _payment_date(payload.status, payload.data_pagamento)
    db.commit()
    return get_lancamento(db, entry.id)


def move_lancamento(
    db: Session,
    lancamento_id: int,
    payload: LancamentoMove,
) -> Lancamento:
    entry = get_lancamento(db, lancamento_id)
    entry.status = payload.status
    entry.data_pagamento = today() if payload.status == "pago" else None
    db.commit()
    return get_lancamento(db, entry.id)


def is_atrasado(entry: Lancamento, today_value: date) -> bool:
    return entry.status != "pago" and entry.data_vencimento < today_value
