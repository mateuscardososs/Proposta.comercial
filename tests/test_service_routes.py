from datetime import date
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db import Base, get_db
from app.main import app
from app.models import (
    AssistantAction, AssistantConversation, Client, ServiceCall, ServiceEvent,
    ServiceTaskLink, ServiceWorkflowStep, ServiceWorkflowTransition, Task,
)


@pytest.fixture(autouse=True)
def reset_database():
    """Keep this route suite off the shared test database."""
    yield


@pytest.fixture
def route_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'service-routes.sqlite3'}")
    Base.metadata.create_all(engine)

    def override_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with Session(engine) as session:
            yield session
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _count_selects(engine, request):
    statements = []

    def collect(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", collect)
    try:
        response = request()
    finally:
        event.remove(engine, "before_cursor_execute", collect)
    return response, statements


def _call(db, name, summary, opened_on, *, execution="not_started", administration="open"):
    client = Client(razao_social=name)
    db.add(client)
    db.flush()
    call = ServiceCall(
        client_id=client.id, summary=summary, opened_on=opened_on,
        execution_status=execution, administrative_status=administration,
    )
    db.add(call)
    db.flush()
    for kind in ("report", "proposal", "proposal_sent", "invoice", "receipt"):
        db.add(ServiceWorkflowStep(service_call_id=call.id, step_type=kind))
    db.flush()
    return call


def _action(db, conversation, number):
    action = AssistantAction(
        conversation_id=conversation.id, request_id=f"route-{number}",
        confirmation_token_hash=f"route-hash-{number}",
        action_type="register_service_event", status="confirmed",
    )
    db.add(action)
    db.flush()
    return action


def test_service_list_shows_current_independent_states_and_detail_links(route_db):
    older = _call(route_db, "Cliente Alfa", "Calibrar balanca", date(2026, 9, 20))
    newer = _call(
        route_db, "Cliente Beta", "Verificar bancada", date(2026, 10, 1),
        execution="completed", administration="open",
    )
    for number in range(4):
        _call(route_db, f"Cliente Extra {number}", f"Servico {number}", date(2026, 9, 10 + number))
    older_id, newer_id = older.id, newer.id
    route_db.commit()

    response, selects = _count_selects(
        route_db.get_bind(), lambda: TestClient(app).get("/web/services")
    )

    assert response.status_code == 200
    assert response.text.index("Cliente Beta") < response.text.index("Cliente Alfa")
    assert "Execucao tecnica" in response.text
    assert "Situacao administrativa" in response.text
    assert "Concluida" in response.text
    assert "Aberta" in response.text
    assert f'href="/web/services/{older_id}"' in response.text
    assert f'href="/web/services/{newer_id}"' in response.text
    assert 'href="/web/services" class="active"' in response.text
    assert "<form" not in response.text
    assert len(selects) <= 3, f"Lista executou {len(selects)} SELECTs para seis chamados"


def test_service_detail_shows_projection_original_correction_and_transition_history(route_db):
    call = _call(
        route_db, "Cliente Historico", "Inspecao de equipamento", date(2026, 10, 1),
        execution="in_progress",
    )
    conversation = AssistantConversation()
    route_db.add(conversation)
    route_db.flush()
    first_action = _action(route_db, conversation, 1)
    second_action = _action(route_db, conversation, 2)
    correction_action = _action(route_db, conversation, 3)
    first = ServiceEvent(
        service_call_id=call.id, assistant_action_id=first_action.id,
        conversation_id=conversation.id, event_type="inspection",
        occurred_on=date(2026, 10, 1), description="Fato inicial registrado",
    )
    later = ServiceEvent(
        service_call_id=call.id, assistant_action_id=second_action.id,
        conversation_id=conversation.id, event_type="execution_completed",
        occurred_on=date(2026, 10, 3), description="Conclusao original registrada",
    )
    route_db.add_all([first, later])
    route_db.flush()
    correction = ServiceEvent(
        service_call_id=call.id, assistant_action_id=correction_action.id,
        conversation_id=conversation.id, event_type="correction",
        occurred_on=date(2026, 10, 4), description="Motivo da correcao",
        correction_reason="Motivo da correcao", supersedes_event_id=later.id,
        corrected_event_type="execution_started",
        corrected_description="Execucao iniciada corretamente",
    )
    route_db.add(correction)
    report = next(step for step in call.workflow_steps if step.step_type == "report")
    report.status = "waiting_customer"
    route_db.add_all([
        ServiceWorkflowTransition(
            service_call_id=call.id, step_type="report", previous_status="unknown",
            new_status="pending", observation="Preparar relatorio",
            service_event_id=first.id, assistant_action_id=first_action.id,
        ),
        ServiceWorkflowTransition(
            service_call_id=call.id, step_type="report", previous_status="pending",
            new_status="waiting_customer", observation="Aguardar aprovacao",
            service_event_id=later.id, assistant_action_id=second_action.id,
        ),
    ])
    task = Task(titulo="Retornar ao cliente", status="a_fazer", ordem=0)
    extra_tasks = [Task(titulo=f"Lembrete {number}", status="a_fazer", ordem=number) for number in (1, 2)]
    route_db.add_all([task, *extra_tasks])
    route_db.flush()
    route_db.add_all(ServiceTaskLink(
        service_call_id=call.id, task_id=item.id, assistant_action_id=first_action.id,
    ) for item in [task, *extra_tasks])
    call_id, first_id, later_id = call.id, first.id, later.id
    first_action_id, second_action_id, task_id = first_action.id, second_action.id, task.id
    route_db.commit()

    response, selects = _count_selects(
        route_db.get_bind(), lambda: TestClient(app).get(f"/web/services/{call_id}")
    )

    assert response.status_code == 200
    assert "Cliente Historico" in response.text
    assert "Execucao tecnica" in response.text
    assert "Em andamento" in response.text
    assert "Situacao administrativa" in response.text
    assert "Aberta" in response.text
    for label in ("Relatorio", "Proposta", "Proposta enviada", "Nota fiscal", "Recibo"):
        assert label in response.text
    assert "Aguardando cliente" in response.text
    assert response.text.index("Fato inicial registrado") < response.text.index("Conclusao original registrada")
    assert response.text.index("Conclusao original registrada") < response.text.index("Motivo da correcao")
    assert "Execucao iniciada corretamente" in response.text
    assert f"#{later_id}" in response.text
    transition_table = response.text.split('<h2 class="card-title">Historico das etapas</h2>', 1)[1].split("</table>", 1)[0]
    rows = re.findall(r"<tr>(.*?)</tr>", transition_table.split("<tbody>", 1)[1], flags=re.S)
    assert len(rows) == 2
    for row, previous, new, observation, action_id, event_id in (
        (rows[0], "Desconhecida", "Pendente", "Preparar relatorio", first_action_id, first_id),
        (rows[1], "Pendente", "Aguardando cliente", "Aguardar aprovacao", second_action_id, later_id),
    ):
        cells = re.findall(r"<td>(.*?)</td>", row, flags=re.S)
        assert len(cells) == 6
        assert cells[1].strip() == "Relatorio"
        assert cells[2].strip() == previous
        assert cells[3].strip() == new
        assert cells[4].strip() == observation
        assert cells[5].strip() == f"Acao confirmada #{action_id} · Evento #{event_id}"
    assert f'href="/web/board/{task_id}/edit"' in response.text
    assert "<form" not in response.text
    assert len(selects) <= 7, f"Detalhe executou {len(selects)} SELECTs para tres lembretes"


def test_service_detail_returns_404_for_unknown_call(route_db):
    response = TestClient(app).get("/web/services/9999")
    assert response.status_code == 404
