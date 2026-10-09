from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import TypeVar
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.assistant.email.classification import OPERATIONAL_CATEGORIES
from app.models import EmailSyncState, InboxEmail
from app.schemas import ServiceCallQuery
from app.services import lancamento_service, service_record_service
from app.services.daily_schedule_service import build_daily_schedule
from app.services.today_service import TaskDayPlan, get_task_day_plan

T = TypeVar("T")
EMAIL_REVIEW_CATEGORIES = {"informational", "other_review"}
TASK_STATUS_LABELS = {
    "a_fazer": "A fazer",
    "em_andamento": "Em andamento",
    "servico_feito_falta_nota_pedido": "Serviço feito — falta nota/pedido",
    "aguardando_cliente": "Aguardando cliente",
}


def _run_source(db: Session, operation: Callable[[], T]) -> tuple[T | None, str | None]:
    """Isolate a read-only source query so one SQL failure does not poison others."""
    try:
        with db.begin_nested():
            return operation(), None
    except Exception:  # noqa: BLE001 - report a sanitized source state, not DB details
        return None, "Não foi possível consultar esta fonte agora."


def _source(
    key: str,
    label: str,
    href: str,
    state: str,
    count: int,
    detail: str,
) -> dict[str, object]:
    return {
        "key": key,
        "label": label,
        "href": href,
        "state": state,
        "count": count,
        "detail": detail,
    }


def _task_source(db: Session, today: date) -> TaskDayPlan:
    return get_task_day_plan(db, today=today)


def _email_snapshot(
    db: Session,
    *,
    provider: str,
    mailbox_key: str,
    now: datetime,
    timezone: str,
    freshness_seconds: int,
) -> dict[str, object]:
    state = (
        db.query(EmailSyncState)
        .filter_by(provider=provider, mailbox_key=mailbox_key)
        .one_or_none()
    )
    rows = (
        db.query(InboxEmail.category, InboxEmail.confidence_band)
        .filter_by(provider=provider, mailbox_key=mailbox_key)
        .all()
    )
    categories = Counter(category for category, _ in rows)
    operational = sum(
        1
        for category, confidence in rows
        if category in OPERATIONAL_CATEGORIES and confidence in {"medium", "high"}
    )
    review = sum(
        1
        for category, confidence in rows
        if (
            (category not in OPERATIONAL_CATEGORIES and category != "informational")
            or (
                category in OPERATIONAL_CATEGORIES
                and confidence not in {"medium", "high"}
            )
        )
    )
    informational = categories.get("informational", 0)

    if provider not in {"synthetic", "imap_yahoo"}:
        status = "unavailable"
        detail = "A leitura de e-mail não está configurada neste ambiente; nenhuma caixa foi consultada."
    elif state is None:
        status = "unavailable"
        detail = "Não há ciclo de sincronização registrado; o cache não confirma que a caixa esteja vazia."
    elif state.last_success_at is None:
        status = "unavailable"
        detail = "A sincronização ainda não concluiu uma consulta; o cache não confirma que a caixa esteja vazia."
    else:
        last_success = state.last_success_at.replace(tzinfo=ZoneInfo(timezone))
        age = max(0.0, (now - last_success).total_seconds())
        stale = age > max(1, freshness_seconds)
        if state.last_error:
            status = "partial"
            detail = "A última sincronização ficou parcial ou falhou; os totais abaixo são apenas do cache local."
        elif stale or state.paused:
            status = "partial"
            detail = "O cache local pode estar desatualizado; os totais não representam uma consulta atual da caixa."
        else:
            status = "success" if (operational or review or informational) else "empty"
            detail = (
                "Totais do cache local após sincronização concluída."
                if status == "success"
                else "A última sincronização concluiu sem mensagens no cache consultado."
            )

    return {
        "state": status,
        "detail": detail,
        "operational": operational,
        "review": review,
        "informational": informational,
        "categories": dict(categories),
    }


