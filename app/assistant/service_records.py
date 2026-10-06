"""Conversational adapter for service calls; domain mutations remain in the service layer."""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.assistant.contracts import (
    AssistantReply,
    ServiceDraftCorrectionCommand,
    ServiceEventDraftCommand,
    ServiceQueryCommand,
    ServiceReminderDraftCommand,
)
from app.assistant.dates import normalize_text, resolve_date_expression
from app.assistant.provider import ProviderToolResult
from app.models import (
    AssistantAction,
    AssistantMessage,
    Client,
    ServiceCall,
    ServiceEvent,
    ServiceTaskLink,
)
from app.schemas import (
    ServiceCallQuery,
    ServiceEventCorrectionCreate,
    ServiceEventCreate,
    ServiceReminderCreate,
    ServiceStepChange,
)
from app.services import service_record_service

EVENT_LABELS = {
    "call_received": "Chamado recebido", "visit_started": "Visita iniciada",
    "inspection": "Inspeção", "execution_started": "Execução iniciada",
    "execution_completed": "Execução concluída", "note": "Nota",
}
STEP_LABELS = {
    "report": "Relatório", "proposal": "Proposta", "proposal_sent": "Proposta enviada",
    "invoice": "Nota fiscal", "receipt": "Recebimento",
}
STEP_WORDS = {
    "report": ("relatorio",), "proposal": ("proposta",),
    "proposal_sent": ("proposta enviada", "enviei a proposta"),
    "invoice": ("nota fiscal", "fatura"), "receipt": ("recebimento", "pagamento recebido"),
}
STATUS_WORDS = {
    "pending": ("pendente", "falta", "a fazer"),
    "waiting_customer": ("aguardando cliente", "aguardando aprovacao", "esperando cliente"),
    "completed": ("concluido", "concluida", "feito", "feita", "pronto", "pronta"),
    "not_applicable": ("dispensado", "dispensada", "nao precisa", "nao sera necessario"),
}
STEP_STATUS_LABELS = {
    "pending": "Pendente", "waiting_customer": "Aguardando cliente",
    "completed": "Concluída", "not_applicable": "Dispensada",
}
EXECUTION_LABELS = {
    "not_started": "Não iniciada", "in_progress": "Em andamento", "completed": "Concluída",
}


@dataclass(frozen=True)
class ServiceQueryExecution:
    reply: AssistantReply
    result: ProviderToolResult | None = None


