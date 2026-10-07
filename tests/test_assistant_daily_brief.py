from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.assistant.service import AssistantService
from app.models import (
    Client,
    EmailSyncState,
    InboxEmail,
    Lancamento,
    ServiceCall,
    Task,
    WorkAvailabilityWindow,
)
from app.services import daily_brief_service
from app.services.daily_brief_service import build_daily_brief


def _now() -> datetime:
    return datetime(2026, 10, 7, 8, 15, tzinfo=ZoneInfo("America/Recife"))


def test_daily_greeting_returns_read_only_summary_without_llm(db):
    db.add_all(
        [
            Task(
                titulo="Enviar relatório atrasado",
                status="a_fazer",
                prazo=date(2026, 10, 6),
                ordem=0,
            ),
            Task(
                titulo="Ligar para cliente hoje",
                status="em_andamento",
                prazo=date(2026, 10, 7),
                ordem=1,
            ),
            Task(
                titulo="Tarefa concluída não entra",
                status="concluido",
                prazo=date(2026, 10, 7),
                ordem=2,
            ),
        ]
    )
    db.commit()
    before = [(task.id, task.status, task.prazo) for task in db.query(Task).all()]
    service = AssistantService(db, None, now=_now, timezone="America/Recife")

    reply = service.handle_message(
        message="Bom dia, o que preciso fazer hoje?",
        request_id="daily-brief-greeting-1",
        source="voice",
    )

    assert reply.kind == "text"
    assert "07/10/2026" in reply.message
    assert "08:15" in reply.message
    assert "1 tarefa atrasada" in reply.spoken_message
    assert "1 tarefa com prazo hoje" in reply.spoken_message
    brief = reply.model_dump().get("daily_brief")
    assert brief is not None
    task_titles = [
        item["title"] for item in brief["items"] if item["source"] == "tasks"
    ]
    assert task_titles == ["Enviar relatório atrasado", "Ligar para cliente hoje"]
    assert "Tarefa concluída não entra" not in task_titles
    assert any(
        source["key"] == "tasks" and source["href"] == "/web/board"
        for source in brief["sources"]
    )
    assert [
        (task.id, task.status, task.prazo) for task in db.query(Task).all()
    ] == before


def test_daily_summary_paraphrases_use_same_deterministic_sources(db):
    service = AssistantService(db, None, now=_now, timezone="America/Recife")

    for index, prompt in enumerate(
        (
            "O que tenho para fazer hoje?",
            "Resuma meu dia",
            "Quais são as prioridades de hoje?",
        )
    ):
        reply = service.handle_message(
            message=prompt,
            request_id=f"daily-brief-paraphrase-{index}",
            source="text",
        )
        assert reply.kind == "text"
        assert reply.daily_brief is not None


def test_daily_brief_marks_schedule_unconfigured_and_partial_email_cache(db):
    db.add(
        EmailSyncState(
            provider="imap_yahoo",
            mailbox_key="primary",
            last_success_at=datetime(
                2026, 10, 7, 7, 55, tzinfo=ZoneInfo("America/Recife")
            ),
            last_error="partial",
            last_count=0,
        )
    )
    db.add(
        InboxEmail(
            provider="imap_yahoo",
            mailbox_key="primary",
            reference="synthetic-ref",
            thread_reference="",
            sender="synthetic@example.invalid",
            subject="Pedido sintético",
            received_at=datetime(2026, 10, 7, 7, 0, tzinfo=ZoneInfo("America/Recife")),
            seen=False,
            awaiting_reply="unknown",
            sent_coverage=False,
            summary="synthetic content",
            category="customer_quote_request",
            confidence_band="high",
            destination="task",
            classification_reason="fixture",
            priority="normal",
            review_status="pending",
            last_seen_at=datetime(
                2026, 10, 7, 7, 55, tzinfo=ZoneInfo("America/Recife")
            ),
        )
    )
    db.commit()

    brief = build_daily_brief(
        db,
        now=_now(),
        timezone="America/Recife",
        email_provider="imap_yahoo",
        email_mailbox_key="primary",
        email_freshness_seconds=1800,
    )

    schedule = next(
        source for source in brief["sources"] if source["key"] == "schedule"
    )
    emails = next(source for source in brief["sources"] if source["key"] == "emails")
    assert schedule["state"] == "not_configured"
    assert "nenhum horário foi presumido" in schedule["detail"]
    assert brief["counts"]["schedule_blocks"] == 0
    assert emails["state"] == "partial"
    assert emails["count"] == 1
    assert "cache local" in emails["detail"]
    stored_email = db.query(InboxEmail).one()
    assert stored_email.seen is False
    assert stored_email.review_status == "pending"


def test_daily_brief_distinguishes_confirmed_empty_sources_from_unavailable_email(db):
    db.add(
        EmailSyncState(
            provider="imap_yahoo",
            mailbox_key="primary",
            last_success_at=datetime(
                2026, 10, 7, 8, 0, tzinfo=ZoneInfo("America/Recife")
            ),
            last_error=None,
            last_count=0,
        )
    )
    db.commit()

    brief = build_daily_brief(
        db,
        now=_now(),
        timezone="America/Recife",
        email_provider="imap_yahoo",
        email_mailbox_key="primary",
        email_freshness_seconds=1800,
    )

    sources = {source["key"]: source for source in brief["sources"]}
    assert sources["tasks"]["state"] == "empty"
    assert sources["services"]["state"] == "empty"
    assert sources["emails"]["state"] == "empty"
    assert sources["payables"]["state"] == "empty"
    assert sources["receivables"]["state"] == "empty"
    assert sources["schedule"]["state"] == "not_configured"
    assert not brief["items"]


