from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models import Client, Lancamento, Proposal, User
from app.schemas import LancamentoCreate


def test_lancamento_foreign_keys_use_set_null():
    foreign_keys = {fk.parent.name: fk for fk in Lancamento.__table__.foreign_keys}

    assert foreign_keys["client_id"].ondelete == "SET NULL"
    assert foreign_keys["proposal_id"].ondelete == "SET NULL"
    assert Lancamento.__table__.c.client_id.nullable is True
    assert Lancamento.__table__.c.proposal_id.nullable is True


def test_deleting_client_and_proposal_preserves_lancamento(db):
    client = Client(razao_social="Cliente teste")
    user = User(nome="Responsavel", email="responsavel@example.com", senha_hash="hash")
    db.add_all([client, user])
    db.flush()
    proposal = Proposal(numero=1, revisao="00", client_id=client.id, user_id=user.id)
    db.add(proposal)
    db.flush()
    lancamento = Lancamento(
        tipo="receber",
        descricao="Servico",
        client_id=client.id,
        proposal_id=proposal.id,
        valor=Decimal("100.00"),
        data_emissao=date(2026, 8, 27),
        data_vencimento=date(2026, 9, 27),
        status="pendente",
    )
    db.add(lancamento)
    db.commit()
    lancamento_id = lancamento.id

    db.delete(client)
    db.commit()
    db.expire_all()

    preserved = db.get(Lancamento, lancamento_id)
    assert preserved is not None
    assert preserved.client_id is None
    assert preserved.proposal_id is None


@pytest.mark.parametrize("tipo", ["entrada", "", "RECEBER"])
def test_lancamento_create_rejects_invalid_tipo(tipo):
    with pytest.raises(ValidationError):
        LancamentoCreate(
            tipo=tipo,
            descricao="Servico",
            valor=Decimal("10.00"),
            data_vencimento=date(2026, 9, 1),
        )


def test_lancamento_create_rejects_empty_description_and_non_positive_value():
    with pytest.raises(ValidationError):
        LancamentoCreate(
            tipo="pagar",
            descricao="   ",
            valor=Decimal("0.00"),
            data_vencimento=date(2026, 9, 1),
        )
