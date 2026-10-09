"""Preparation and correction of assistant task drafts."""
from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.assistant.contracts import (
    AssistantReply,
    TaskCreateCommand,
    TaskDraftCorrectionCommand,
)
from app.assistant.dates import resolve_date_expression
from app.models import AssistantAction, Client, Proposal, User
from app.services.today_service import TASK_STATUS_LABELS

STATUS_LABELS = TASK_STATUS_LABELS


class AssistantTaskDraftAdapter:
    def __init__(
        self, db: Session, *, token_hash: Callable[[str], str],
        resolve_task_client: Callable[[str | None], tuple[Client | None, str | None, str]],
        resolve_user: Callable[[str | None], tuple[User | None, str | None]],
    ) -> None:
        self.db = db
        self.token_hash = token_hash
        self.resolve_task_client = resolve_task_client
        self.resolve_user = resolve_user

    def correct(
        self,
        conversation_id: int,
        request_id: str,
        command: TaskDraftCorrectionCommand,
        today: date,
    ) -> AssistantReply:
        action = (
            self.db.query(AssistantAction)
            .filter(
                AssistantAction.conversation_id == conversation_id,
                AssistantAction.action_type == "create_task",
                AssistantAction.status.in_(("pending", "needs_clarification")),
            )
            .order_by(AssistantAction.id.desc())
            .first()
        )
        if action is None:
            return AssistantReply(
                conversation_id=conversation_id,
                kind="clarification",
                message="Nao ha um rascunho pendente para corrigir.",
            )

        if action.status == "needs_clarification":
            draft = TaskCreateCommand.model_validate(action.arguments_json)
            updates: dict[str, object] = {}
            if command.title is not None:
                updates["title"] = command.title
            if command.clear_due_date:
                updates["due_date"] = None
            elif command.due_date is not None:
                updates["due_date"] = command.due_date
            if command.clear_client:
                updates["client"] = None
            elif command.client is not None:
                updates["client"] = command.client
            if command.clear_responsible:
                updates["responsible"] = None
            elif command.responsible is not None:
                updates["responsible"] = command.responsible
            if command.estimated_duration_minutes is not None:
                updates["estimated_duration_minutes"] = command.estimated_duration_minutes
            return self.prepare(
                conversation_id,
                action.request_id or request_id,
                draft.model_copy(update=updates),
                today,
                existing_action=action,
            )

        arguments = dict(action.arguments_json)
        if command.title is not None:
            title = command.title.strip()
            if not title:
                return AssistantReply(
                    conversation_id=conversation_id,
                    kind="clarification",
                    message="Qual deve ser o novo titulo da tarefa?",
                )
            arguments["titulo"] = title

        if command.clear_due_date:
            arguments["prazo"] = None
        elif command.due_date is not None:
            try:
                due_date = resolve_date_expression(command.due_date, today=today)
            except ValueError as exc:
                return AssistantReply(
                    conversation_id=conversation_id,
                    kind="clarification",
                    message=str(exc),
                )
            arguments["prazo"] = due_date.isoformat() if due_date else None

        if command.clear_client:
            if arguments.get("proposal_id"):
                return AssistantReply(
                    conversation_id=conversation_id,
                    kind="clarification",
                    message="A tarefa esta vinculada a uma proposta; o cliente nao pode ser removido aqui.",
                )
            arguments["client_id"] = None
            arguments["client_name"] = None
            arguments["client_link_status"] = "unlinked"
        elif command.client is not None:
            client, client_name, link_status = self.resolve_task_client(command.client)
            if arguments.get("proposal_id") and client is None:
                return AssistantReply(
                    conversation_id=conversation_id,
                    kind="clarification",
                    message="A tarefa está vinculada a uma proposta. Confirme o cliente cadastrado antes de alterar esse vínculo.",
                )
            if arguments.get("proposal_id"):
                proposal = self.db.get(Proposal, int(arguments["proposal_id"]))
                if proposal is None or client is None or proposal.client_id != client.id:
                    return AssistantReply(
                        conversation_id=conversation_id,
                        kind="clarification",
                        message="A proposta informada pertence a outro cliente. Qual vinculo devo usar?",
                    )
            arguments["client_id"] = client.id if client else None
            arguments["client_name"] = client_name
            arguments["client_link_status"] = link_status

        if command.clear_responsible:
            arguments["user_id"] = None
        elif command.responsible is not None:
            user, question = self.resolve_user(command.responsible)
            if question:
                return AssistantReply(
                    conversation_id=conversation_id,
                    kind="clarification",
                    message=question,
                )
            arguments["user_id"] = user.id

        if command.estimated_duration_minutes is not None:
            arguments["estimated_duration_minutes"] = command.estimated_duration_minutes

        confirmation_token = secrets.token_urlsafe(32)
        action.arguments_json = arguments
        action.confirmation_token_hash = self.token_hash(confirmation_token)
        self.db.flush()
        return self.confirmation_reply(action, confirmation_token)


    def prepare(
        self,
        conversation_id: int,
        request_id: str,
        command: TaskCreateCommand,
        today: date,
        *,
        existing_action: AssistantAction | None = None,
    ) -> AssistantReply:
        title = (command.title or "").strip()
        if not title:
            return AssistantReply(
                conversation_id=conversation_id,
                kind="clarification",
                message="Qual deve ser o titulo da tarefa?",
            )
        try:
            due_date = resolve_date_expression(command.due_date, today=today)
        except ValueError as exc:
            return AssistantReply(conversation_id=conversation_id, kind="clarification", message=str(exc))

        client, client_name, client_link_status = self.resolve_task_client(command.client)
        user, user_question = self.resolve_user(command.responsible)
        if user_question:
            if existing_action is not None:
                existing_action.arguments_json = command.model_dump(mode="json")
                existing_action.status = "needs_clarification"
                self.db.flush()
            else:
                self.record_clarification(conversation_id, request_id, command)
            return AssistantReply(
                conversation_id=conversation_id,
                kind="clarification",
                message=user_question,
            )

        proposal: Proposal | None = None
        if command.proposal_number is not None:
            proposals = (
                self.db.query(Proposal)
                .filter(Proposal.numero == command.proposal_number)
                .order_by(Proposal.revisao.desc())
                .all()
            )
            if not proposals:
                return AssistantReply(
                    conversation_id=conversation_id,
                    kind="clarification",
                    message=f"Nao encontrei a proposta {command.proposal_number}.",
                )
            if len(proposals) > 1:
                revisions = ", ".join(proposal.revisao for proposal in proposals)
                return AssistantReply(
                    conversation_id=conversation_id,
                    kind="clarification",
                    message=(
                        f"A proposta {command.proposal_number} possui as revisoes {revisions}. Informe a revisao pela tela do quadro antes de vincular pelo assistente."
                    ),
                )
            proposal = proposals[0]
            if client is None:
                if command.client:
                    self.record_clarification(conversation_id, request_id, command)
                    return AssistantReply(
                        conversation_id=conversation_id,
                        kind="clarification",
                        message="A proposta tem um cliente cadastrado. Confirme se devo usar esse cliente ou deixe a tarefa sem vínculo com a proposta.",
                    )
                client = self.db.get(Client, proposal.client_id)
                client_name = client.razao_social if client else None
                client_link_status = "linked" if client else "unlinked"
            elif proposal.client_id != client.id:
                return AssistantReply(
                    conversation_id=conversation_id,
                    kind="clarification",
                    message="A proposta informada pertence a outro cliente. Qual vinculo devo usar?",
                )

        arguments: dict[str, object] = {
            "titulo": title,
            "descricao": command.description.strip(),
            "status": command.status,
            "prazo": due_date.isoformat() if due_date else None,
            "client_id": client.id if client else None,
            "client_name": client_name,
            "client_link_status": client_link_status,
            "proposal_id": proposal.id if proposal else None,
            "user_id": user.id if user else None,
            "source_email_reference": command.source_email_reference,
            "estimated_duration_minutes": command.estimated_duration_minutes,
        }
        confirmation_token = secrets.token_urlsafe(32)
        action = existing_action or AssistantAction(
            conversation_id=conversation_id,
            request_id=request_id,
            confirmation_token_hash=self.token_hash(confirmation_token),
            action_type="create_task",
            status="pending",
            arguments_json=arguments,
            result_json={},
        )
        action.arguments_json = arguments
        action.confirmation_token_hash = self.token_hash(confirmation_token)
        action.status = "pending"
        if existing_action is None:
            self.db.add(action)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.query(AssistantAction).filter(AssistantAction.request_id == request_id).first()
            if existing is None:
                raise
            action = existing

        return self.confirmation_reply(action, confirmation_token)


    def confirmation_reply(
        self,
        action: AssistantAction,
        confirmation_token: str,
    ) -> AssistantReply:
        arguments = action.arguments_json
        due_date = date.fromisoformat(str(arguments["prazo"])) if arguments.get("prazo") else None
        client = self.db.get(Client, int(arguments["client_id"])) if arguments.get("client_id") else None
        user = self.db.get(User, int(arguments["user_id"])) if arguments.get("user_id") else None
        status_value = str(arguments.get("status") or "a_fazer")
        fields = {
            "titulo": str(arguments["titulo"]),
            "status": STATUS_LABELS[status_value],
            "prazo": due_date.strftime("%d/%m/%Y") if due_date else "Sem prazo",
            "cliente": (
                client.razao_social
                if client
                else f"{arguments['client_name']} (cliente a confirmar)"
                if arguments.get("client_link_status") == "needs_confirmation"
                else f"{arguments['client_name']} (vínculo pendente de revisão)"
                if arguments.get("client_link_status") == "pending_review"
                else "Sem cliente"
            ),
            "responsavel": user.nome if user else "Sem responsavel",
            "duracao_estimada": (
                f"{arguments['estimated_duration_minutes']} minutos (estimativa)"
                if arguments.get("estimated_duration_minutes")
                else "Não informada; a agenda usará a estimativa padrão configurada."
            ),
        }
        message = (
            "Revise antes de criar: "
            f"{fields['titulo']}; status {fields['status']}; prazo {fields['prazo']}; "
            f"cliente {fields['cliente']}; responsavel {fields['responsavel']}; "
            f"duração {fields['duracao_estimada']}."
        )
        if arguments.get("client_link_status") in {
            "pending_review",
            "needs_confirmation",
        }:
            message += " Não criei nem alterei cadastro de cliente."
        return AssistantReply(
            conversation_id=action.conversation_id,
            kind="confirmation",
            message=message,
            action_id=action.id,
            confirmation_token=confirmation_token,
            fields=fields,
        )


    def record_clarification(
        self,
        conversation_id: int,
        request_id: str,
        command: TaskCreateCommand,
    ) -> None:
        exists = self.db.query(AssistantAction).filter(AssistantAction.request_id == request_id).first()
        if exists is None:
            clarification_token = secrets.token_urlsafe(32)
            self.db.add(
                AssistantAction(
                    conversation_id=conversation_id,
                    request_id=request_id,
                    confirmation_token_hash=self.token_hash(clarification_token),
                    action_type="create_task",
                    status="needs_clarification",
                    arguments_json=command.model_dump(mode="json"),
                    result_json={},
                )
            )
            self.db.flush()
