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
    paid = Lancamento(status="pago", data_vencimento=date(2026, 8, 26))

    assert lancamento_service.is_atrasado(pending, today_value) is True
    assert lancamento_service.is_atrasado(paid, today_value) is False


def test_proposal_creation_does_not_create_financial_entry(db):
    client, proposal = make_references(db)

    created = proposal_service.create_proposal(
        db,
        ProposalCreate(client_id=client.id, user_id=proposal.user_id),
    )

    assert created.id is not None
    assert db.query(Lancamento).count() == 0
