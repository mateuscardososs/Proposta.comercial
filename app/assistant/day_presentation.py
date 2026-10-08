from __future__ import annotations

from datetime import date, datetime

from app.assistant.contracts import AssistantReply
from app.assistant.provider import ProviderToolResult
from app.services.daily_schedule_service import DailySchedule
from app.services.today_service import TaskDayPlan


def present_daily_brief(conversation_id: int, brief: dict[str, object]) -> AssistantReply:
    counts = brief["counts"]
    assert isinstance(counts, dict)
    sources = brief["sources"]
    assert isinstance(sources, list)
    failed = [
        str(source["label"])
        for source in sources
        if isinstance(source, dict) and source.get("state") in {"failed", "unavailable", "partial"}
    ]
    date_label = datetime.fromisoformat(str(brief["queried_at"])).strftime("%d/%m/%Y às %H:%M")
    message = (
        f"Resumo operacional consultado em {date_label} ({brief['timezone']}). Consultei o quadro. "
        f"Tarefas abertas: {counts['tasks_open']}; {counts['tasks_overdue']} atrasadas e "
        f"{counts['tasks_today']} com prazo hoje. "
    )
    task_items = sorted(
        (item for item in brief["items"] if item.get("source") == "tasks"),
        key=lambda item: item.get("order", 0),
    )
    if not task_items:
        message += "Consultei o quadro: não há tarefas abertas. "
    else:
        if counts["tasks_today"] == 0:
            message += "Não há tarefa com prazo hoje; seguem as próximas pendências abertas relevantes. "
        message += "Ordem de tarefas sugerida, igual à página Hoje: "
        for position, item in enumerate(task_items, start=1):
            due = date.fromisoformat(item["due_date"]).strftime("%d/%m/%Y") if item.get("due_date") else "sem prazo"
            line = f"{position}. {item['title']} — Status: {item['status']}; Prioridade sugerida: {item['priority']}; prazo: {due}. Motivo: {item['reason']}"
            if item.get("client"):
                line += f" Cliente: {item['client']}."
            message += line + " "
        message += "O sistema não mantém dependências formais entre tarefas. "
    if brief["availability_configured"]:
        message += f"Agenda: {counts['schedule_blocks']} bloco(s) sugerido(s). "
        for item in brief["items"]:
            if item.get("source") != "schedule":
                continue
            start = datetime.fromisoformat(str(item["start"]))
            end = datetime.fromisoformat(str(item["end"]))
            block_type = (
                "Compromisso fixo"
                if item.get("fixed")
                else (
                    "estimativa padrão"
                    if item.get("duration_source") == "default_estimate"
                    else "duração estimada informada na tarefa"
                    if item.get("duration_is_estimate")
                    else "bloco de tarefa"
                )
            )
            duration = (
                f"; {item['duration_minutes']} min ({block_type})"
                if item.get("duration_minutes")
                else f" ({block_type})"
            )
            message += f"{start:%H:%M}–{end:%H:%M} — {item['title']}{duration}. "
    else:
        message += "Agenda: disponibilidade não configurada; nenhum horário foi presumido como livre. "
    message += (
        f"Serviços ativos ou com etapa pendente: {counts['service_items']}. "
        f"E-mails no cache: {counts['emails_operational']} operacionais e {counts['emails_review']} para revisão. "
        f"Contas a pagar: {counts['payables_overdue']} atrasadas e {counts['payables_upcoming']} próximas. "
        f"Contas a receber: {counts['receivables_overdue']} atrasadas e {counts['receivables_upcoming']} próximas."
    )
    if failed:
        message += " Fontes que precisam de atenção: " + ", ".join(failed) + "."
    message += " Consulte os detalhes e as telas de origem abaixo."
    overdue_label = "tarefa atrasada" if counts["tasks_overdue"] == 1 else "tarefas atrasadas"
    today_label = "tarefa com prazo hoje" if counts["tasks_today"] == 1 else "tarefas com prazo hoje"
    spoken_message = (
        f"Resumo de {datetime.fromisoformat(str(brief['queried_at'])):%d/%m}: "
        f"{counts['tasks_overdue']} {overdue_label}, {counts['tasks_today']} {today_label}, "
        f"{counts['service_items']} serviços pendentes, {counts['emails_operational']} e-mails operacionais "
        f"e {counts['emails_review']} para revisão. "
        f"A pagar: {counts['payables_overdue']} atrasadas e {counts['payables_upcoming']} próximas; "
        f"a receber: {counts['receivables_overdue']} atrasadas e {counts['receivables_upcoming']} próximas."
    )
    if not brief["availability_configured"]:
        spoken_message += " Não há disponibilidade configurada para sugerir horários."
    if failed:
        spoken_message += " Algumas fontes estão indisponíveis ou incompletas; veja os detalhes na tela."
    message += "Esta sugestão é somente leitura: não salva a agenda nem altera tarefas."
    return AssistantReply(
        conversation_id=conversation_id,
        kind="text",
        message=message,
        spoken_message=spoken_message,
        daily_brief=brief,
    )


