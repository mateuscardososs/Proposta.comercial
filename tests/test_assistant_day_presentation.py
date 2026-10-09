from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.assistant import service as service_module
from app.assistant.service import AssistantService
from app.services.daily_schedule_service import DailySchedule, UnscheduledTask
from app.services.today_service import TaskDayPlan, TaskPlanItem

TODAY = date(2026, 10, 7)


def brief_fixture():
    return {
        "counts": dict.fromkeys((
            "tasks_open", "tasks_overdue", "tasks_today", "schedule_blocks",
            "service_items", "emails_operational", "emails_review",
            "payables_overdue", "payables_upcoming", "receivables_overdue",
            "receivables_upcoming",
        ), 0),
        "sources": [], "items": [], "queried_at": "2026-10-07T08:15:00",
        "timezone": "America/Recife", "availability_configured": False,
    }


@pytest.mark.parametrize("count", [0, 1, 2])
def test_daily_brief_empty_sources_and_spoken_counts(monkeypatch, count):
    brief = brief_fixture()
    brief["counts"].update(tasks_overdue=count, tasks_today=count)
    brief["sources"] = [
        {"label": "Correio", "state": "partial"},
        {"label": "Financeiro", "state": "unavailable"},
        {"label": "Falha", "state": "failed"},
        {"label": "Quadro", "state": "ok"},
    ]
    build = Mock(return_value=brief)
    monkeypatch.setattr(service_module, "build_daily_brief", build)
    service = AssistantService(Mock(), None, now=lambda: datetime(2026, 10, 7, 8, 15, tzinfo=UTC))
    reply = service._execute_daily_brief(23)
    assert reply.conversation_id == 23
    assert reply.daily_brief == brief
    assert "Consultei o quadro: não há tarefas abertas. " in reply.message
    assert "Agenda: disponibilidade não configurada; nenhum horário foi presumido como livre. " in reply.message
    assert "Fontes que precisam de atenção: Correio, Financeiro, Falha." in reply.message
    assert reply.message.endswith("abaixo.Esta sugestão é somente leitura: não salva a agenda nem altera tarefas.")
    noun = "tarefa" if count == 1 else "tarefas"
    adjective = "atrasada" if count == 1 else "atrasadas"
    assert f"{count} {noun} {adjective}, {count} {noun} com prazo hoje" in reply.spoken_message
    assert reply.spoken_message.endswith("Algumas fontes estão indisponíveis ou incompletas; veja os detalhes na tela.")
    assert build.call_count == 1


def test_daily_brief_task_order_clients_and_schedule_variants(monkeypatch):
    brief = brief_fixture()
    brief["availability_configured"] = True
    brief["counts"].update(tasks_open=2, schedule_blocks=4)
    brief["items"] = [
        {"source": "tasks", "title": "Sem data", "order": 2, "status": "A fazer",
         "priority": "Não definida", "reason": "Sem prazo."},
        {"source": "tasks", "title": "Enviar", "order": 1, "status": "Em andamento",
         "priority": "Urgente", "reason": "Prazo.", "due_date": "2026-10-07", "client": "Cliente"},
    ]
    for index, extra in enumerate([
        {"fixed": True}, {"duration_source": "default_estimate", "duration_minutes": 30},
        {"duration_is_estimate": True, "duration_minutes": 45}, {},
    ]):
        brief["items"].append({
            "source": "schedule", "title": f"Bloco {index}",
            "start": "2026-10-07T09:00:00", "end": "2026-10-07T10:00:00", **extra,
        })
    monkeypatch.setattr(service_module, "build_daily_brief", Mock(return_value=brief))
    reply = AssistantService(Mock(), None)._execute_daily_brief(3)
    assert "1. Enviar — Status: Em andamento; Prioridade sugerida: Urgente; prazo: 07/10/2026. Motivo: Prazo. Cliente: Cliente." in reply.message
    assert "2. Sem data — Status: A fazer; Prioridade sugerida: Não definida; prazo: sem prazo. Motivo: Sem prazo." in reply.message
    assert "Bloco 0 (Compromisso fixo)." in reply.message
    assert "Bloco 1; 30 min (estimativa padrão)." in reply.message
    assert "Bloco 2; 45 min (duração estimada informada na tarefa)." in reply.message
    assert "Bloco 3 (bloco de tarefa)." in reply.message
    assert "Não há tarefa com prazo hoje;" in reply.message