class AssistantServiceRecordAdapter:
    def __init__(
        self, db: Session, *, today: Callable[[], date],
        resolve_client: Callable[[str | None], tuple[Client | None, str | None]],
        resolve_user: Callable[[str | None], tuple[object | None, str | None]],
        token_hash: Callable[[str], str],
    ) -> None:
        self.db = db
        self.today = today
        self.resolve_client = resolve_client
        self.resolve_user = resolve_user
        self.token_hash = token_hash

    def execute_query(self, conversation_id: int, command: ServiceQueryCommand) -> ServiceQueryExecution:
        client, question = self.resolve_client(command.client)
        if question:
            return ServiceQueryExecution(AssistantReply(
                conversation_id=conversation_id, kind="clarification", message=question,
            ))
        calls = service_record_service.list_service_calls(self.db, ServiceCallQuery(
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

    def prepare_event(
        self, conversation_id: int, request_id: str,
        command: ServiceEventDraftCommand, source_message: str,
    ) -> AssistantReply:
        outstanding = self.db.query(AssistantAction).filter(
            AssistantAction.conversation_id == conversation_id,
            AssistantAction.action_type == "register_service_event",
            AssistantAction.status == "pending",
        ).order_by(AssistantAction.id.desc()).first()
        if outstanding is not None:
            return AssistantReply(
                conversation_id=conversation_id, kind="clarification",
                message="Há um registro aguardando confirmação. Quer corrigir esse rascunho ou cancelá-lo antes de preparar outro?",
            )
        previous = self._clarification(conversation_id)
        if previous is not None:
            old = ServiceEventDraftCommand.model_validate(previous.arguments_json["command"])
            command = command.model_copy(update={
                "client": command.client or old.client,
                "service_call_id": command.service_call_id or old.service_call_id,
                "summary": command.summary or old.summary,
                "event_type": command.event_type or old.event_type,
                "occurred_on": command.occurred_on or old.occurred_on,
                "description": command.description or old.description,
                "equipment": command.equipment or old.equipment,
                "reported_problem": command.reported_problem or old.reported_problem,
                "analysis": command.analysis or old.analysis,
                "work_performed": command.work_performed or old.work_performed,
                "return_on": command.return_on or old.return_on,
                "return_task_id": command.return_task_id or old.return_task_id,
                "return_result": command.return_result or old.return_result,
                "execution_completed_explicitly": (
                    command.execution_completed_explicitly or old.execution_completed_explicitly
                ),
                "step_changes": command.step_changes or old.step_changes,
            })
        prior_source = str(previous.arguments_json.get("source_message", "")) if previous else ""
        grounded_source = f"{prior_source} {source_message}".strip()
        source = normalize_text(grounded_source)
        event_type = command.event_type
        return_task_link = None
        return_result = command.return_result
        if command.return_task_id is not None or return_result is not None:
            if command.return_task_id is None or return_result is None:
                return self._ask(conversation_id, request_id, command, source_message,
                                 "Qual retorno você verificou e qual foi o resultado?")
            if command.return_task_id not in self._presented_return_task_ids(conversation_id):
                return self._ask(conversation_id, request_id, command, source_message,
                                 "Consulte primeiro os retornos pendentes apresentados nesta conversa.")
            return_task_link = self.db.query(ServiceTaskLink).filter(
                ServiceTaskLink.task_id == command.return_task_id,
                ServiceTaskLink.service_event_id.is_not(None),
                ServiceTaskLink.step_type.is_(None),
            ).first()
            if return_task_link is None or return_task_link.task is None or return_task_link.task.status == "concluido":
                return self._ask(conversation_id, request_id, command, source_message,
                                 "Esse retorno já foi encerrado ou não está mais pendente.")
            if not self._return_result_is_grounded(return_result, source):
                return self._ask(conversation_id, request_id, command, source_message,
                                 "A verificação resolveu o problema ou ele continua pendente?")
            event_type = "note"
        if event_type == "note" and return_task_link is not None:
            call = self.db.get(ServiceCall, return_task_link.service_call_id)
            client = self.db.get(Client, call.client_id) if call is not None else None
            if client is None:
                return self._ask(conversation_id, request_id, command, source_message,
                                 "Não encontrei o cliente vinculado ao retorno.")
            command = command.model_copy(update={
                "service_call_id": return_task_link.service_call_id,
                "client": client.razao_social,
            })
        else:
            client = None
        inspection_only = bool(re.search(r"\b(?:so|somente|apenas)\b.{0,30}\binspec|\bnao\b.{0,20}\bconser", source))
        if inspection_only and "inspec" in source:
            event_type = "inspection"
        elif event_type == "execution_completed" and not (
            command.execution_completed_explicitly
            and re.search(r"\b(?:terminei|terminou|conclui|concluido|finalizei|finalizado|consertei|reparei)\b", source)
        ):
            event_type = None
        elif event_type == "inspection" and "inspec" not in source:
            event_type = None
        elif event_type == "execution_started" and not re.search(r"\b(?:comecei|comecou|inici\w*|execut\w*)\b", source):
            event_type = None
        elif event_type == "visit_started" and not re.search(r"\b(?:visitei|visita|fui|estive)\b", source):
            event_type = None
        elif event_type == "call_received" and not re.search(r"\b(?:ligou|ligacao|chamado|telefon\w*)\b", source):
            event_type = None
        elif (event_type == "note" and return_task_link is None
              and not re.search(r"\b(?:nota|anot\w*|observ\w*|inform\w*)\b", source)):
            event_type = None
        if event_type is None:
            return self._ask(conversation_id, request_id, command, source_message,
                             "A execução terminou, ou foi apenas uma inspeção?")

        if return_task_link is None:
            client, question = self.resolve_client(command.client)
        else:
            question = None
        if client is None:
            return self._ask(conversation_id, request_id, command, source_message,
                             question or "Qual cliente devo vincular ao atendimento?")
        if command.client and return_task_link is None and normalize_text(command.client) not in source:
            return self._ask(conversation_id, request_id, command, source_message,
                             "Qual cliente devo vincular ao atendimento?")

        call_id = command.service_call_id
        open_calls = service_record_service.find_open_calls_for_client(self.db, client.id)
        if command.force_new_call or "novo chamado" in source or "outro chamado" in source:
            call_id = None
        elif call_id is not None:
            call = self.db.get(ServiceCall, call_id)
            if call is None or call.client_id != client.id or not self._was_presented(conversation_id, call_id, source_message):
                return self._ask(conversation_id, request_id, command, source_message,
                                 "Qual chamado apresentado nesta conversa devo usar?")
            if call.administrative_status == "closed" and return_task_link is None:
                return self._ask(conversation_id, request_id, command, source_message,
                                 "Esse chamado está encerrado. Você quer registrar uma correção ou abrir outro chamado?")
        elif len(open_calls) == 1:
            call_id = open_calls[0].id
        elif len(open_calls) > 1:
            ordinal = self._ordinal(source)
            choices = previous.arguments_json.get("call_options", []) if previous else []
            if ordinal is not None and ordinal < len(choices):
                call_id = int(choices[ordinal])
            else:
                options = "; ".join(f"{index}. #{call.id} {call.summary}" for index, call in enumerate(open_calls[:5], 1))
                return self._ask(conversation_id, request_id, command, source_message,
                                 f"Qual chamado da {client.razao_social}? {options}",
                                 call_options=[call.id for call in open_calls[:5]])

        date_text = command.occurred_on
        if date_text and normalize_text(date_text) not in source:
            date_text = None
        try:
            occurred_on = (
                self.today() - timedelta(days=1) if date_text and normalize_text(date_text) == "ontem"
                else resolve_date_expression(date_text, today=self.today()) or self.today()
            )
        except ValueError as exc:
            return self._ask(conversation_id, request_id, command, source_message, str(exc))
        description = (command.description or "").strip()
        if not description or normalize_text(description) not in source:
            description = grounded_source
        work_performed = (
            command.work_performed
            if command.work_performed and normalize_text(command.work_performed) in source
            else None
        )
        if (work_performed is None and command.description
                and normalize_text(command.description) in source
                and re.search(r"\b(?:consertei|reparei|troquei|substitui|ajustei|limpei|corrigi|reconectei|instalei)\b", source)):
            work_performed = command.description
        if event_type == "execution_completed" and work_performed is None:
            return self._ask(conversation_id, request_id, command, source_message,
                             "O que foi executado no serviço? Ainda não vou registrar sem esse detalhe.")
        summary = (command.summary or "").strip()
        if call_id is not None:
            summary = self.db.get(ServiceCall, call_id).summary
        elif not summary or normalize_text(summary) not in source:
            summary = description[:500]
        grounded_changes = []
        for change in command.step_changes:
            words = STEP_WORDS[change.step_type]
            cue_words = STATUS_WORDS.get(change.status, ())
            clauses = re.split(r"[;,.]", source)
            if any(any(word in clause for word in words)
                   and any(word in clause for word in cue_words) for clause in clauses):
                grounded_changes.append(ServiceStepChange(
                    step_type=change.step_type, status=change.status,
                    note=change.note if change.note and normalize_text(change.note) in source else "",
                ))
        return_on = None
        if command.return_on:
            if normalize_text(command.return_on) not in source:
                return self._ask(conversation_id, request_id, command, source_message,
                                 "Qual é a data combinada para o retorno?")
            try:
                return_on = resolve_date_expression(command.return_on, today=self.today())
            except ValueError as exc:
                return self._ask(conversation_id, request_id, command, source_message, str(exc))
        elif return_task_link is None and re.search(r"\b(?:preciso|devo|vou|precisamos)\s+(?:voltar|retornar)\b|\b(?:marcar|agendar)\s+retorno\b|\b(?:volto|voltar|retorno|retornar)\b", source):
            return self._ask(conversation_id, request_id, command, source_message,
                             "Qual data devo registrar para o retorno?")
        arguments = ServiceEventCreate(
            client_id=client.id, service_call_id=call_id,
            force_new_call=command.force_new_call or "novo chamado" in source or "outro chamado" in source,
            summary=summary, event_type=event_type, occurred_on=occurred_on,
            description=description, step_changes=grounded_changes,
            equipment=(command.equipment if command.equipment and normalize_text(command.equipment) in source else None),
            reported_problem=(command.reported_problem if command.reported_problem and normalize_text(command.reported_problem) in source else None),
            analysis=(command.analysis if command.analysis and normalize_text(command.analysis) in source else None),
            work_performed=work_performed,
            return_on=return_on,
            return_task_id=command.return_task_id if return_task_link is not None else None,
            return_result=return_result if return_task_link is not None else None,
        ).model_dump(mode="json")
        if previous is not None:
            previous.status = "cancelled"
        token = secrets.token_urlsafe(32)
        action = AssistantAction(
            conversation_id=conversation_id, request_id=request_id,
            confirmation_token_hash=self.token_hash(token),
            action_type="register_service_event", status="pending",
            arguments_json=arguments, result_json={},
        )
        self.db.add(action)
        self.db.flush()
        fields = {
            "cliente": client.razao_social,
            "chamado": f"#{call_id} — {summary}" if call_id else "Novo chamado",
            "evento": EVENT_LABELS[event_type],
            "data": occurred_on.strftime("%d/%m/%Y"),
            "execucao": EXECUTION_LABELS["completed" if event_type == "execution_completed" else
                                        "in_progress" if event_type == "execution_started" else
                                        self.db.get(ServiceCall, call_id).execution_status if call_id else "not_started"],
            "descricao": description,
            "equipamento": command.equipment if command.equipment and normalize_text(command.equipment) in source else "Não informado",
            "problema": command.reported_problem if command.reported_problem and normalize_text(command.reported_problem) in source else "Não informado",
            "analise": command.analysis if command.analysis and normalize_text(command.analysis) in source else "Não informada",
            "servico_executado": work_performed or "Não informado",
            "retorno": return_on.strftime("%d/%m/%Y") if return_on else "Não agendado",
            "etapas": "; ".join(f"{STEP_LABELS[change.step_type]}: {STEP_STATUS_LABELS[change.status]}"
                                 for change in grounded_changes) or "Não informadas",
        }
        return AssistantReply(
            conversation_id=conversation_id, kind="confirmation", action_id=action.id,
            confirmation_token=token, fields=fields,
            message=(f"Revise antes de registrar: {fields['evento']} em {fields['data']}; "
                     f"cliente {fields['cliente']}; chamado {fields['chamado']}; "
                     f"execução {fields['execucao']}; equipamento {fields['equipamento']}; "
                     f"problema {fields['problema']}; análise {fields['analise']}; "
                     f"serviço executado {fields['servico_executado']}; retorno {fields['retorno']}."),
        )

    def confirm(self, action: AssistantAction) -> AssistantReply:
        if action.action_type == "correct_service_event":
            payload = ServiceEventCorrectionCreate.model_validate(action.arguments_json)
            result = service_record_service.correct_event(
                self.db, payload, conversation_id=action.conversation_id,
                assistant_action_id=action.id, commit=False,
            )
            action.status = "executed"
            action.result_json = {
                "service_call_id": result.service_call.id,
                "service_event_id": result.event.id,
            }
            return self.success(action, correction=True)
        if action.action_type == "create_service_reminders":
            data = action.arguments_json
            reminders = [ServiceReminderCreate.model_validate(item) for item in data["reminders"]]
            tasks = service_record_service.create_reminders(
                self.db, service_call_id=int(data["service_call_id"]),
                assistant_action_id=action.id, reminders=reminders, commit=False,
            )
            action.status = "executed"
            action.result_json = {
                "service_call_id": int(data["service_call_id"]),
                "task_ids": [task.id for task in tasks],
            }
            return AssistantReply(
                conversation_id=action.conversation_id, kind="success", action_id=action.id,
                service_call_id=int(data["service_call_id"]),
                service_url=f"/web/services/{data['service_call_id']}",
                task_urls=[f"/web/board/{task.id}/edit" for task in tasks],
                message=f"Criei {len(tasks)} lembrete(s) no quadro para o chamado #{data['service_call_id']}.",
            )
        payload = ServiceEventCreate.model_validate(action.arguments_json)
        result = service_record_service.register_event(
            self.db, payload, conversation_id=action.conversation_id,
            assistant_action_id=action.id, commit=False,
        )
        action.status = "executed"
        return_task_ids = [int(link.task_id) for link in self.db.query(ServiceTaskLink).filter(
            ServiceTaskLink.assistant_action_id == action.id,
            ServiceTaskLink.task_id.is_not(None),
        ).order_by(ServiceTaskLink.id).all()]
        action.result_json = {
            "service_call_id": result.service_call.id,
            "service_event_id": result.event.id,
            "return_task_ids": return_task_ids,
        }
        return self.success(action)

    def success(self, action: AssistantAction, *, correction: bool = False) -> AssistantReply:
        call_id = int(action.result_json.get("service_call_id") or action.arguments_json["service_call_id"])
        if action.action_type == "create_service_reminders":
            task_ids = [int(item) for item in action.result_json.get("task_ids", [])]
            return AssistantReply(
                conversation_id=action.conversation_id, kind="success", action_id=action.id,
                service_call_id=call_id, service_url=f"/web/services/{call_id}",
                task_urls=[f"/web/board/{task_id}/edit" for task_id in task_ids],
                message=f"Criei {len(task_ids)} lembrete(s) no quadro para o chamado #{call_id}.",
            )
        event_id = int(action.result_json.get("service_event_id") or action.id)
        return_task_ids = [int(item) for item in action.result_json.get("return_task_ids", [])]
        completed = action.arguments_json.get("event_type") == "execution_completed"
        client_id = int(action.arguments_json.get("client_id") or 0)
        message = (
            f"Correção registrada como evento #{event_id} no chamado #{call_id}."
            if correction or action.action_type == "correct_service_event"
            else f"Evento #{event_id} registrado no chamado #{call_id}."
        )
        proposal_url = None
        if completed:
            message += (
                " A execução técnica está concluída; relatório e proposta continuam sendo etapas "
                "administrativas separadas. Posso ajudar a preparar a proposta no fluxo existente; "
                "não gerei nem enviei documentos."
            )
            if client_id:
                proposal_url = f"/web/proposals/new?client_id={client_id}"
        elif action.arguments_json.get("event_type") == "execution_started":
            message += " A execução segue em andamento; posso preparar um lembrete para verificar depois se foi concluída."
        return AssistantReply(
            conversation_id=action.conversation_id, kind="success", action_id=action.id,
            message=message,
            service_call_id=call_id, service_url=f"/web/services/{call_id}",
            task_urls=[f"/web/board/{task_id}/edit" for task_id in return_task_ids],
            proposal_url=proposal_url,
            fields={"chamado": str(call_id), "evento": str(event_id)},
        )

    def prepare_correction(
        self, conversation_id: int, request_id: str, command: ServiceDraftCorrectionCommand,
        source_message: str,
    ) -> AssistantReply:
        pending_draft = self.db.query(AssistantAction).filter(
            AssistantAction.conversation_id == conversation_id,
            AssistantAction.action_type == "register_service_event",
            AssistantAction.status == "pending",
        ).order_by(AssistantAction.id.desc()).first()
        if pending_draft is not None:
            return self._correct_pending_event_draft(
                pending_draft, request_id, command, source_message,
            )
        if not re.search(r"\b(?:corrig|na verdade|me enganei|errei|retific)", normalize_text(source_message)):
            return AssistantReply(conversation_id=conversation_id, kind="clarification",
                                  message="O que devo corrigir no registro do chamado?")
        client, question = self.resolve_client(command.client)
        if question:
            return AssistantReply(conversation_id=conversation_id, kind="clarification", message=question)
        event = None
        if command.event_id:
            event = self.db.get(ServiceEvent, command.event_id)
            if event is None or event.conversation_id != conversation_id:
                event = None
        else:
            query = self.db.query(ServiceEvent).filter(ServiceEvent.conversation_id == conversation_id)
            if client is not None:
                query = query.join(ServiceCall).filter(ServiceCall.client_id == client.id)
            event = query.order_by(ServiceEvent.id.desc()).first()
        if event is None:
            return AssistantReply(conversation_id=conversation_id, kind="clarification",
                                  message="Qual evento registrado nesta conversa devo corrigir?")
        if command.client and client is None:
            return AssistantReply(conversation_id=conversation_id, kind="clarification",
                                  message=question or "Qual cliente devo considerar?")
        if command.event_type is None and command.occurred_on is None and command.description is None:
            return AssistantReply(conversation_id=conversation_id, kind="clarification",
                                  message="O que mudou: o tipo de evento, a data ou a descrição?")
        normalized = normalize_text(source_message)
        corrected_type = command.event_type
        if corrected_type is not None:
            cues = {
                "inspection": ("inspecao", "vistoria"),
                "execution_completed": ("terminei", "concluido", "consertei", "reparei"),
                "execution_started": ("iniciei", "comecei", "iniciado"),
                "visit_started": ("visita", "fui", "estive"),
                "call_received": ("chamado", "ligacao"),
                "note": ("anotei", "registro", "nota"),
            }
            if not any(cue in normalized for cue in cues.get(corrected_type, ())):
                corrected_type = None
        if command.occurred_on and normalize_text(command.occurred_on) not in normalized:
            corrected_date = None
        else:
            try:
                corrected_date = resolve_date_expression(command.occurred_on, today=self.today())
            except ValueError:
                corrected_date = None
        description = command.description if command.description and normalize_text(command.description) in normalized else None
        if corrected_type is None and corrected_date is None and description is None:
            return AssistantReply(conversation_id=conversation_id, kind="clarification",
                                  message="Qual informação correta devo registrar?")
        call = self.db.get(ServiceCall, event.service_call_id)
        payload = ServiceEventCorrectionCreate(
            service_call_id=call.id, supersedes_event_id=event.id,
            occurred_on=self.today(), reason=source_message[:1000],
            corrected_event_type=corrected_type, corrected_occurred_on=corrected_date,
            corrected_description=description,
        )
        return self._prepare_confirm_action(
            conversation_id, request_id, "correct_service_event", payload.model_dump(mode="json"),
            {"chamado": f"#{call.id} — {call.summary}", "evento_original": f"#{event.id}",
             "correcao": corrected_type or description or "Data corrigida",
             **({"data_corrigida": corrected_date.strftime("%d/%m/%Y")} if corrected_date else {})},
            "Confirme para acrescentar uma correção ao histórico; o evento original será preservado.",
        )

    def _correct_pending_event_draft(self, action, request_id, command, source_message):
        normalized = normalize_text(source_message)
        changes = dict(action.arguments_json)
        changed = False
        if command.event_type is not None:
            cues = {
                "inspection": ("inspecao", "vistoria"),
                "execution_completed": ("terminei", "conclui", "finalizei"),
                "execution_started": ("iniciei", "comecei", "execucao iniciada"),
                "visit_started": ("visita", "fui", "estive"),
                "call_received": ("chamado", "ligacao"), "note": ("nota", "anotei"),
            }
            if any(cue in normalized for cue in cues.get(command.event_type, ())):
                changes["event_type"] = command.event_type
                if command.event_type == "execution_completed":
                    changes["execution_completed_explicitly"] = bool(
                        re.search(r"\b(?:terminei|conclui|finalizei)\b", normalized)
                    )
                changed = True
        if command.occurred_on and normalize_text(command.occurred_on) in normalized:
            resolved = resolve_date_expression(command.occurred_on, today=self.today())
            if resolved is not None:
                changes["occurred_on"] = resolved.isoformat()
                changed = True
        if command.return_on and normalize_text(command.return_on) in normalized:
            resolved_return = resolve_date_expression(command.return_on, today=self.today())
            if resolved_return is not None:
                changes["return_on"] = resolved_return.isoformat()
                changed = True
        if command.description and normalize_text(command.description) in normalized:
            changes["description"] = command.description
            changed = True
        for field in ("equipment", "reported_problem", "analysis", "work_performed"):
            value = getattr(command, field)
            if value and normalize_text(value) in normalized:
                changes[field] = value
                changed = True
        if command.client:
            client, question = self.resolve_client(command.client)
            if question:
                return AssistantReply(conversation_id=action.conversation_id, kind="clarification", message=question)
            if client is not None and normalize_text(client.razao_social) in normalized:
                changes["client_id"] = client.id
                changed = True
        if not changed:
            return AssistantReply(conversation_id=action.conversation_id, kind="clarification",
                                  message="O que devo corrigir no rascunho do registro?")
        updated = ServiceEventCreate.model_validate(changes)
        payload = updated.model_dump(mode="json")
        action.status = "cancelled"
        token = secrets.token_urlsafe(32)
        replacement = AssistantAction(
            conversation_id=action.conversation_id, request_id=request_id,
            confirmation_token_hash=self.token_hash(token), action_type="register_service_event",
            status="pending", arguments_json=payload, result_json={},
        )
        self.db.add(replacement)
        self.db.flush()
        client = self.db.get(Client, updated.client_id)
        fields = {
            "cliente": client.razao_social if client else "Cliente",
            "chamado": f"#{updated.service_call_id}" if updated.service_call_id else "Novo chamado",
            "evento": EVENT_LABELS[updated.event_type],
            "data": updated.occurred_on.strftime("%d/%m/%Y"),
            "execucao": EXECUTION_LABELS[
                "completed" if updated.event_type == "execution_completed" else
                "in_progress" if updated.event_type == "execution_started" else "not_started"
            ],
            "descricao": updated.description,
            "equipamento": updated.equipment or "Não informado",
            "problema": updated.reported_problem or "Não informado",
            "analise": updated.analysis or "Não informada",
            "servico_executado": updated.work_performed or "Não informado",
            "retorno": updated.return_on.strftime("%d/%m/%Y") if updated.return_on else "Não agendado",
            "etapas": "Mantidas do rascunho anterior",
        }
        return AssistantReply(
            conversation_id=action.conversation_id, kind="confirmation", action_id=replacement.id,
            confirmation_token=token, fields=fields,
            message=f"Atualizei o rascunho: {fields['evento']} em {fields['data']}, cliente {fields['cliente']}. Confirme para registrar.",
        )

    def prepare_reminders(
        self, conversation_id: int, request_id: str, command: ServiceReminderDraftCommand,
        source_message: str,
    ) -> AssistantReply:
        call = self.db.get(ServiceCall, command.service_call_id) if command.service_call_id else None
        if call is None:
            candidates = service_record_service.list_service_calls(self.db, ServiceCallQuery(pending_only=True, limit=10))
            shown = self._presented_call_ids(conversation_id)
            candidates = [item for item in candidates if item.id in shown]
            if len(candidates) != 1:
                return AssistantReply(conversation_id=conversation_id, kind="clarification",
                                      message="A qual chamado devo vincular os lembretes? Diga o número apresentado.")
            call = candidates[0]
        if call.id not in self._presented_call_ids(conversation_id):
            return AssistantReply(conversation_id=conversation_id, kind="clarification",
                                  message="Consulte primeiro o chamado ou indique um chamado apresentado nesta conversa.")
        reminders = []
        for item in command.reminders:
            if normalize_text(item.title) not in normalize_text(source_message):
                return AssistantReply(conversation_id=conversation_id, kind="clarification",
                                      message="Qual deve ser o título do lembrete?")
            user_id = None
            if item.responsible:
                user, question = self.resolve_user(item.responsible)
                if question or user is None:
                    return AssistantReply(conversation_id=conversation_id, kind="clarification",
                                          message=question or "Qual responsável cadastrado devo usar?")
                user_id = user.id
            due_date = None
            if item.due_date:
                if normalize_text(item.due_date) not in normalize_text(source_message):
                    return AssistantReply(conversation_id=conversation_id, kind="clarification",
                                          message="Qual prazo devo usar para esse lembrete?")
                try:
                    due_date = resolve_date_expression(item.due_date, today=self.today())
                except ValueError as exc:
                    return AssistantReply(conversation_id=conversation_id, kind="clarification", message=str(exc))
            reminders.append(ServiceReminderCreate(
                title=item.title, description=item.description, status=item.status,
                due_date=due_date, user_id=user_id, step_type=item.step_type,
            ).model_dump(mode="json"))
        return self._prepare_confirm_action(
            conversation_id, request_id, "create_service_reminders",
            {"service_call_id": call.id, "reminders": reminders},
            {"chamado": f"#{call.id} — {call.summary}", "lembretes": "; ".join(
                f"{item['title']}" + (f" — {date.fromisoformat(item['due_date']).strftime('%d/%m/%Y')}" if item["due_date"] else "")
                for item in reminders
            )},
            "Confirme para criar os lembretes no quadro.",
        )

    def _prepare_confirm_action(self, conversation_id, request_id, action_type, arguments, fields, prompt):
        token = secrets.token_urlsafe(32)
        action = AssistantAction(
            conversation_id=conversation_id, request_id=request_id,
            confirmation_token_hash=self.token_hash(token), action_type=action_type,
            status="pending", arguments_json=arguments, result_json={},
        )
        self.db.add(action)
        self.db.flush()
        return AssistantReply(conversation_id=conversation_id, kind="confirmation",
                              action_id=action.id, confirmation_token=token, fields=fields,
                              message=prompt)

    def _presented_call_ids(self, conversation_id: int) -> set[int]:
        rows = self.db.query(AssistantMessage).filter(
            AssistantMessage.conversation_id == conversation_id,
            AssistantMessage.role == "assistant",
        ).order_by(AssistantMessage.id.desc()).limit(30).all()
        ids = set()
        for row in rows:
            ids.update(item.get("id") for item in row.details_json.get("service_calls", [])
                       if isinstance(item, dict) and isinstance(item.get("id"), int))
        return ids

    def _presented_return_task_ids(self, conversation_id: int) -> set[int]:
        rows = self.db.query(AssistantMessage).filter(
            AssistantMessage.conversation_id == conversation_id,
            AssistantMessage.role == "assistant",
        ).order_by(AssistantMessage.id.desc()).limit(30).all()
        ids = set()
        for row in rows:
            for call in row.details_json.get("service_calls", []):
                if not isinstance(call, dict):
                    continue
                for task in call.get("return_tasks", []):
                    if isinstance(task, dict) and isinstance(task.get("task_id"), int):
                        ids.add(task["task_id"])
        return ids

    @staticmethod
    def _return_result_is_grounded(result: str, source: str) -> bool:
        resolved = re.search(
            r"\b(?:resolvid\w*|funcionou|normaliz\w*|voltou ao normal|funcionando)\b", source,
        )
        pending = re.search(
            r"\b(?:continua|ainda|nao resolveu|nao funcionou|pendente|precisa voltar)\b", source,
        )
        return bool(resolved if result == "resolved" else pending)

    def _ask(self, conversation_id, request_id, command, source_message, question, *, call_options=None):
        old = self._clarification(conversation_id)
        prior_source = str(old.arguments_json.get("source_message", "")) if old else ""
        retained_source = f"{prior_source} {source_message}".strip()
        if old is not None:
            old.status = "cancelled"
        self.db.add(AssistantAction(
            conversation_id=conversation_id, request_id=request_id,
            confirmation_token_hash=self.token_hash(secrets.token_urlsafe(32)),
            action_type="register_service_event", status="needs_clarification",
            arguments_json={"command": command.model_dump(mode="json"),
                            "source_message": retained_source, "call_options": call_options or []},
            result_json={},
        ))
        self.db.flush()
        return AssistantReply(conversation_id=conversation_id, kind="clarification", message=question)

    def _clarification(self, conversation_id: int) -> AssistantAction | None:
        return self.db.query(AssistantAction).filter(
            AssistantAction.conversation_id == conversation_id,
            AssistantAction.action_type == "register_service_event",
            AssistantAction.status == "needs_clarification",
        ).order_by(AssistantAction.id.desc()).first()

    def _was_presented(self, conversation_id: int, call_id: int, source_message: str) -> bool:
        if re.search(rf"(?:#|\bchamado\s+(?:numero\s+|n[ºo]\s*)?){call_id}(?!\d)", normalize_text(source_message)):
            return True
        rows = self.db.query(AssistantMessage).filter(
            AssistantMessage.conversation_id == conversation_id,
            AssistantMessage.role == "assistant",
        ).order_by(AssistantMessage.id.desc()).limit(20).all()
        return any(call_id in [item.get("id") for item in row.details_json.get("service_calls", [])
                               if isinstance(item, dict)] for row in rows)

    @staticmethod
    def _ordinal(source: str) -> int | None:
        for word, index in (("primeiro", 0), ("segundo", 1), ("terceiro", 2), ("quarto", 3), ("quinto", 4)):
            if re.search(rf"\b{word}\b", source):
                return index
        return None
