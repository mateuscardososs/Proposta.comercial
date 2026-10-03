from __future__ import annotations

from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models import Client, Lancamento, LancamentoHistorico, Proposal
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


def _snapshot(entry: Lancamento) -> dict[str, object]:
    return {
        "status": entry.status,
        "data_emissao": entry.data_emissao,
        "data_vencimento": entry.data_vencimento,
        "data_pagamento": entry.data_pagamento,
        "arquivado_em": entry.arquivado_em,
    }


def _record_transition(
    db: Session,
    entry: Lancamento,
    before: dict[str, object],
    *,
    event_type: str,
    action: str,
    observation: str = "",
) -> None:
    after = _snapshot(entry)
    if before == after and event_type != "created":
        return
    latest_id = (
        db.query(LancamentoHistorico.id)
        .filter(LancamentoHistorico.lancamento_id == entry.id)
        .order_by(LancamentoHistorico.id.desc())
        .limit(1)
        .scalar()
    )
    db.add(
        LancamentoHistorico(
            lancamento_id=entry.id,
            event_key=f"{action}:{latest_id or 'initial'}",
            event_type=event_type,
            status_anterior=before["status"],
            status_novo=after["status"],
            data_emissao_anterior=before["data_emissao"],
            data_emissao_nova=after["data_emissao"],
            data_vencimento_anterior=before["data_vencimento"],
            data_vencimento_nova=after["data_vencimento"],
            data_pagamento_anterior=before["data_pagamento"],
            data_pagamento_nova=after["data_pagamento"],
            arquivado_em_anterior=before["arquivado_em"],
            arquivado_em_novo=after["arquivado_em"],
            acao_confirmada=action,
            observacao=observation,
        )
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
    db.flush()
    _record_transition(
        db,
        entry,
        {
            "status": None,
            "data_emissao": None,
            "data_vencimento": None,
            "data_pagamento": None,
            "arquivado_em": None,
        },
        event_type="created",
        action="manual_ui_create",
    )
    db.commit()
    return get_lancamento(db, entry.id)


def update_lancamento(
    db: Session,
    lancamento_id: int,
    tipo: str,
    payload: LancamentoUpdate,
) -> Lancamento:
    entry = get_lancamento(db, lancamento_id, tipo=tipo)
    if entry.arquivado_em is not None:
        raise HTTPException(status_code=409, detail="Lancamento arquivado e somente para consulta.")
    before = _snapshot(entry)
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
    entry.data_pagamento = (
        None
        if payload.status == "pendente"
        else payload.data_pagamento
        or (before["data_pagamento"] if before["status"] == "pago" else None)
        or today()
    )
    _record_transition(
        db, entry, before, event_type="updated", action="manual_ui_update"
    )
    db.commit()
    return get_lancamento(db, entry.id)


def move_lancamento(
    db: Session,
    lancamento_id: int,
    payload: LancamentoMove,
) -> Lancamento:
    entry = get_lancamento(db, lancamento_id)
    if entry.arquivado_em is not None:
        raise HTTPException(status_code=409, detail="Lancamento arquivado e somente para consulta.")
    before = _snapshot(entry)
    if payload.status == "pendente":
        entry.status = "pendente"
        entry.data_pagamento = None
    elif entry.status != "pago":
        entry.status = "pago"
        entry.data_pagamento = today()
    _record_transition(
        db, entry, before, event_type="status_changed", action="explicit_status_confirmation"
    )
    db.commit()
    return get_lancamento(db, entry.id)


def is_atrasado(entry: Lancamento, today_value: date) -> bool:
    return (
        entry.arquivado_em is None
        and entry.status != "pago"
        and entry.data_vencimento < today_value
    )


def archive_expired_lancamentos(
    db: Session, *, today_value: date | None = None
) -> int:
    """Archive confirmed payments after 30 days, preserving status and history."""
    cutoff = (today_value or today()) - timedelta(days=30)
    query = (
        db.query(Lancamento)
        .filter(
            Lancamento.status == "pago",
            Lancamento.data_pagamento.is_not(None),
            Lancamento.data_pagamento <= cutoff,
            Lancamento.arquivado_em.is_(None),
        )
        .order_by(Lancamento.id.asc())
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    archived = 0
    for entry in query.all():
        before = _snapshot(entry)
        entry.arquivado_em = today_value or today()
        _record_transition(
            db,
            entry,
            before,
            event_type="archived",
            action="auto_archive_after_30_days",
            observation="Pagamento/recebimento confirmado há pelo menos 30 dias.",
        )
        archived += 1
    db.commit()
    return archived
