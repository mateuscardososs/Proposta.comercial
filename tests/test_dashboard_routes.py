from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.models import Client, Lancamento, Proposal, Task, User


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
    assert "agenda priorizada" in response.text
    assert "Hoje" in response.text
    assert 'aria-label="Resumo operacional do dia"' in response.text
    assert 'data-today-section="attention"' in response.text
    assert 'data-today-section="agenda"' in response.text
    assert 'data-today-section="services"' in response.text
    assert 'data-today-section="finance"' in response.text
    assert "Indicadores financeiros e propostas do mês" in response.text
    assert "R$ 100,00" in response.text
    assert "R$ 250,00" in response.text
    assert "Tarefa atrasada" in response.text
    assert 'class="layout-grid full-width"' in response.text
    assert 'href="/" aria-label="Hoje"' in response.text
    assert "Clientes ativos" not in response.text
    assert "Usuarios internos" not in response.text
    assert "Ultimas propostas" not in response.text
    assert "em breve" not in response.text.lower()


def test_index_empty_state_is_clear_and_keeps_monthly_kpis():
    with TestClient(app) as client_app:
        response = client_app.get("/")

    assert response.status_code == 200
    assert response.text.count("R$ 0,00") == 5
    assert "Nenhuma pendência encontrada nesta janela" in response.text