@pytest.mark.parametrize("configured", [False, True])
def test_empty_agenda_exact_message_and_payload(monkeypatch, configured):
    plan = TaskDayPlan(TODAY, (), (), 0, 0, 0)
    schedule = DailySchedule(TODAY, "America/Recife", configured, 30, (), (), ())
    monkeypatch.setattr(service_module, "get_task_day_plan", Mock(return_value=plan))
    monkeypatch.setattr(service_module, "build_daily_schedule", Mock(return_value=schedule))
    db = Mock()
    db.query.return_value.filter.return_value.all.return_value = []
    reply, result = AssistantService(db, None)._execute_task_agenda(8, TODAY)
    availability = (
        "Nenhuma tarefa coube nas janelas livres restantes de hoje."
        if configured else
        "A disponibilidade semanal não está configurada; nenhum horário foi presumido como livre."
    )
    assert reply.message == (
        "Consultei o quadro: não há tarefas abertas.\n"
        "Sugestão de blocos de horário (determinística e somente de leitura):\n"
        f"{availability}\n"
        "Visualizar ou gerar a sugestão não salva a agenda nem altera tarefas. Para salvar um snapshot, peça para salvar a agenda e confirme a prévia."
    )
    assert result.tool == "consultar_tarefas"
    assert result.payload == {
        "criteria": {"scope": "all_open_board_tasks", "reference_date": "2026-10-07",
                     "read_only": True, "limited": False},
        "tasks": [], "schedule": schedule.snapshot(),
    }


def test_agenda_pending_client_duration_payload_and_query_order(monkeypatch):
    item = TaskPlanItem(41, "Retorno", "aguardando_cliente", "Aguardando cliente",
                        "Não definida", None, "Cliente", "pending_review",
                        "Aguardar.", "waiting_customer", "Aguardando cliente", "/web/board/41/edit")
    plan = TaskDayPlan(TODAY, (item,), (), 1, 0, 0)
    schedule = DailySchedule(TODAY, "America/Recife", True, 30, (), (),
                             (UnscheduledTask(41, "Retorno", "Sem janela."),))
    events = []
    monkeypatch.setattr(service_module, "get_task_day_plan",
                        lambda *args, **kwargs: events.append("plan") or plan)
    monkeypatch.setattr(service_module, "build_daily_schedule",
                        lambda *args, **kwargs: events.append("schedule") or schedule)
    db = Mock()
    db.query.side_effect = lambda *args: events.append("durations") or query
    query = Mock()
    query.filter.return_value.all.return_value = [SimpleNamespace(id=41, estimated_duration_minutes=None)]
    reply, result = AssistantService(db, None)._execute_task_agenda(8, TODAY)
    assert events == ["plan", "schedule", "durations"]
    assert "Cliente: Cliente (vínculo pendente de revisão)" in reply.message
    assert "Não alocadas:\n- Retorno: Sem janela." in reply.message
    assert result.payload["tasks"] == [{
        "id": 41, "title": "Retorno", "status": "Aguardando cliente",
        "priority_suggested": "Não definida", "priority_reason": "Aguardar.",
        "due_date": None, "client": "Cliente", "client_link_status": "pending_review",
        "section": "waiting_customer", "href": "/web/board/41/edit",
        "estimated_duration_minutes": None,
    }]
    assert result.payload["schedule"] == schedule.snapshot()
