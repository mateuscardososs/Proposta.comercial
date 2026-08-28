from fastapi.testclient import TestClient

from app.main import app
from app.models import Task


def test_all_board_pages_use_full_width_layout_without_sidebar(db):
    task = Task(titulo="Atividade para editar", status="a_fazer", ordem=0)
    db.add(task)
    db.commit()

    with TestClient(app) as client:
        responses = [
            client.get("/web/board"),
            client.get("/web/board/new"),
            client.get(f"/web/board/{task.id}/edit"),
        ]

    for response in responses:
        assert response.status_code == 200
        assert 'class="layout-grid full-width"' in response.text
        assert '<aside class="aside-stack">' not in response.text
        assert "<h3>Atalhos</h3>" not in response.text
        assert "<h3>Padrao de produtividade</h3>" not in response.text


def test_non_board_page_keeps_default_sidebar():
    with TestClient(app) as client:
        response = client.get("/web/proposals")

    assert response.status_code == 200
    assert 'class="layout-grid"' in response.text
    assert '<aside class="aside-stack">' in response.text


def test_edit_page_shows_confirmed_delete_action_only_for_existing_task(db):
    task = Task(titulo="Atividade descartável", status="a_fazer", ordem=0)
    db.add(task)
    db.commit()

    with TestClient(app) as client:
        edit_response = client.get(f"/web/board/{task.id}/edit")
        new_response = client.get("/web/board/new")

    assert edit_response.status_code == 200
    assert f'action="/web/board/{task.id}/delete"' in edit_response.text
    assert 'class="btn btn-danger"' in edit_response.text
    assert "Excluir atividade" in edit_response.text
    assert "window.confirm" in edit_response.text
    assert "Esta ação não pode ser desfeita" in edit_response.text
    assert "/delete" not in new_response.text
    assert "Excluir atividade" not in new_response.text


def test_delete_task_redirects_removes_and_compacts_order(db):
    first = Task(titulo="Primeira", status="em_andamento", ordem=0)
    deleted = Task(titulo="Excluir", status="em_andamento", ordem=1)
    last = Task(titulo="Última", status="em_andamento", ordem=2)
    other_column = Task(titulo="Outra coluna", status="concluido", ordem=2)
    db.add_all([first, deleted, last, other_column])
    db.commit()
    deleted_id = deleted.id

    with TestClient(app) as client:
        response = client.post(
            f"/web/board/{deleted_id}/delete",
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"].endswith("/web/board")
    db.expire_all()
    assert db.get(Task, deleted_id) is None
    assert db.get(Task, first.id).ordem == 0
    assert db.get(Task, last.id).ordem == 1
    assert db.get(Task, other_column.id).ordem == 2


def test_delete_missing_task_returns_404():
    with TestClient(app) as client:
        response = client.post(
            "/web/board/999999/delete",
            follow_redirects=False,
        )

    assert response.status_code == 404