def build_daily_brief(
    db: Session,
    *,
    now: datetime,
    timezone: str,
    email_provider: str,
    email_mailbox_key: str,
    email_freshness_seconds: int = 1800,
    lookahead_days: int = 7,
) -> dict[str, object]:
    zone = ZoneInfo(timezone)
    local_now = now.replace(tzinfo=zone) if now.tzinfo is None else now.astimezone(zone)
    today = local_now.date()
    through = today + timedelta(days=max(1, min(31, lookahead_days)))
    sources: list[dict[str, object]] = []
    items: list[dict[str, object]] = []
    counts = {
        "tasks_open": 0,
        "tasks_overdue": 0,
        "tasks_today": 0,
        "schedule_blocks": 0,
        "service_items": 0,
        "emails_operational": 0,
        "emails_review": 0,
        "payables_overdue": 0,
        "payables_upcoming": 0,
        "receivables_overdue": 0,
        "receivables_upcoming": 0,
    }

    plan, error = _run_source(db, lambda: _task_source(db, today))
    if error:
        sources.append(_source("tasks", "Tarefas", "/web/board", "failed", 0, error))
    else:
        assert plan is not None
        relevant = list(plan.items)
        counts["tasks_open"] = plan.open_count
        counts["tasks_overdue"] = plan.overdue_count
        counts["tasks_today"] = plan.due_today_count
        sources.append(
            _source(
                "tasks",
                "Tarefas",
                "/web/board",
                "success" if relevant else "empty",
                len(relevant),
                "Consulta completa do quadro; concluídas foram excluídas e a ordem segue a página Hoje."
                if relevant
                else "Não há tarefas abertas no quadro.",
            )
        )
        for position, item in enumerate(relevant, start=1):
            items.append(
                {
                    "source": "tasks",
                    "title": item.title,
                    "href": item.href,
                    "due_date": item.due_date.isoformat() if item.due_date else None,
                    "status": item.status_label,
                    "priority": item.priority_label,
                    "client": item.client_name,
                    "reason": item.reason,
                    "section": item.section_label,
                    "order": position,
                    "rank": (
                        "overdue",
                        "today",
                        "explicit_urgency",
                        "admin_follow_up",
                        "in_progress",
                        "upcoming",
                        "no_deadline",
                        "waiting_customer",
                    ).index(item.section_key),
                }
            )

    schedule_result = None
    if plan is None:
        sources.append(
            _source(
                "schedule",
                "Agenda",
                "/web/agenda/config",
                "unavailable",
                0,
                "Não foi possível montar os blocos porque a consulta de tarefas falhou.",
            )
        )
    else:
        schedule_result, error = _run_source(
            db,
            lambda: build_daily_schedule(
                db,
                today=today,
                now=local_now,
                timezone=timezone,
                task_plan=plan,
            ),
        )
        if error:
            sources.append(
                _source("schedule", "Agenda", "/web/agenda/config", "failed", 0, error)
            )
        else:
            assert schedule_result is not None
            scheduled_count = len(schedule_result.blocks) + len(
                schedule_result.fixed_blocks
            )
            schedule_state = (
                "success"
                if schedule_result.availability_configured
                else "not_configured"
            )
            detail = (
                f"{scheduled_count} bloco(s) de agenda; horários não alteram tarefas."
                if schedule_result.availability_configured
                else "Disponibilidade não configurada; nenhum horário foi presumido como livre."
            )
            sources.append(
                _source(
                    "schedule",
                    "Agenda",
                    "/web/agenda/config",
                    schedule_state,
                    scheduled_count,
                    detail,
                )
            )
            counts["schedule_blocks"] = scheduled_count
            for block in schedule_result.blocks:
                items.append(
                    {
                        "source": "schedule",
                        "title": block.title,
                        "href": f"/web/board/{block.task_id}/edit",
                        "start": block.start.isoformat(),
                        "end": block.end.isoformat(),
                        "duration_minutes": block.duration_minutes,
                        "duration_is_estimate": block.is_estimate,
                        "duration_source": block.duration_source,
                        "reason": block.reason,
                    }
                )
            for block in schedule_result.fixed_blocks:
                items.append(
                    {
                        "source": "schedule",
                        "title": block.title,
                        "href": "/web/agenda/config",
                        "start": block.start.isoformat(),
                        "end": block.end.isoformat(),
                        "fixed": True,
                        "reason": "Compromisso fixo cadastrado.",
                    }
                )

    service_calls, error = _run_source(
        db,
        lambda: service_record_service.list_service_calls(
            db,
            ServiceCallQuery(limit=50),
            unbounded=True,
        ),
    )
    if error:
        sources.append(
            _source("services", "Serviços", "/web/services", "failed", 0, error)
        )
    else:
        assert service_calls is not None
        service_items = []
        for call in service_calls:
            next_step = next(
                (
                    step
                    for step in call.workflow_steps
                    if step.status in {"unknown", "pending"}
                ),
                None,
            )
            active = call.execution_status in {"not_started", "in_progress"}
            if not active and next_step is None:
                continue
            reason = (
                "Execução em andamento."
                if call.execution_status == "in_progress"
                else "Execução ainda não iniciada."
                if call.execution_status == "not_started"
                else "Execução concluída; há etapa administrativa pendente."
            )
            if next_step:
                reason += f" Próxima etapa: {next_step.step_type} ({next_step.status})."
            service_items.append(
                {
                    "source": "services",
                    "title": f"{call.client.razao_social}: {call.summary}",
                    "href": f"/web/services/{call.id}",
                    "due_date": None,
                    "status": call.execution_status,
                    "reason": reason,
                    "rank": 2
                    if call.execution_status == "in_progress"
                    else 3
                    if call.execution_status == "completed"
                    else 4,
                }
            )
        counts["service_items"] = len(service_items)
        items.extend(service_items)
        sources.append(
            _source(
                "services",
                "Serviços e retornos",
                "/web/services",
                "success" if service_items else "empty",
                len(service_items),
                "Chamados em execução ou com próxima etapa administrativa pendente."
                if service_items
                else "Não há serviços ativos ou etapas administrativas pendentes.",
            )
        )

    email_result, error = _run_source(
        db,
        lambda: _email_snapshot(
            db,
            provider=email_provider,
            mailbox_key=email_mailbox_key,
            now=local_now,
            timezone=timezone,
            freshness_seconds=email_freshness_seconds,
        ),
    )
    if error:
        email_result = {
            "state": "failed",
            "detail": error,
            "operational": 0,
            "review": 0,
        }
    assert email_result is not None
    counts["emails_operational"] = int(email_result["operational"])
    counts["emails_review"] = int(email_result["review"])
    email_count = counts["emails_operational"] + counts["emails_review"]
    sources.append(
        _source(
            "emails",
            "E-mails",
            "/web/mensagens",
            str(email_result["state"]),
            email_count,
            str(email_result["detail"]),
        )
    )

    for tipo, label, href, prefix in (
        ("pagar", "Contas a pagar", "/web/contas-a-pagar", "payables"),
        ("receber", "Contas a receber", "/web/contas-a-receber", "receivables"),
    ):
        entries, error = _run_source(
            db, lambda tipo=tipo: lancamento_service.list_lancamentos(db, tipo)
        )
        if error:
            sources.append(_source(prefix, label, href, "failed", 0, error))
            continue
        assert entries is not None
        relevant_entries = [
            entry
            for entry in entries
            if entry.status == "pendente"
            and entry.arquivado_em is None
            and entry.data_vencimento <= through
        ]
        overdue = [entry for entry in relevant_entries if entry.data_vencimento < today]
        upcoming = [
            entry for entry in relevant_entries if entry.data_vencimento >= today
        ]
        counts[f"{prefix}_overdue"] = len(overdue)
        counts[f"{prefix}_upcoming"] = len(upcoming)
        for entry in relevant_entries:
            overdue_flag = entry.data_vencimento < today
            items.append(
                {
                    "source": prefix,
                    "title": entry.descricao,
                    "href": href,
                    "due_date": entry.data_vencimento.isoformat(),
                    "status": "Atrasada" if overdue_flag else "Em aberto",
                    "supplier_or_client": entry.fornecedor
                    or (entry.client.razao_social if entry.client else None),
                    "reason": (
                        f"Vencimento ultrapassado em {entry.data_vencimento:%d/%m/%Y}."
                        if overdue_flag
                        else f"Vencimento em {entry.data_vencimento:%d/%m/%Y}."
                    ),
                    "rank": 0 if overdue_flag else 3,
                }
            )
        sources.append(
            _source(
                prefix,
                label,
                href,
                "success" if relevant_entries else "empty",
                len(relevant_entries),
                f"{len(overdue)} atrasada(s), {len(upcoming)} com vencimento hoje ou nos próximos {lookahead_days} dias."
                if relevant_entries
                else f"Nenhum lançamento pendente até {through:%d/%m/%Y}.",
            )
        )

    source_order = {
        "tasks": 0,
        "payables": 1,
        "receivables": 2,
        "services": 3,
        "schedule": 4,
    }
    items.sort(
        key=lambda item: (
            item.get("rank", 5),
            item.get("due_date") or "9999-12-31",
            source_order.get(str(item.get("source")), 9),
            item.get("order", 0),
            str(item.get("title", "")).casefold(),
        )
    )

    return {
        "reference_date": today.isoformat(),
        "queried_at": local_now.isoformat(timespec="minutes"),
        "timezone": timezone,
        "through_date": through.isoformat(),
        "counts": counts,
        "sources": sources,
        "items": items,
        "availability_configured": bool(
            schedule_result and schedule_result.availability_configured
        ),
    }
