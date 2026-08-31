import re
from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.models import Client, Lancamento, Proposal, Task, User


def _kpi_classes(html: str, key: str) -> set[str]:
    match = re.search(
        rf'<article class="([^"]+)"\s+data-kpi="{re.escape(key)}">',
        html,
    )
    assert match is not None, f"KPI {key} não encontrado"
    return set(match.group(1).split())


def test_index_renders_dashboard_contract_and_danger_states(db):
    today = date.today()
    client = Client(razao_social="Cliente Dashboard")
    user = User(
        nome="Responsável Dashboard",
        email="dashboard-route@example.com",
        senha_hash="hash",
    )
    db.add_all([client, user])
    db.flush()
    db.add_all(
        [
            Lancamento(
                tipo="receber",
                descricao="Recebimento vencido",
                valor=Decimal("100.00"),
                data_vencimento=today - timedelta(days=1),
                status="pendente",
            ),
            Task(
                titulo="Tarefa atrasada",
                status="em_andamento",
                prazo=today - timedelta(days=1),
                ordem=0,
            ),
            Proposal(
                numero=500,
                revisao="00",
                client_id=client.id,
                user_id=user.id,
                data_geracao=today,
                valor_total=Decimal("250.00"),
            ),
        ]
    )
    db.commit()

    with TestClient(app) as client_app:
        response = client_app.get("/")

    assert response.status_code == 200
    assert "Visão geral da empresa" in response.text
    assert "Financeiro" in response.text
    assert "Tarefas" in response.text
    assert "Propostas do mês" in response.text
    assert response.text.count('class="kpi-card') == 9
    assert _kpi_classes(response.text, "receber-vencido") == {
        "kpi-card",
        "is-danger",
    }
    assert _kpi_classes(response.text, "pagar-vencido") == {"kpi-card"}
    assert _kpi_classes(response.text, "tarefas-atrasadas") == {
        "kpi-card",
        "is-danger",
    }
    assert "R$ 100,00" in response.text
    assert "R$ 250,00" in response.text
    assert 'class="layout-grid full-width"' in response.text
    assert 'href="/" class="active"' in response.text
    assert "Clientes ativos" not in response.text
    assert "Usuarios internos" not in response.text
    assert "Ultimas propostas" not in response.text
    assert "em breve" not in response.text.lower()


def test_index_empty_state_keeps_risk_kpis_neutral():
    with TestClient(app) as client_app:
        response = client_app.get("/")

    assert response.status_code == 200
    assert response.text.count('class="kpi-card') == 9
    assert response.text.count("R$ 0,00") == 5
    assert _kpi_classes(response.text, "receber-vencido") == {"kpi-card"}
    assert _kpi_classes(response.text, "pagar-vencido") == {"kpi-card"}
    assert _kpi_classes(response.text, "tarefas-atrasadas") == {"kpi-card"}
