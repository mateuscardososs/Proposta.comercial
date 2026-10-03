from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models import (
    EmailTaskLink,
    InboxEmail,
    Lancamento,
    ServiceCall,
    ServiceWorkflowStep,
    Task,
)


@dataclass(frozen=True)
class TodayItem:
    source_type: str
    source_id: int
    title: str
    href: str
    reason: str
    due_date: date | None
    rank: int
    email_origin: bool = False


@dataclass(frozen=True)
class TodaySummary:
    overdue: int
    due_today: int
    upcoming: int
    ongoing_services: int
    financial_attention: int
    email_review: int


@dataclass(frozen=True)
class TodayAgenda:
    today: date
    through: date
    items: list[TodayItem]
    summary: TodaySummary


def get_today_agenda(
    db: Session,
    *,
    today: date | None = None,
    lookahead_days: int = 7,
    timezone: str = "America/Recife",
) -> TodayAgenda:
    reference = today or datetime.now(ZoneInfo(timezone)).date()
    through = reference + timedelta(days=max(1, min(31, lookahead_days)))
    items: list[TodayItem] = []

    linked_tasks = {
        row.task_id
        for row in db.query(EmailTaskLink.task_id)
        .filter(EmailTaskLink.task_id.is_not(None))
        .all()
    }
    tasks = (
        db.query(Task)
        .options(joinedload(Task.client))
        .filter(Task.status != "concluido")
        .filter(
            or_(
                Task.prazo <= through,
                Task.id.in_(linked_tasks) if linked_tasks else Task.id == -1,
            )
        )
        .order_by(Task.prazo.asc().nullslast(), Task.id.asc())
        .all()
    )
    for task in tasks:
        overdue = task.prazo is not None and task.prazo < reference
        due_today = task.prazo == reference
        if overdue:
            reason, rank = f"Tarefa incompleta atrasada desde {task.prazo:%d/%m/%Y}.", 0
        elif due_today:
            reason, rank = "Prazo explícito para hoje.", 1
        elif task.prazo:
            reason, rank = f"Prazo explícito próximo: {task.prazo:%d/%m/%Y}.", 3
        else:
            reason, rank = (
                "Tarefa aberta sem prazo; aparece após os compromissos datados.",
                4,
            )
        items.append(
            TodayItem(
                source_type="task",
                source_id=task.id,
                title=task.titulo,
                href=f"/web/board/{task.id}/edit",
                reason=reason,
                due_date=task.prazo,
                rank=rank,
                email_origin=task.id in linked_tasks,
            )
        )

    service_rows = (
        db.query(ServiceCall)
        .options(joinedload(ServiceCall.client))
        .order_by(ServiceCall.opened_on.asc(), ServiceCall.id.asc())
        .all()
    )
    services: list[ServiceCall] = []
    for service in service_rows:
        next_step = (
            db.query(ServiceWorkflowStep)
            .filter(
                ServiceWorkflowStep.service_call_id == service.id,
                ServiceWorkflowStep.status.in_(("unknown", "pending")),
            )
            .order_by(ServiceWorkflowStep.id.asc())
            .first()
        )
        execution_active = service.execution_status in {"not_started", "in_progress"}
        if not execution_active and next_step is None:
            continue
        services.append(service)
        if service.execution_status == "in_progress":
            reason = (
                "Serviço em andamento; verificar execução e próxima etapa registrada."
            )
            rank = 2
        elif service.execution_status == "completed":
            reason = "Execução técnica concluída; o encerramento administrativo ainda tem etapa pendente."
            rank = 3
        else:
            reason = "Chamado aberto, execução ainda não iniciada."
            rank = 4
        if next_step:
            reason += (
                f" Etapa administrativa {next_step.step_type} está {next_step.status}."
            )
        items.append(
            TodayItem(
                source_type="service",
                source_id=service.id,
                title=f"{service.client.razao_social}: {service.summary}",
                href=f"/web/services/{service.id}",
                reason=reason,
                due_date=None,
                rank=rank,
            )
        )

    finance = (
        db.query(Lancamento)
        .filter(
            Lancamento.status == "pendente",
            Lancamento.data_vencimento <= through,
        )
        .order_by(Lancamento.data_vencimento.asc(), Lancamento.id.asc())
        .all()
    )
    for entry in finance:
        overdue = entry.data_vencimento < reference
        reason = (
            f"Conta a {entry.tipo} vencida desde {entry.data_vencimento:%d/%m/%Y}; requer conferência humana."
            if overdue
            else f"Conta a {entry.tipo} com vencimento em {entry.data_vencimento:%d/%m/%Y}; não houve baixa automática."
        )
        items.append(
            TodayItem(
                source_type="finance",
                source_id=entry.id,
                title=entry.descricao,
                href=f"/web/contas-a-{'pagar' if entry.tipo == 'pagar' else 'receber'}",
                reason=reason,
                due_date=entry.data_vencimento,
                rank=0 if overdue else 3,
            )
        )

    items.sort(
        key=lambda item: (
            item.rank,
            item.due_date or date.max,
            item.source_type,
            item.source_id,
        )
    )
    email_review = (
        db.query(InboxEmail).filter(InboxEmail.review_status == "pending").count()
    )
    return TodayAgenda(
        today=reference,
        through=through,
        items=items,
        summary=TodaySummary(
            overdue=sum(
                item.due_date is not None and item.due_date < reference
                for item in items
            ),
            due_today=sum(item.due_date == reference for item in items),
            upcoming=sum(
                item.due_date is not None and reference < item.due_date <= through
                for item in items
            ),
            ongoing_services=sum(
                service.execution_status == "in_progress" for service in services
            ),
            financial_attention=len(finance),
            email_review=email_review,
        ),
    )
