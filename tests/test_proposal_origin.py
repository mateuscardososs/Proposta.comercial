from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text

from app.db import ensure_schema_compatibility_for_engine
from app.models import Client, Proposal, User
from app.schemas import ProposalRead
from app.services import dashboard_service, proposal_service


def _make_references(db):
    client = Client(razao_social="Cliente Origem")
    user = User(
        nome="Responsável Origem",
        email="origem@example.com",
        senha_hash="hash",
    )
    db.add_all([client, user])
    db.flush()
    return client, user


def _make_proposal(db, *, numero: int = 1, origem: str | None = None) -> Proposal:
    client, user = _make_references(db)
    values = {
        "numero": numero,
        "revisao": "00",
        "client_id": client.id,
        "user_id": user.id,
        "data_geracao": date(2026, 8, 31),
        "valor_total": Decimal("100.00"),
    }
    if origem is not None:
        values["origem"] = origem
    proposal = Proposal(**values)
    db.add(proposal)
    db.commit()
    return proposal_service.get_proposal_with_details(db, proposal.id)


def test_proposal_origin_defaults_to_sistema(db):
    proposal = _make_proposal(db)

    assert proposal.origem == "sistema"


def test_proposal_read_exposes_origin(db):
    proposal = _make_proposal(db)

    payload = ProposalRead.model_validate(proposal)

    assert payload.origem == "sistema"


def test_proposal_schema_rejects_unknown_origin(db):
    proposal = _make_proposal(db)
    proposal.origem = "desconhecida"

    with pytest.raises(ValidationError):
        ProposalRead.model_validate(proposal)


def test_schema_compatibility_adds_origin_to_legacy_sqlite_idempotently(tmp_path):
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE proposals ("
                "id INTEGER PRIMARY KEY, "
                "condicao_pagamento_dias INTEGER NOT NULL DEFAULT 0, "
                "imposto_percentual NUMERIC(7,2) NOT NULL DEFAULT 0"
                ")"
            )
        )
        connection.execute(text("INSERT INTO proposals (id) VALUES (1)"))

    ensure_schema_compatibility_for_engine(legacy_engine)
    ensure_schema_compatibility_for_engine(legacy_engine)

    columns = {column["name"] for column in inspect(legacy_engine).get_columns("proposals")}
    with legacy_engine.connect() as connection:
        origin = connection.execute(
            text("SELECT origem FROM proposals WHERE id = 1")
        ).scalar_one()

    assert "origem" in columns
    assert origin == "sistema"


def test_dashboard_counts_all_proposal_origins(db):
    client, user = _make_references(db)
    for numero, origem, value in (
        (10, "sistema", "100.00"),
        (11, "reupload_editado", "200.00"),
        (12, "upload_externo", "300.00"),
    ):
        db.add(
            Proposal(
                numero=numero,
                revisao="00",
                data_geracao=date(2026, 8, 15),
                client_id=client.id,
                user_id=user.id,
                origem=origem,
                valor_total=Decimal(value),
            )
        )
    db.commit()

    summary = dashboard_service.get_dashboard_summary(
        db,
        reference_date=date(2026, 8, 31),
    )

    assert summary.propostas_mes_quantidade == 3
    assert summary.propostas_mes_valor == Decimal("600.00")
