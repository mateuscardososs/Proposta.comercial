from fastapi.testclient import TestClient

from app.main import app
from app.models import Task


NEW_STATUS = "servico_feito_falta_nota_pedido"
NEW_LABEL = "Serviços Feitos — Falta Nota/Pedido"


def test_board_shows_service_done_column_in_approved_order():
    with TestClient(app) as client:
        response = client.get("/web/board")

    assert response.status_code == 200
    statuses = [
        'data-status="a_fazer"',
        'data-status="em_andamento"',
        f'data-status="{NEW_STATUS}"',
        'data-status="aguardando_cliente"',
        'data-status="concluido"',
    ]
    positions = [response.text.index(status) for status in statuses]
    assert positions == sorted(positions)
    assert NEW_LABEL in response.text
    assert '--kanban-columns: 5' in response.text
    assert 'data-board-filters' in response.text
    assert 'data-filter-search' in response.text
    assert 'data-filter-owner' in response.text
    assert 'data-filter-client' in response.text
    assert 'data-filter-deadline' in response.text
    assert 'data-task-total' in response.text


def test_board_card_has_accessible_move_control_and_client_fallback(db):
    task = Task(titulo="Validar atendimento", status="a_fazer", ordem=0)
    db.add(task)
    db.commit()

    with TestClient(app) as client:
        response = client.get("/web/board")

    assert response.status_code == 200
    assert "Cliente a identificar" in response.text
    assert 'data-task-move' in response.text
    assert 'aria-label="Mover tarefa Validar atendimento"' in response.text


def test_task_form_offers_service_done_status():
    with TestClient(app) as client:
        response = client.get("/web/board/new")

    assert response.status_code == 200
    assert f'<option value="{NEW_STATUS}"' in response.text
    assert NEW_LABEL in response.text


def test_move_task_to_service_done_status_persists(db):
    task = Task(titulo="Serviço executado", status="em_andamento", ordem=0)
    db.add(task)
    db.commit()
    task_id = task.id

    with TestClient(app) as client:
        response = client.post(
            f"/api/tasks/{task_id}/move",
            json={"status": NEW_STATUS, "ordem": 0},
        )

    assert response.status_code == 200
    assert response.json()["status"] == NEW_STATUS
    db.expire_all()
    assert db.get(Task, task_id).status == NEW_STATUS
