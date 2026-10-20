"""Read-only service-call query and assistant projection."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.assistant.contracts import AssistantReply, ServiceQueryCommand
from app.assistant.provider import ProviderToolResult
from app.models import Client
from app.schemas import ServiceCallQuery
from app.services import service_record_service


@dataclass(frozen=True)
class ServiceQueryExecution:
    reply: AssistantReply
    result: ProviderToolResult | None = None


def execute_service_query(
    db: Session, conversation_id: int, command: ServiceQueryCommand,
    resolve_client: Callable[[str | None], tuple[Client | None, str | None]],
) -> ServiceQueryExecution:
    client, question = resolve_client(command.client)
    if question:
        return ServiceQueryExecution(AssistantReply(
            conversation_id=conversation_id, kind="clarification", message=question,
        ))
    calls = service_record_service.list_service_calls(db, ServiceCallQuery(
        client_id=client.id if client else None,
        execution_status=command.execution_status,
        administrative_status=command.administrative_status,
        pending_only=command.pending_only,
        return_tasks_only=command.return_tasks_only,
        limit=command.limit,
    ))
    items = []
    for call in calls:
        effective_events = service_record_service.effective_service_events(call.events)
        recent_events = [
            {
                "event_type": item.event_type,
                "occurred_on": item.occurred_on.isoformat(),
                "description": item.description[:240],
            }
            for item in effective_events[-3:]
        ]
        pending = next((step.step_type for step in call.workflow_steps
                        if step.status in {"pending", "waiting_customer", "unknown"}), None)
        return_tasks = []
        if command.return_tasks_only:
            return_tasks = [
                {
                    "task_id": link.task.id,
                    "title": link.task.titulo,
                    "due_date": link.task.prazo.isoformat() if link.task.prazo else None,
                    "status": link.task.status,
                    "source_event_id": link.service_event_id,
                }
                for link in call.task_links
                if link.task is not None and link.step_type is None
                and link.service_event_id is not None and link.task.status != "concluido"
            ]
        items.append({
            "id": call.id, "client": call.client.razao_social,
            "summary": call.summary, "execution_status": call.execution_status,
            "administrative_status": call.administrative_status,
            "next_pending_step": pending, "opened_on": call.opened_on.isoformat(),
            "technically_completed_at": call.technically_completed_at.isoformat() if call.technically_completed_at else None,
            "administratively_closed_at": call.administratively_closed_at.isoformat() if call.administratively_closed_at else None,
            "workflow_steps": [
                {"step_type": step.step_type, "status": step.status}
                for step in call.workflow_steps
            ],
            "event_types": sorted({item.event_type for item in effective_events}),
            "effective_event_count": len(effective_events),
            "recent_events": recent_events,
            "return_tasks": return_tasks,
        })
    result = ProviderToolResult(
        tool="consultar_servicos", evidence_id=secrets.token_urlsafe(16),
        state="success" if items else "empty",
        payload={"count": len(items), "service_calls": items},
    )
    message = (
        "; ".join(
            f"#{item['id']} {item['client']}: {item['summary']}" + (
                "; retornos: " + ", ".join(
                    f"tarefa #{return_item['task_id']} {return_item['title']} "
                    f"(prazo {return_item['due_date'] or 'sem prazo'})"
                    for return_item in item["return_tasks"]
                ) if item["return_tasks"] else ""
            ) for item in items
        )
        if items else "Nenhum chamado encontrado para os filtros informados."
    )
    return ServiceQueryExecution(AssistantReply(
        conversation_id=conversation_id, kind="text", message=message,
    ), result)
