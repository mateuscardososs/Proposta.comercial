from datetime import datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    AssistantAction,
    AssistantConversation,
    DailySchedulePreference,
    DailyScheduleSnapshot,
    FixedCommitment,
    Task,
    WorkAvailabilityWindow,
)
from app.routers import pages


def test_today_shows_no_time_as_free_until_availability_is_configured(db):
    db.add(Task(titulo="Tarefa sem agenda sintética", status="a_fazer"))
    db.commit()

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Disponibilidade semanal ainda não configurada" in response.text
    assert "nenhum horário foi presumido como livre" in response.text
    assert db.query(DailyScheduleSnapshot).count() == 0


def test_today_renders_estimated_blocks_and_fixed_commitment_gaps_without_saving(db, monkeypatch):
    reference = datetime(2026, 10, 8, 0, 0, tzinfo=ZoneInfo("America/Recife"))
    monkeypatch.setattr(pages, "datetime", SimpleNamespace(now=lambda zone: reference.astimezone(zone)))
    today = reference.date()
    db.add_all(
        [
            Task(titulo="Tarefa bloco sintética", status="a_fazer"),
            WorkAvailabilityWindow(
                weekday=today.weekday(), start_time=time(0), end_time=time(23, 59)
            ),
            FixedCommitment(
                title="Intervalo sintético",
                occurrence_type="weekly",
                weekday=today.weekday(),
                start_time=time(0),
                end_time=time(0, 1),
            ),
        ]
    )
    db.commit()

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'data-today-section="time-blocks"' in response.text
    assert "Tarefa bloco sintética" in response.text
    assert "60 min · estimativa" in response.text
    assert "00:01–01:01" in response.text
    assert db.query(DailyScheduleSnapshot).count() == 0
    assert db.query(Task).one().status == "a_fazer"


def test_agenda_configuration_is_editable_and_validates_time_windows(db):
    with TestClient(app, follow_redirects=False) as client:
        config = client.get("/web/agenda/config")
        duration = client.post(
            "/web/agenda/config",
            data={"action": "default_duration", "default_task_duration_minutes": "75"},
        )
        window = client.post(
            "/web/agenda/config",
            data={
                "action": "add_window",
                "weekday": "1",
                "label": "Expediente de teste",
                "start_time": "09:00",
                "end_time": "12:00",
            },
        )
        commitment = client.post(
            "/web/agenda/config",
            data={
                "action": "add_commitment",
                "title": "Compromisso sintético",
                "occurrence_type": "dated",
                "commitment_date": "2026-10-06",
                "start_time": "10:00",
                "end_time": "10:30",
            },
        )
        invalid_window = client.post(
            "/web/agenda/config",
            data={
                "action": "add_window",
                "weekday": "1",
                "start_time": "12:00",
                "end_time": "09:00",
            },
        )

    assert config.status_code == 200
    assert "60" in config.text
    assert duration.status_code == 303
    assert window.status_code == 303
    assert commitment.status_code == 303
    assert invalid_window.status_code == 400
    assert db.get(DailySchedulePreference, 1).default_task_duration_minutes == 75
    assert db.query(WorkAvailabilityWindow).count() == 1
    assert db.query(FixedCommitment).one().occurrence_type == "dated"


def test_task_form_exposes_editable_duration_estimate(db):
    with TestClient(app) as client:
        response = client.get("/web/board/new")

    assert response.status_code == 200
    assert 'name="estimated_duration_minutes"' in response.text
    assert "Aparecerá como estimativa" in response.text

    with TestClient(app, follow_redirects=False) as client:
        saved = client.post(
            "/web/board/new",
            data={
                "titulo": "Duração editável sintética",
                "descricao": "",
                "status": "a_fazer",
                "estimated_duration_minutes": "90",
            },
        )
    assert saved.status_code == 303
    assert db.query(Task).one().estimated_duration_minutes == 90


def test_today_exposes_snapshot_version_history_without_mutating_it(db):
    today = datetime.now(ZoneInfo("America/Recife")).date()
    conversation = AssistantConversation()
    db.add(conversation)
    db.flush()
    for version in (1, 2):
        action = AssistantAction(
            conversation_id=conversation.id,
            request_id=f"today-snapshot-{version}",
            confirmation_token_hash=f"hash-{version}",
            action_type="save_daily_schedule",
            status="executed",
            arguments_json={},
            result_json={},
        )
        db.add(action)
        db.flush()
        db.add(DailyScheduleSnapshot(
            schedule_date=today,
            version=version,
            assistant_action_id=action.id,
            idempotency_key=f"today-snapshot-key-{version}",
            snapshot_json={"date": today.isoformat(), "blocks": [], "fixed_blocks": [], "unscheduled": []},
        ))
    db.commit()

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Histórico de versões anteriores (1)" in response.text
    assert "Versão 1" in response.text
    assert db.query(DailyScheduleSnapshot).count() == 2