def test_daily_brief_reports_finance_source_failure_and_keeps_other_sources(
    db, monkeypatch
):
    db.add(
        Task(
            titulo="Pendência de hoje",
            status="a_fazer",
            prazo=date(2026, 10, 7),
            ordem=0,
        )
    )
    db.commit()
    original = daily_brief_service.lancamento_service.list_lancamentos

    def fail_payables(session, tipo):
        if tipo == "pagar":
            raise RuntimeError("synthetic source outage")
        return original(session, tipo)

    monkeypatch.setattr(
        daily_brief_service.lancamento_service, "list_lancamentos", fail_payables
    )
    brief = build_daily_brief(
        db,
        now=_now(),
        timezone="America/Recife",
        email_provider="disabled",
        email_mailbox_key="primary",
    )

    source_by_key = {source["key"]: source for source in brief["sources"]}
    assert source_by_key["payables"]["state"] == "failed"
    assert source_by_key["tasks"]["state"] == "success"
    assert any(item["title"] == "Pendência de hoje" for item in brief["items"])


def test_daily_brief_counts_only_pending_unarchived_finance_and_service_work(db):
    client = Client(razao_social="Cliente sintético")
    db.add(client)
    db.flush()
    db.add_all(
        [
            Lancamento(
                tipo="pagar",
                descricao="Boleto vencido",
                valor="120.00",
                data_emissao=date(2026, 10, 1),
                data_vencimento=date(2026, 10, 6),
                status="pendente",
            ),
            Lancamento(
                tipo="receber",
                descricao="Recebimento próximo",
                valor="250.00",
                client_id=client.id,
                data_emissao=date(2026, 10, 1),
                data_vencimento=date(2026, 10, 10),
                status="pendente",
            ),
            Lancamento(
                tipo="pagar",
                descricao="Conta já paga",
                valor="30.00",
                data_emissao=date(2026, 9, 1),
                data_vencimento=date(2026, 9, 2),
                status="pago",
                data_pagamento=date(2026, 9, 2),
            ),
            ServiceCall(
                client_id=client.id,
                summary="Retorno técnico sintético",
                opened_on=date(2026, 10, 6),
                execution_status="in_progress",
                administrative_status="open",
            ),
        ]
    )
    db.commit()
    before = [
        (entry.id, entry.status, entry.data_vencimento)
        for entry in db.query(Lancamento).all()
    ]

    brief = build_daily_brief(
        db,
        now=_now(),
        timezone="America/Recife",
        email_provider="disabled",
        email_mailbox_key="primary",
    )

    assert brief["counts"]["payables_overdue"] == 1
    assert brief["counts"]["receivables_upcoming"] == 1
    assert brief["counts"]["service_items"] == 1
    assert [
        (entry.id, entry.status, entry.data_vencimento)
        for entry in db.query(Lancamento).all()
    ] == before


def test_daily_brief_does_not_truncate_service_sources_at_fifty(db):
    client = Client(razao_social="Cliente sintético")
    db.add(client)
    db.flush()
    db.add_all(
        ServiceCall(
            client_id=client.id,
            summary=f"Chamado ativo {index:02d}",
            opened_on=date(2026, 10, 6),
            execution_status="in_progress",
            administrative_status="open",
        )
        for index in range(57)
    )
    db.commit()

    brief = build_daily_brief(
        db,
        now=_now(),
        timezone="America/Recife",
        email_provider="disabled",
        email_mailbox_key="primary",
    )

    service_items = [item for item in brief["items"] if item["source"] == "services"]
    assert brief["counts"]["service_items"] == 57
    assert len(service_items) == 57
    assert "Cliente sintético: Chamado ativo 56" in {
        item["title"] for item in service_items
    }


def test_daily_brief_uses_configured_schedule_without_mutating_tasks(db):
    task = Task(
        titulo="Relatório com bloco sintético",
        status="a_fazer",
        prazo=date(2026, 10, 7),
        estimated_duration_minutes=30,
        ordem=0,
    )
    db.add(task)
    db.add(
        WorkAvailabilityWindow(
            weekday=2,
            start_time=datetime.min.time().replace(hour=9),
            end_time=datetime.min.time().replace(hour=12),
        )
    )
    db.commit()
    before = (task.status, task.prazo, task.updated_at)

    brief = build_daily_brief(
        db,
        now=_now(),
        timezone="America/Recife",
        email_provider="disabled",
        email_mailbox_key="primary",
    )

    schedule = next(
        source for source in brief["sources"] if source["key"] == "schedule"
    )
    block = next(item for item in brief["items"] if item["source"] == "schedule")
    assert schedule["state"] == "success"
    assert block["title"] == "Relatório com bloco sintético"
    assert block["duration_minutes"] == 30
    assert block["duration_is_estimate"] is True
    assert (task.status, task.prazo, task.updated_at) == before
