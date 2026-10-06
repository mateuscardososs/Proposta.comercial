from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, joinedload

from app.models import (
    EmailTaskLink,
    InboxEmail,
    Lancamento,
    ServiceCall,
    ServiceWorkflowStep,
)
from app.services import board_service

TASK_STATUS_LABELS = {
    "a_fazer": "A fazer",
    "em_andamento": "Em andamento",
    "servico_feito_falta_nota_pedido": "Serviço feito — falta nota/pedido",
    "aguardando_cliente": "Aguardando cliente",
    "concluido": "Concluído",
}


@dataclass(frozen=True)
class TaskPlanItem:
    task_id: int
    title: str
    status: str
    status_label: str
    priority_label: str
    due_date: date | None
    client_name: str | None
    client_link_status: str
    reason: str
    section_key: str
    section_label: str
    href: str


@dataclass(frozen=True)
class TaskPlanSection:
    key: str
    label: str
    items: tuple[TaskPlanItem, ...]


@dataclass(frozen=True)
class TaskDayPlan:
    today: date
    items: tuple[TaskPlanItem, ...]
    sections: tuple[TaskPlanSection, ...]
    open_count: int
    due_today_count: int
    overdue_count: int


def get_task_day_plan(db: Session, *, today: date) -> TaskDayPlan:
    """Build a read-only, complete sequence from the same tasks shown on the board."""
    urgency_markers = (
        "urgente",
        "prioridade alta",
        "alta prioridade",
        "critico",
        "critica",
    )
    section_labels = {
        "overdue": "Atrasadas",
        "today": "Com prazo hoje",
        "explicit_urgency": "Urgência explícita",
        "admin_follow_up": "Execução concluída, etapa administrativa pendente",
        "in_progress": "Em andamento",
        "upcoming": "Próximos prazos",
        "no_deadline": "Sem prazo",
        "waiting_customer": "Aguardando cliente",
    }
    section_order = tuple(section_labels)
    ranked: list[tuple[tuple[int, date, int, int, int], TaskPlanItem]] = []
    for task in board_service.get_tasks(db):
        if task.status == "concluido":
            continue
        text = f"{task.titulo} {task.descricao}".casefold()
        explicit_urgency = any(marker in text for marker in urgency_markers)
        if task.prazo is not None and task.prazo < today:
            key, reason = "overdue", f"Tarefa atrasada: prazo vencido em {task.prazo:%d/%m/%Y}; permanece incompleta."
        elif task.prazo == today:
            key, reason = "today", "Prazo explicitamente cadastrado para hoje."
        elif explicit_urgency:
            key, reason = "explicit_urgency", "O título ou a descrição marca urgência explicitamente; não há prazo vencido ou de hoje."
        elif task.status == "servico_feito_falta_nota_pedido":
            key, reason = "admin_follow_up", "O status registra execução concluída com etapa documental pendente."
        elif task.status == "em_andamento":
            key, reason = "in_progress", "A tarefa já está em andamento e não tem prazo vencido ou de hoje."
        elif task.prazo is not None:
            key, reason = "upcoming", f"Próximo prazo registrado: {task.prazo:%d/%m/%Y}."
        elif task.status == "aguardando_cliente":
            key, reason = "waiting_customer", "O status registra espera por retorno do cliente; não há data de retorno cadastrada."
        else:
            key, reason = "no_deadline", "Tarefa aberta sem prazo registrado; aparece depois das tarefas datadas e das etapas em andamento."

        client_name = task.client.razao_social if task.client else task.client_name
        link_status = (
            "linked"
            if task.client
            else "pending_review"
            if client_name
            else task.client_link_status
        )
        item = TaskPlanItem(
            task_id=task.id,
            title=task.titulo,
            status=task.status,
            status_label=TASK_STATUS_LABELS.get(task.status, task.status),
            priority_label="Urgente" if explicit_urgency else "Não definida",
            due_date=task.prazo,
            client_name=client_name,
            client_link_status=link_status,
            reason=reason,
            section_key=key,
            section_label=section_labels[key],
            href=f"/web/board/{task.id}/edit",
        )
        ranked.append(
            (
                (
                    section_order.index(key),
                    task.prazo or date.max,
                    0 if explicit_urgency else 1,
                    task.ordem,
                    task.id,
                ),
                item,
            )
        )

    ranked.sort(key=lambda pair: pair[0])
    items = tuple(item for _, item in ranked)
    sections = tuple(
        TaskPlanSection(key, section_labels[key], tuple(item for item in items if item.section_key == key))
        for key in section_order
        if any(item.section_key == key for item in items)
    )
    return TaskDayPlan(
        today=today,
        items=items,
        sections=sections,
        open_count=len(items),
        due_today_count=sum(item.due_date == today for item in items),
        overdue_count=sum(item.due_date is not None and item.due_date < today for item in items),
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
    task_plan: TaskDayPlan


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

    task_plan = get_task_day_plan(db, today=reference)

    linked_tasks = {
        row.task_id
        for row in db.query(EmailTaskLink.task_id)
        .filter(EmailTaskLink.task_id.is_not(None))
        .all()
    }
    for plan_item in task_plan.items:
        if plan_item.due_date is not None and plan_item.due_date > through and plan_item.task_id not in linked_tasks:
            continue
        items.append(
            TodayItem(
                source_type="task",
                source_id=plan_item.task_id,
                title=plan_item.title,
                href=plan_item.href,
                reason=plan_item.reason,
                due_date=plan_item.due_date,
                rank=0 if plan_item.section_key == "overdue" else 1 if plan_item.section_key == "today" else 3 if plan_item.due_date else 4,
                email_origin=plan_item.task_id in linked_tasks,
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
        task_plan=task_plan,
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
