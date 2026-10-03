from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models import Client, Lancamento, Proposal, User
from app.schemas import LancamentoCreate, LancamentoMove, LancamentoUpdate, ProposalCreate
from app.services import lancamento_service, proposal_service


def make_references(db):
    client = Client(razao_social="Cliente A")
    user = User(nome="Responsavel", email="financeiro@example.com", senha_hash="hash")
    db.add_all([client, user])
    db.flush()
    proposal = Proposal(numero=10, revisao="00", client_id=client.id, user_id=user.id)
    db.add(proposal)
    db.commit()
    return client, proposal


def test_create_receivable_keeps_references_and_clears_supplier(db):
    client, proposal = make_references(db)

    created = lancamento_service.create_lancamento(
        db,
        LancamentoCreate(
            tipo="receber",
            descricao="Manutencao",
            client_id=client.id,
            proposal_id=proposal.id,
            fornecedor="nao deve persistir",
            valor=Decimal("4500.00"),
            data_vencimento=date(2026, 10, 1),
        ),
    )

    assert created.client_id == client.id
    assert created.proposal_id == proposal.id
    assert created.fornecedor is None


def test_create_payable_clears_client_and_keeps_optional_proposal(db):
    client, proposal = make_references(db)

    created = lancamento_service.create_lancamento(
        db,
        LancamentoCreate(
            tipo="pagar",
            descricao="Combustivel",
            client_id=client.id,
            proposal_id=proposal.id,
            fornecedor="Posto Central",
            valor=Decimal("300.00"),
            data_vencimento=date(2026, 9, 5),
        ),
    )

    assert created.client_id is None
    assert created.proposal_id == proposal.id
    assert created.fornecedor == "Posto Central"


def test_create_rejects_unknown_optional_references(db):
    with pytest.raises(ValueError, match="Cliente nao encontrado"):
        lancamento_service.create_lancamento(
            db,
            LancamentoCreate(
                tipo="receber",
                descricao="Servico",
                client_id=999,
                valor=Decimal("10.00"),
                data_vencimento=date(2026, 9, 1),
            ),
        )


def test_list_orders_by_due_date_then_descending_id(db):
    for description, due_date in [
        ("Segundo", date(2026, 9, 2)),
        ("Primeiro antigo", date(2026, 9, 1)),
        ("Primeiro novo", date(2026, 9, 1)),
    ]:
        db.add(
            Lancamento(
                tipo="pagar",
                descricao=description,
                valor=10,
                data_vencimento=due_date,
            )
        )
        db.flush()
    db.commit()

    assert [item.descricao for item in lancamento_service.list_lancamentos(db, "pagar")] == [
        "Primeiro novo",
        "Primeiro antigo",
        "Segundo",
    ]


def test_move_sets_and_clears_payment_date(db, monkeypatch):
    fixed_today = date(2026, 8, 27)
    entry = Lancamento(
        tipo="receber",
        descricao="Servico",
        valor=100,
        data_vencimento=fixed_today,
    )
    db.add(entry)
    db.commit()
    monkeypatch.setattr(lancamento_service, "today", lambda: fixed_today)

    paid = lancamento_service.move_lancamento(db, entry.id, LancamentoMove(status="pago"))
    assert paid.status == "pago"
    assert paid.data_pagamento == fixed_today

    pending = lancamento_service.move_lancamento(db, entry.id, LancamentoMove(status="pendente"))
    assert pending.status == "pendente"
    assert pending.data_pagamento is None


def test_update_paid_entry_uses_supplied_payment_date(db):
    entry = Lancamento(
        tipo="pagar",
        descricao="Conta antiga",
        valor=100,
        data_vencimento=date(2026, 9, 1),
    )
    db.add(entry)
    db.commit()

    updated = lancamento_service.update_lancamento(
        db,
        entry.id,
        "pagar",
        LancamentoUpdate(
            descricao="Conta corrigida",
            fornecedor="Fornecedor",
            valor=Decimal("120.00"),
            data_emissao=date(2026, 8, 27),
            data_vencimento=date(2026, 9, 10),
            status="pago",
            data_pagamento=date(2026, 8, 28),
        ),
    )

    assert updated.descricao == "Conta corrigida"
    assert updated.valor == Decimal("120.00")
    assert updated.data_pagamento == date(2026, 8, 28)


def test_edit_url_type_cannot_cross_financial_board(db):
    entry = Lancamento(
        tipo="pagar",
        descricao="Conta",
        valor=100,
        data_vencimento=date(2026, 9, 1),
    )
    db.add(entry)
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        lancamento_service.get_lancamento(db, entry.id, tipo="receber")

    assert exc_info.value.status_code == 404


def test_is_atrasado_only_for_unpaid_past_due_entries():
    today_value = date(2026, 8, 27)
    pending = Lancamento(status="pendente", data_vencimento=date(2026, 8, 26))
    future = Lancamento(status="pendente", data_vencimento=date(2026, 8, 28))
    paid = Lancamento(status="pago", data_vencimento=date(2026, 8, 26))

    assert lancamento_service.is_atrasado(pending, today_value) is True
    assert lancamento_service.is_atrasado(future, today_value) is False
    assert lancamento_service.is_atrasado(paid, today_value) is False


