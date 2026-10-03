from datetime import date

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Lancamento


def test_move_endpoint_returns_updated_payment_state(db):
    entry = Lancamento(
        tipo="receber",
        descricao="Servico",
        valor=10,
        data_vencimento=date(2026, 9, 1),
    )
    db.add(entry)
    db.commit()

    with TestClient(app) as client:
        response = client.post(
            f"/api/lancamentos/{entry.id}/move",
            json={"status": "pago"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "pago"
    assert response.json()["data_pagamento"] is not None


def test_move_endpoint_rejects_invalid_status(db):
    entry = Lancamento(
        tipo="pagar",
        descricao="Conta",
        valor=10,
        data_vencimento=date(2026, 9, 1),
    )
    db.add(entry)
    db.commit()

    with TestClient(app) as client:
        response = client.post(
            f"/api/lancamentos/{entry.id}/move",
            json={"status": "cancelado"},
        )

    assert response.status_code == 422


def test_create_receivable_redirects_and_persists():
    with TestClient(app) as client:
        response = client.post(
            "/web/contas-a-receber/new",
            data={
                "descricao": "Manutencao",
                "valor": "1.250,50",
                "data_emissao": "2026-08-27",
                "data_vencimento": "2026-09-27",
                "status": "pendente",
                "client_id": "",
                "proposal_id": "",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].endswith("/web/contas-a-receber")
    with SessionLocal() as db:
        entry = db.query(Lancamento).one()
        assert entry.tipo == "receber"
        assert entry.valor == 1250.50


def test_create_payable_persists_supplier_and_manual_dates():
    with TestClient(app) as client:
        response = client.post(
            "/web/contas-a-pagar/new",
            data={
                "descricao": "Combustivel",
                "fornecedor": "Posto Central",
                "valor": "350,75",
                "data_emissao": "2026-08-27",
                "data_vencimento": "2026-09-10",
                "status": "pendente",
                "proposal_id": "",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    with SessionLocal() as db:
        entry = db.query(Lancamento).one()
        assert entry.tipo == "pagar"
        assert entry.fornecedor == "Posto Central"
        assert entry.data_vencimento == date(2026, 9, 10)


def test_edit_payable_updates_without_changing_type(db):
    entry = Lancamento(
        tipo="pagar",
        descricao="Conta antiga",
        fornecedor="Fornecedor antigo",
        valor=10,
        data_emissao=date(2026, 8, 1),
        data_vencimento=date(2026, 9, 1),
    )
    db.add(entry)
    db.commit()

    with TestClient(app) as client:
        response = client.post(
            f"/web/contas-a-pagar/{entry.id}/edit",
            data={
                "descricao": "Conta atualizada",
                "fornecedor": "Fornecedor novo",
                "valor": "25,00",
                "data_emissao": "2026-08-02",
                "data_vencimento": "2026-09-02",
                "status": "pago",
                "data_pagamento": "2026-08-27",
                "proposal_id": "",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    db.expire_all()
    updated = db.get(Lancamento, entry.id)
    assert updated.tipo == "pagar"
    assert updated.descricao == "Conta atualizada"
    assert updated.fornecedor == "Fornecedor novo"
    assert updated.status == "pago"
    assert updated.data_pagamento == date(2026, 8, 27)


def test_invalid_form_rerenders_with_message():
    with TestClient(app) as client:
        response = client.post(
            "/web/contas-a-pagar/new",
            data={
                "descricao": "",
                "valor": "0",
                "data_emissao": "2026-08-27",
                "data_vencimento": "2026-09-01",
                "status": "pendente",
            },
        )

    assert response.status_code == 400
    assert "Verifique os campos informados" in response.text


def test_cross_type_edit_returns_404(db):
    entry = Lancamento(
        tipo="pagar",
        descricao="Conta",
        valor=10,
        data_vencimento=date(2026, 9, 1),
    )
    db.add(entry)
    db.commit()

    with TestClient(app) as client:
        response = client.get(f"/web/contas-a-receber/{entry.id}/edit")

    assert response.status_code == 404


def test_matching_type_edit_route_exists(db):
    entry = Lancamento(
        tipo="pagar",
        descricao="Conta",
        valor=10,
        data_vencimento=date(2026, 9, 1),
    )
    db.add(entry)
    db.commit()

    with TestClient(app) as client:
        response = client.get(f"/web/contas-a-pagar/{entry.id}/edit")

    assert response.status_code == 200


def test_boards_filter_type_and_mark_only_pending_overdue(db):
    db.add_all(
        [
            Lancamento(
                tipo="receber",
                descricao="Receber atrasado",
                valor=10,
                data_vencimento=date(2020, 1, 1),
                status="pendente",
            ),
            Lancamento(
                tipo="receber",
                descricao="Receber pago",
                valor=20,
                data_vencimento=date(2020, 1, 1),
                status="pago",
                data_pagamento=date(2020, 1, 2),
            ),
            Lancamento(
                tipo="pagar",
                descricao="Pagar oculto",
                valor=30,
                data_vencimento=date(2020, 1, 1),
                status="pendente",
            ),
        ]
    )
    db.commit()

    with TestClient(app) as client:
        response = client.get("/web/contas-a-receber?grupo=atrasadas")

    assert response.status_code == 200
    assert "Receber atrasado" in response.text
    assert "Pagar oculto" not in response.text
    assert response.text.count('class="kanban-card is-overdue"') == 1


def test_navigation_contains_both_financial_links():
    with TestClient(app) as client:
        response = client.get("/web/contas-a-pagar")

    assert 'href="/web/contas-a-receber"' in response.text
    assert 'href="/web/contas-a-pagar"' in response.text


def test_shared_drag_script_has_rollback_and_error_region():
    with TestClient(app) as client:
        response = client.get("/web/contas-a-pagar")

    assert "originZone" in response.text
    assert "originNextSibling" in response.text
    assert 'role="alert"' in response.text
    assert "/api/lancamentos/{id}/move" in response.text


def test_financial_board_separates_open_overdue_paid_and_archived_groups(db):
    from datetime import datetime, timedelta

    from app.models import Lancamento

    today = date.today()
    db.add_all(
        [
            Lancamento(
                tipo="receber", descricao="Aberta futura", valor=10,
                data_vencimento=today + timedelta(days=5), status="pendente",
            ),
            Lancamento(
                tipo="receber", descricao="Atrasada vencida", valor=20,
                data_vencimento=today - timedelta(days=1), status="pendente",
            ),
            Lancamento(
                tipo="receber", descricao="Recebida ativa", valor=30,
                data_vencimento=today, status="pago", data_pagamento=today,
            ),
            Lancamento(
                tipo="receber", descricao="Recebida arquivada", valor=40,
                data_vencimento=today - timedelta(days=40), status="pago",
                data_pagamento=today - timedelta(days=35),
                arquivado_em=datetime.now(),
            ),
        ]
    )
    db.commit()

    with TestClient(app) as client:
        opened = client.get("/web/contas-a-receber?grupo=abertas")
        overdue = client.get("/web/contas-a-receber?grupo=atrasadas")
        paid = client.get("/web/contas-a-receber?grupo=pagas")
        archived = client.get("/web/contas-a-receber?grupo=arquivadas")

    assert "Aberta futura" in opened.text
    assert "Atrasada vencida" not in opened.text
    assert "Atrasada vencida" in overdue.text
    assert "Aberta futura" not in overdue.text
    assert "Recebida ativa" in paid.text
    assert "Recebida arquivada" not in paid.text
    assert "Recebida arquivada" in archived.text
    assert "Recebida ativa" not in archived.text
    assert "Em aberto" in opened.text
    assert "Atrasadas" in overdue.text
    assert "Pagas/recebidas" in paid.text
    assert "Arquivadas" in archived.text


def test_existing_task_board_uses_shared_ordered_drag_contract():
    with TestClient(app) as client:
        response = client.get("/web/board")

    assert response.status_code == 200
    assert 'data-ordered="true"' in response.text
    assert 'data-endpoint-template="/api/tasks/{id}/move"' in response.text
    assert "payload.ordem" in response.text