def task_agenda_message(plan: TaskDayPlan, schedule: DailySchedule, today: date) -> str:
    if not plan.items:
        lines = ["Consultei o quadro: não há tarefas abertas."]
    else:
        lines = [
            f"Consultei todas as tarefas abertas do quadro e montei um plano para {today:%d/%m/%Y}.",
            "Sequência e prioridade sugeridas por prazo, urgência explicitamente registrada e situação; prioridade não é um campo salvo.",
        ]
        if plan.due_today_count == 0:
            lines.append("Não há tarefa com prazo hoje; seguem as próximas pendências abertas relevantes.")
        lines.append("Ordem sugerida pela prioridade compartilhada com a página Hoje:")
        for position, item in enumerate(plan.items, start=1):
            due_label = item.due_date.strftime("%d/%m/%Y") if item.due_date else "sem prazo"
            parts = [
                f"{position}. {item.title}",
                f"Status: {item.status_label}",
                f"Prioridade sugerida: {item.priority_label}",
                f"Prazo: {due_label}",
                f"Motivo: {item.reason}",
            ]
            if item.client_name:
                client = item.client_name
                if item.client_link_status == "pending_review":
                    client += " (vínculo pendente de revisão)"
                parts.append(f"Cliente: {client}")
            lines.append(" — ".join(parts))
        lines.append(
            "O sistema não registra dependências formais entre tarefas; usei apenas status e etapas representadas no quadro."
        )

    lines.append("Sugestão de blocos de horário (determinística e somente de leitura):")
    if not schedule.availability_configured:
        lines.append("A disponibilidade semanal não está configurada; nenhum horário foi presumido como livre.")
    else:
        for fixed in schedule.fixed_blocks:
            lines.append(
                f"{fixed.start:%H:%M}–{fixed.end:%H:%M} — {fixed.title} (compromisso/intervalo bloqueado)."
            )
    if schedule.availability_configured and schedule.blocks:
        for block in schedule.blocks:
            duration_label = (
                "estimativa padrão"
                if block.duration_source == "default_estimate"
                else "duração estimada informada na tarefa"
            )
            due_label = block.due_date.strftime("%d/%m/%Y") if block.due_date else "sem prazo"
            lines.append(
                f"{block.start:%H:%M}–{block.end:%H:%M} — {block.title}; "
                f"{block.duration_minutes} min ({duration_label}); {block.status_label}; "
                f"prazo {due_label}. Motivo: {block.reason}"
            )
    elif schedule.availability_configured:
        lines.append("Nenhuma tarefa coube nas janelas livres restantes de hoje.")
    if schedule.unscheduled:
        lines.append("Não alocadas:")
        lines.extend(f"- {item.title}: {item.reason}" for item in schedule.unscheduled)
    lines.append(
        "Visualizar ou gerar a sugestão não salva a agenda nem altera tarefas. Para salvar um snapshot, peça para salvar a agenda e confirme a prévia."
    )
    return "\n".join(lines)



def task_agenda_result(
    plan: TaskDayPlan,
    schedule: DailySchedule,
    today: date,
    duration_by_task: dict[int, int | None],
) -> ProviderToolResult:
    return ProviderToolResult(
        tool="consultar_tarefas",
        payload={
            "criteria": {
                "scope": "all_open_board_tasks",
                "reference_date": today.isoformat(),
                "read_only": True,
                "limited": False,
            },
            "tasks": [
                {
                    "id": item.task_id,
                    "title": item.title,
                    "status": item.status_label,
                    "priority_suggested": item.priority_label,
                    "priority_reason": item.reason,
                    "due_date": item.due_date.isoformat() if item.due_date else None,
                    "client": item.client_name,
                    "client_link_status": item.client_link_status,
                    "section": item.section_key,
                    "href": item.href,
                    "estimated_duration_minutes": duration_by_task.get(item.task_id),
                }
                for item in plan.items
            ],
            "schedule": schedule.snapshot(),
        },
    )