def test_archive_only_paid_entries_with_confirmed_payment_at_30_days(db):
    today_value = date(2026, 10, 3)
    exactly_30_days = Lancamento(
        tipo="pagar",
        descricao="Pagamento elegível",
        valor=10,
        data_vencimento=date(2026, 9, 1),
        status="pago",
        data_pagamento=date(2026, 9, 3),
    )
    newer_payment = Lancamento(
        tipo="receber",
        descricao="Recebimento recente",
        valor=10,
        data_vencimento=date(2026, 9, 1),
        status="pago",
        data_pagamento=date(2026, 9, 4),
    )
    unconfirmed_payment = Lancamento(
        tipo="pagar",
        descricao="Sem data confirmada",
        valor=10,
        data_vencimento=date(2026, 9, 1),
        status="pago",
        data_pagamento=None,
    )
    overdue_unpaid = Lancamento(
        tipo="receber",
        descricao="Em aberto vencido",
        valor=10,
        data_vencimento=date(2026, 9, 1),
        status="pendente",
    )
    db.add_all([exactly_30_days, newer_payment, unconfirmed_payment, overdue_unpaid])
    db.commit()

    archived_count = lancamento_service.archive_expired_lancamentos(
        db, today_value=today_value
    )
    repeated_count = lancamento_service.archive_expired_lancamentos(
        db, today_value=today_value
    )

    assert archived_count == 1
    assert repeated_count == 0
    assert exactly_30_days.arquivado_em is not None
    assert exactly_30_days.status == "pago"
    assert exactly_30_days.data_pagamento == date(2026, 9, 3)
    assert newer_payment.arquivado_em is None
    assert unconfirmed_payment.arquivado_em is None
    assert overdue_unpaid.arquivado_em is None

    from app.models import LancamentoHistorico

    events = db.query(LancamentoHistorico).filter_by(lancamento_id=exactly_30_days.id).all()
    assert len(events) == 1
    assert events[0].event_type == "archived"
    assert events[0].acao_confirmada == "auto_archive_after_30_days"
    assert events[0].status_anterior == "pago"
    assert events[0].status_novo == "pago"
    assert events[0].data_pagamento_anterior == date(2026, 9, 3)
    assert events[0].data_pagamento_nova == date(2026, 9, 3)


def test_repeated_payment_action_preserves_confirmed_date_and_audit_count(db, monkeypatch):
    from app.models import LancamentoHistorico

    entry = Lancamento(
        tipo="pagar",
        descricao="Conta paga",
        valor=10,
        data_vencimento=date(2026, 9, 1),
    )
    db.add(entry)
    db.commit()

    monkeypatch.setattr(lancamento_service, "today", lambda: date(2026, 9, 10))
    first = lancamento_service.move_lancamento(
        db, entry.id, LancamentoMove(status="pago")
    )
    assert first.data_pagamento == date(2026, 9, 10)
    assert db.query(LancamentoHistorico).filter_by(lancamento_id=entry.id).count() == 1

    monkeypatch.setattr(lancamento_service, "today", lambda: date(2026, 9, 12))
    repeated = lancamento_service.move_lancamento(
        db, entry.id, LancamentoMove(status="pago")
    )
    assert repeated.data_pagamento == date(2026, 9, 10)
    assert db.query(LancamentoHistorico).filter_by(lancamento_id=entry.id).count() == 1


def test_financial_history_is_append_only_and_restricts_parent_deletion(db):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, IntegrityError

    from app.models import LancamentoHistorico

    entry = Lancamento(
        tipo="pagar",
        descricao="Conta histórica",
        valor=10,
        data_vencimento=date(2026, 9, 1),
    )
    db.add(entry)
    db.flush()
    event = LancamentoHistorico(
        lancamento_id=entry.id,
        event_key="manual:test-1",
        event_type="status_changed",
        status_anterior="pendente",
        status_novo="pago",
        data_pagamento_anterior=None,
        data_pagamento_nova=date(2026, 9, 1),
        arquivado_em_anterior=None,
        arquivado_em_novo=None,
        acao_confirmada="manual_ui_status_change",
        observacao="Ação explícita de teste",
    )
    db.add(event)
    db.commit()

    event.observacao = "tentativa de reescrita"
    with pytest.raises(ValueError, match="Histórico financeiro imutável"):
        db.commit()
    db.rollback()
    db.expire_all()
    preserved = db.query(LancamentoHistorico).filter_by(lancamento_id=entry.id).one()
    assert preserved.observacao == "Ação explícita de teste"

    db.delete(preserved)
    with pytest.raises(ValueError, match="Histórico financeiro imutável"):
        db.commit()
    db.rollback()
    db.delete(entry)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    with pytest.raises(DBAPIError, match="financial history is immutable"):
        db.execute(
            text("UPDATE lancamento_historicos SET observacao = 'SQL direto' WHERE id = :id"),
            {"id": preserved.id},
        )
        db.commit()
    db.rollback()


def test_proposal_creation_does_not_create_financial_entry(db):
    client, proposal = make_references(db)

    created = proposal_service.create_proposal(
        db,
        ProposalCreate(client_id=client.id, user_id=proposal.user_id),
    )

    assert created.id is not None
    assert db.query(Lancamento).count() == 0
