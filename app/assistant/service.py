from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from typing import TypeVar
from zoneinfo import ZoneInfo

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.assistant.contracts import (
    AssistantMessageView,
    AssistantReply,
    CancelActionCommand,
    ConfirmActionCommand,
    TaskCreateCommand,
    TaskDraftCorrectionCommand,
    TaskQueryCommand,
    UnsupportedCommand,
)
from app.assistant.dates import normalize_text, resolve_date_expression
from app.assistant.provider import (
    AssistantProvider,
    ProviderMessage,
    ProviderResponseError,
    ProviderUnavailableError,
)
from app.models import (
    AssistantAction,
    AssistantConversation,
    AssistantMessage,
    AssistantRequest,
    Client,
    Proposal,
    User,
)
from app.schemas import TaskCreate
from app.services import board_service

ModelT = TypeVar("ModelT", Client, User)

STATUS_LABELS = {
    "a_fazer": "A fazer",
    "em_andamento": "Em andamento",
    "servico_feito_falta_nota_pedido": "Servico feito — falta nota/pedido",
    "aguardando_cliente": "Aguardando cliente",
    "concluido": "Concluido",
}


class AssistantService:
    def __init__(
        self,
        db: Session,
        provider: AssistantProvider | None,
        *,
        now: Callable[[], datetime] | None = None,
        timezone: str = "America/Recife",
        context_messages: int = 12,
        request_lease_seconds: int = 120,
    ) -> None:
        self.db = db
        self.provider = provider
        self.timezone_name = timezone
        self.timezone = ZoneInfo(timezone)
        self.now = now or (lambda: datetime.now(self.timezone))
        self.context_messages = max(2, min(context_messages, 30))
        self.request_lease_seconds = max(30, min(request_lease_seconds, 900))

    def handle_message(
        self,
        *,
        message: str,
        request_id: str,
        conversation_id: int | None = None,
    ) -> AssistantReply:
        clean_message = message.strip()
        clean_request_id = request_id.strip()
        if not clean_message:
            raise ValueError("A mensagem nao pode ficar vazia.")
        if len(clean_message) > 4000:
            raise ValueError("A mensagem deve ter no maximo 4000 caracteres.")
        if not clean_request_id or len(clean_request_id) > 100:
            raise ValueError("Identificador de requisicao invalido.")

        cached = self._cached_reply(clean_request_id)
        if cached is not None:
            return cached

        claimed_request = self._claim_or_create_request(
            message=clean_message,
            request_id=clean_request_id,
            conversation_id=conversation_id,
        )
        if isinstance(claimed_request, AssistantReply):
            return claimed_request
        conversation = claimed_request

        current_date = self._local_now().date()
        try:
            direct_control = self._direct_control_command(clean_message)
            command = direct_control
            if command is None:
                if self.provider is None:
                    raise ProviderUnavailableError("Provedor nao configurado.")
                command = self.provider.interpret(
                    self._provider_messages(conversation.id),
                    today=current_date,
                    timezone=self.timezone_name,
                )
            if direct_control is None and isinstance(
                command, (ConfirmActionCommand, CancelActionCommand)
            ):
                reply = AssistantReply(
                    conversation_id=conversation.id,
                    kind="clarification",
                    message=(
                        "Nao entendi essa confirmacao com seguranca. "
                        "Diga 'Pode criar' para confirmar ou 'Cancela' para cancelar."
                    ),
                )
            elif isinstance(command, TaskQueryCommand):
                reply = self._query_tasks(conversation.id, command, current_date)
            elif isinstance(command, TaskCreateCommand):
                reply = self._prepare_task(
                    conversation.id,
                    clean_request_id,
                    command,
                    current_date,
                )
            elif isinstance(command, ConfirmActionCommand):
                reply = self._confirm_latest(conversation.id)
            elif isinstance(command, CancelActionCommand):
                reply = self._cancel_latest(conversation.id)
            elif isinstance(command, TaskDraftCorrectionCommand):
                reply = self._correct_pending_task(conversation.id, command, current_date)
            elif isinstance(command, UnsupportedCommand):
                reply = AssistantReply(
                    conversation_id=conversation.id,
                    kind="error",
                    message=command.message,
                )
            else:  # pragma: no cover - protected by the provider contract
                raise ProviderResponseError("Comando desconhecido.")
        except ProviderUnavailableError:
            reply = AssistantReply(
                conversation_id=conversation.id,
                kind="error",
                message=(
                    "O Ollama ou o modelo configurado nao esta disponivel. "
                    "Confira se o Ollama esta iniciado e se OLLAMA_MODEL corresponde a um modelo instalado."
                ),
            )
        except ProviderResponseError:
            reply = AssistantReply(
                conversation_id=conversation.id,
                kind="error",
                message=(
                    "O Ollama respondeu fora do formato esperado. "
                    "Nada foi alterado; reformule a mensagem e tente novamente."
                ),
            )

        return self._save_reply(clean_request_id, reply)

    @staticmethod
    def _direct_control_command(
        message: str,
    ) -> ConfirmActionCommand | CancelActionCommand | None:
        normalized = re.sub(r"[^a-z0-9 ]+", " ", normalize_text(message))
        normalized = " ".join(normalized.split())
        if normalized in {"pode criar", "pode confirmar", "confirmo", "sim pode criar"}:
            return ConfirmActionCommand()
        if normalized in {"cancela", "cancelar", "nao cancela"}:
            return CancelActionCommand()
        return None

    def confirm_action(self, action_id: int, confirmation_token: str) -> AssistantReply:
        action = self.db.get(AssistantAction, action_id)
        if action is None:
            raise ValueError("Acao de confirmacao nao encontrada.")
        self._validate_confirmation_token(action, confirmation_token)
        return self._confirm_action_record(action, record_message=True)

    def _confirm_action_record(
        self,
        action: AssistantAction,
        *,
        record_message: bool,
    ) -> AssistantReply:
        if action.status == "executed":
            return self._success_reply(action)
        if action.status == "cancelled":
            raise ValueError("Esta acao foi cancelada.")

        claimed = self.db.execute(
            update(AssistantAction)
            .where(AssistantAction.id == action.id, AssistantAction.status == "pending")
            .values(status="executing"),
            execution_options={"synchronize_session": False},
        )
        if claimed.rowcount != 1:
            self.db.rollback()
            refreshed = self.db.get(AssistantAction, action.id)
            if refreshed is not None and refreshed.status == "executed":
                return self._success_reply(refreshed)
            raise ValueError("A acao ja esta sendo processada. Consulte o historico antes de repetir.")

        arguments = action.arguments_json
        try:
            payload = TaskCreate(
                titulo=str(arguments["titulo"]),
                descricao=str(arguments.get("descricao") or ""),
                status=str(arguments.get("status") or "a_fazer"),
                prazo=date.fromisoformat(str(arguments["prazo"])) if arguments.get("prazo") else None,
                client_id=int(arguments["client_id"]) if arguments.get("client_id") else None,
                proposal_id=int(arguments["proposal_id"]) if arguments.get("proposal_id") else None,
                user_id=int(arguments["user_id"]) if arguments.get("user_id") else None,
            )
            task = board_service.create_task(self.db, payload, commit=False)
            action.status = "executed"
            action.task_id = task.id
            action.result_json = {"task_id": task.id}
            reply = AssistantReply(
                conversation_id=action.conversation_id,
                kind="success",
                message=f"Tarefa #{task.id} criada com sucesso no quadro.",
                action_id=action.id,
                task_id=task.id,
                task_url=f"/web/board/{task.id}/edit",
            )
            if record_message:
                self.db.add(
                    AssistantMessage(
                        conversation_id=action.conversation_id,
                        role="assistant",
                        kind="success",
                        content=reply.message,
                        details_json=reply.model_dump(mode="json"),
                    )
                )
            self.db.commit()
            return reply
        except Exception:
            self.db.rollback()
            raise

    def cancel_action(self, action_id: int, confirmation_token: str) -> AssistantReply:
        action = self.db.get(AssistantAction, action_id)
        if action is None:
            raise ValueError("Acao de confirmacao nao encontrada.")
        self._validate_confirmation_token(action, confirmation_token)
        return self._cancel_action_record(action, record_message=True)

    def _cancel_action_record(
        self,
        action: AssistantAction,
        *,
        record_message: bool,
    ) -> AssistantReply:
        if action.status == "executed":
            return self._success_reply(action)
        if action.status == "cancelled":
            return AssistantReply(
                conversation_id=action.conversation_id,
                kind="text",
                message="Esta criacao ja foi cancelada.",
                action_id=action.id,
            )

        cancelled = self.db.execute(
            update(AssistantAction)
            .where(AssistantAction.id == action.id, AssistantAction.status == "pending")
            .values(status="cancelled"),
            execution_options={"synchronize_session": False},
        )
        if cancelled.rowcount == 1:
            action.status = "cancelled"
            reply = AssistantReply(
                conversation_id=action.conversation_id,
                kind="text",
                message="Criacao cancelada. Nenhuma tarefa foi adicionada ao quadro.",
                action_id=action.id,
            )
            if record_message:
                self.db.add(
                    AssistantMessage(
                        conversation_id=action.conversation_id,
                        role="assistant",
                        kind="text",
                        content=reply.message,
                        details_json=reply.model_dump(mode="json"),
                    )
                )
            self.db.commit()
            return reply
        self.db.rollback()
        refreshed = self.db.get(AssistantAction, action.id)
        if refreshed is not None and refreshed.status == "executed":
            return self._success_reply(refreshed)
        raise ValueError("A acao ja esta sendo processada; consulte o historico antes de cancelar.")

    def get_history(self, conversation_id: int) -> list[AssistantMessageView]:
        conversation = self.db.get(AssistantConversation, conversation_id)
        if conversation is None:
            raise ValueError("Conversa nao encontrada.")
        return [
            AssistantMessageView(
                role=message.role,
                kind=message.kind,
                content=message.content,
                created_at=message.created_at.isoformat(),
                details=self._safe_reply_details(message.details_json),
            )
            for message in conversation.messages
        ]

    def _local_now(self) -> datetime:
        value = self.now()
        if value.tzinfo is None:
            return value.replace(tzinfo=self.timezone)
        return value.astimezone(self.timezone)

    def _request_now(self) -> datetime:
        return self._local_now().astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    def _claim_or_create_request(
        self,
        *,
        message: str,
        request_id: str,
        conversation_id: int | None,
    ) -> AssistantConversation | AssistantReply:
        now = self._request_now()
        lease_expires_at = now + timedelta(seconds=self.request_lease_seconds)
        request_record = (
            self.db.query(AssistantRequest)
            .filter(AssistantRequest.request_id == request_id)
            .first()
        )
        if request_record is not None:
            if conversation_id is not None and request_record.conversation_id != conversation_id:
                raise ValueError("O identificador de requisicao pertence a outra conversa.")
            user_message = self.db.get(AssistantMessage, request_record.user_message_id)
            if user_message is None or user_message.content != message:
                raise ValueError("O identificador de requisicao ja foi usado com outra mensagem.")
            if request_record.status == "completed":
                cached = self._cached_reply(request_id)
                if cached is not None:
                    return cached
                raise ValueError("A solicitacao foi concluida sem uma resposta reconciliavel.")
            if request_record.lease_expires_at > now:
                raise ValueError(
                    "Esta solicitacao ainda esta sendo processada; aguarde antes de repetir."
                )
            claimed = self.db.execute(
                update(AssistantRequest)
                .where(
                    AssistantRequest.id == request_record.id,
                    AssistantRequest.status == "processing",
                    AssistantRequest.lease_expires_at <= now,
                )
                .values(
                    lease_expires_at=lease_expires_at,
                    attempts=AssistantRequest.attempts + 1,
                ),
                execution_options={"synchronize_session": False},
            )
            if claimed.rowcount != 1:
                self.db.rollback()
                raise ValueError(
                    "Esta solicitacao ainda esta sendo processada; aguarde antes de repetir."
                )
            self.db.commit()
            conversation = self.db.get(AssistantConversation, request_record.conversation_id)
            if conversation is None:
                raise ValueError("Conversa da solicitacao nao encontrada.")
            return conversation

        existing_user_message = (
            self.db.query(AssistantMessage)
            .filter(AssistantMessage.request_id == request_id)
            .first()
        )
        if existing_user_message is not None:
            legacy_expiry = existing_user_message.created_at + timedelta(
                seconds=self.request_lease_seconds
            )
            if legacy_expiry > now:
                raise ValueError(
                    "Esta solicitacao ainda esta sendo processada; aguarde antes de repetir."
                )
            request_record = AssistantRequest(
                request_id=request_id,
                conversation_id=existing_user_message.conversation_id,
                user_message_id=existing_user_message.id,
                status="processing",
                lease_expires_at=lease_expires_at,
                attempts=2,
            )
            self.db.add(request_record)
            self.db.commit()
            conversation = self.db.get(
                AssistantConversation,
                existing_user_message.conversation_id,
            )
            if conversation is None:
                raise ValueError("Conversa da solicitacao nao encontrada.")
            return conversation

        conversation = self._get_or_build_conversation(conversation_id)
        user_message = AssistantMessage(
            conversation_id=conversation.id,
            role="user",
            kind="text",
            content=message,
            request_id=request_id,
            details_json={},
        )
        self.db.add(user_message)
        self.db.flush()
        self.db.add(
            AssistantRequest(
                request_id=request_id,
                conversation_id=conversation.id,
                user_message_id=user_message.id,
                status="processing",
                lease_expires_at=lease_expires_at,
                attempts=1,
            )
        )
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            cached = self._cached_reply(request_id)
            if cached is not None:
                return cached
            raise ValueError(
                "Esta solicitacao ainda esta sendo processada; aguarde antes de repetir."
            )
        return conversation

    def _get_or_build_conversation(self, conversation_id: int | None) -> AssistantConversation:
        if conversation_id is not None:
            conversation = self.db.get(AssistantConversation, conversation_id)
            if conversation is None:
                raise ValueError("Conversa nao encontrada.")
            return conversation
        conversation = AssistantConversation()
        self.db.add(conversation)
        self.db.flush()
        return conversation

    def _provider_messages(self, conversation_id: int) -> list[ProviderMessage]:
        rows = (
            self.db.query(AssistantMessage)
            .filter(AssistantMessage.conversation_id == conversation_id)
            .order_by(AssistantMessage.id.desc())
            .limit(self.context_messages)
            .all()
        )
        return [
            ProviderMessage(role=row.role, content=row.content)
            for row in reversed(rows)
        ]

    def _cached_reply(self, request_id: str) -> AssistantReply | None:
        message = (
            self.db.query(AssistantMessage)
            .filter(AssistantMessage.reply_to_request_id == request_id)
            .first()
        )
        if message is None:
            return None
        reply = AssistantReply.model_validate(message.details_json)
        if reply.kind != "confirmation" or reply.action_id is None:
            return reply

        action = self.db.get(AssistantAction, reply.action_id)
        if action is None:
            return reply.model_copy(update={"kind": "error", "confirmation_token": None})
        if action.status == "executed":
            return self._success_reply(action)
        if action.status == "cancelled":
            return AssistantReply(
                conversation_id=action.conversation_id,
                kind="text",
                message="Esta criacao ja foi cancelada.",
                action_id=action.id,
            )
        if action.status != "pending":
            return reply.model_copy(
                update={
                    "kind": "error",
                    "message": "A acao ja esta sendo processada. Consulte o historico em instantes.",
                    "confirmation_token": None,
                }
            )

        # Confirmation capabilities are never persisted in plaintext. A replay
        # receives a fresh token, invalidating the earlier capability.
        confirmation_token = secrets.token_urlsafe(32)
        action.confirmation_token_hash = self._token_hash(confirmation_token)
        self.db.commit()
        return reply.model_copy(update={"confirmation_token": confirmation_token})

    def _save_reply(self, request_id: str, reply: AssistantReply) -> AssistantReply:
        existing = self._cached_reply(request_id)
        if existing is not None:
            return existing
        reply_message = AssistantMessage(
            conversation_id=reply.conversation_id,
            role="assistant",
            kind=reply.kind,
            content=reply.message,
            reply_to_request_id=request_id,
            details_json=self._safe_reply_details(reply.model_dump(mode="json")),
        )
        self.db.add(reply_message)
        try:
            self.db.flush()
            request_record = (
                self.db.query(AssistantRequest)
                .filter(AssistantRequest.request_id == request_id)
                .first()
            )
            if request_record is not None:
                request_record.status = "completed"
                request_record.reply_message_id = reply_message.id
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self._cached_reply(request_id)
            if existing is not None:
                return existing
            raise
        return reply

    @staticmethod
    def _safe_reply_details(details: dict[str, object]) -> dict[str, object]:
        """Return audit-safe structured metadata without action credentials."""
        return {key: value for key, value in details.items() if key != "confirmation_token"}

    def _query_tasks(
        self,
        conversation_id: int,
        command: TaskQueryCommand,
        today: date,
    ) -> AssistantReply:
        client, client_question = self._resolve_client(command.client)
        if client_question:
            return AssistantReply(conversation_id=conversation_id, kind="clarification", message=client_question)
        user, user_question = self._resolve_user(command.responsible)
        if user_question:
            return AssistantReply(conversation_id=conversation_id, kind="clarification", message=user_question)
        try:
            due_before = resolve_date_expression(command.due_before, today=today)
        except ValueError as exc:
            return AssistantReply(conversation_id=conversation_id, kind="clarification", message=str(exc))

        tasks = board_service.query_tasks(
            self.db,
            today=today,
            status_value=command.status,
            client_id=client.id if client else None,
            user_id=user.id if user else None,
            overdue_only=command.overdue_only,
            due_before=due_before,
            priorities=command.priorities,
            include_completed=command.include_completed,
            limit=command.limit,
        )
        if not tasks:
            return AssistantReply(
                conversation_id=conversation_id,
                kind="text",
                message="Nao encontrei tarefas com esses criterios.",
            )
        lines = ["Encontrei estas tarefas:"]
        for task in tasks:
            deadline = task.prazo.strftime("%d/%m/%Y") if task.prazo else "sem prazo"
            links = []
            if task.client:
                links.append(task.client.razao_social)
            if task.user:
                links.append(task.user.nome)
            suffix = f" — {' / '.join(links)}" if links else ""
            lines.append(
                f"- #{task.id} {task.titulo} — {STATUS_LABELS.get(task.status, task.status)} — {deadline}{suffix}"
            )
        return AssistantReply(conversation_id=conversation_id, kind="text", message="\n".join(lines))

    def _confirm_latest(self, conversation_id: int) -> AssistantReply:
        action = self._latest_create_action(conversation_id)
        if action is None:
            return AssistantReply(
                conversation_id=conversation_id,
                kind="clarification",
                message="Nao ha uma criacao de tarefa nesta conversa para confirmar.",
            )
        if action.status == "cancelled":
            return AssistantReply(
                conversation_id=conversation_id,
                kind="text",
                message="Esta criacao ja foi cancelada.",
                action_id=action.id,
            )
        return self._confirm_action_record(action, record_message=False)

    def _cancel_latest(self, conversation_id: int) -> AssistantReply:
        action = self._latest_create_action(conversation_id)
        if action is None:
            return AssistantReply(
                conversation_id=conversation_id,
                kind="clarification",
                message="Nao ha uma criacao de tarefa nesta conversa para cancelar.",
            )
        if action.status == "executed":
            return AssistantReply(
                conversation_id=conversation_id,
                kind="error",
                message="A tarefa ja foi criada e nao pode ser cancelada pelo assistente.",
                action_id=action.id,
                task_id=action.task_id,
                task_url=f"/web/board/{action.task_id}/edit" if action.task_id else None,
            )
        return self._cancel_action_record(action, record_message=False)

    def _latest_create_action(self, conversation_id: int) -> AssistantAction | None:
        return (
            self.db.query(AssistantAction)
            .filter(
                AssistantAction.conversation_id == conversation_id,
                AssistantAction.action_type == "create_task",
            )
            .order_by(AssistantAction.id.desc())
            .first()
        )

    def _correct_pending_task(
        self,
        conversation_id: int,
        command: TaskDraftCorrectionCommand,
        today: date,
    ) -> AssistantReply:
        action = (
            self.db.query(AssistantAction)
            .filter(
                AssistantAction.conversation_id == conversation_id,
                AssistantAction.action_type == "create_task",
                AssistantAction.status == "pending",
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
        elif command.client is not None:
            client, question = self._resolve_client(command.client)
            if question:
                return AssistantReply(
                    conversation_id=conversation_id,
                    kind="clarification",
                    message=question,
                )
            if arguments.get("proposal_id"):
                proposal = self.db.get(Proposal, int(arguments["proposal_id"]))
                if proposal is None or proposal.client_id != client.id:
                    return AssistantReply(
                        conversation_id=conversation_id,
                        kind="clarification",
                        message="A proposta informada pertence a outro cliente. Qual vinculo devo usar?",
                    )
            arguments["client_id"] = client.id

        if command.clear_responsible:
            arguments["user_id"] = None
        elif command.responsible is not None:
            user, question = self._resolve_user(command.responsible)
            if question:
                return AssistantReply(
                    conversation_id=conversation_id,
                    kind="clarification",
                    message=question,
                )
            arguments["user_id"] = user.id

        confirmation_token = secrets.token_urlsafe(32)
        action.arguments_json = arguments
        action.confirmation_token_hash = self._token_hash(confirmation_token)
        self.db.flush()
        return self._task_confirmation_reply(action, confirmation_token)

    def _prepare_task(
        self,
        conversation_id: int,
        request_id: str,
        command: TaskCreateCommand,
        today: date,
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

        client, client_question = self._resolve_client(command.client)
        if client_question:
            self._record_clarification_action(conversation_id, request_id, command)
            return AssistantReply(conversation_id=conversation_id, kind="clarification", message=client_question)
        user, user_question = self._resolve_user(command.responsible)
        if user_question:
            self._record_clarification_action(conversation_id, request_id, command)
            return AssistantReply(conversation_id=conversation_id, kind="clarification", message=user_question)

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
                        f"A proposta {command.proposal_number} possui as revisoes {revisions}. "
                        "Informe a revisao pela tela do quadro antes de vincular pelo assistente."
                    ),
                )
            proposal = proposals[0]
            if client is None:
                client = self.db.get(Client, proposal.client_id)
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
            "proposal_id": proposal.id if proposal else None,
            "user_id": user.id if user else None,
        }
        confirmation_token = secrets.token_urlsafe(32)
        action = AssistantAction(
            conversation_id=conversation_id,
            request_id=request_id,
            confirmation_token_hash=self._token_hash(confirmation_token),
            action_type="create_task",
            status="pending",
            arguments_json=arguments,
            result_json={},
        )
        self.db.add(action)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            existing = (
                self.db.query(AssistantAction)
                .filter(AssistantAction.request_id == request_id)
                .first()
            )
            if existing is None:
                raise
            action = existing

        return self._task_confirmation_reply(action, confirmation_token)

    def _task_confirmation_reply(
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
            "cliente": client.razao_social if client else "Sem cliente",
            "responsavel": user.nome if user else "Sem responsavel",
        }
        message = (
            "Revise antes de criar: "
            f"{fields['titulo']}; status {fields['status']}; prazo {fields['prazo']}; "
            f"cliente {fields['cliente']}; responsavel {fields['responsavel']}."
        )
        return AssistantReply(
            conversation_id=action.conversation_id,
            kind="confirmation",
            message=message,
            action_id=action.id,
            confirmation_token=confirmation_token,
            fields=fields,
        )

    def _record_clarification_action(
        self,
        conversation_id: int,
        request_id: str,
        command: TaskCreateCommand,
    ) -> None:
        exists = (
            self.db.query(AssistantAction)
            .filter(AssistantAction.request_id == request_id)
            .first()
        )
        if exists is None:
            clarification_token = secrets.token_urlsafe(32)
            self.db.add(
                AssistantAction(
                    conversation_id=conversation_id,
                    request_id=request_id,
                    confirmation_token_hash=self._token_hash(clarification_token),
                    action_type="create_task",
                    status="needs_clarification",
                    arguments_json=command.model_dump(mode="json"),
                    result_json={},
                )
            )
            self.db.flush()

    def _resolve_client(self, name: str | None) -> tuple[Client | None, str | None]:
        return self._resolve_named(
            name,
            self.db.query(Client).order_by(Client.razao_social).all(),
            lambda client: client.razao_social,
            "cliente",
        )

    def _resolve_user(self, name: str | None) -> tuple[User | None, str | None]:
        return self._resolve_named(
            name,
            self.db.query(User).filter(User.ativo.is_(True)).order_by(User.nome).all(),
            lambda user: user.nome,
            "responsavel",
        )

    def _resolve_named(
        self,
        name: str | None,
        candidates: Sequence[ModelT],
        label: Callable[[ModelT], str],
        entity_name: str,
    ) -> tuple[ModelT | None, str | None]:
        if name is None or not name.strip():
            return None, None
        needle = normalize_text(name)
        exact = [candidate for candidate in candidates if normalize_text(label(candidate)) == needle]
        if len(exact) == 1:
            return exact[0], None
        matches = [candidate for candidate in candidates if needle in normalize_text(label(candidate))]
        if len(matches) == 1:
            return matches[0], None
        if not matches:
            return None, f"Nao encontrei o {entity_name} '{name}'. Qual cadastro devo usar?"
        options = ", ".join(label(candidate) for candidate in matches[:8])
        return None, f"Encontrei mais de um {entity_name}: {options}. Qual deles devo usar?"

    def _success_reply(self, action: AssistantAction) -> AssistantReply:
        if action.task_id is None:
            raise ValueError("A acao foi executada sem vinculo com a tarefa.")
        return AssistantReply(
            conversation_id=action.conversation_id,
            kind="success",
            message=f"Tarefa #{action.task_id} criada com sucesso no quadro.",
            action_id=action.id,
            task_id=action.task_id,
            task_url=f"/web/board/{action.task_id}/edit",
        )

    @staticmethod
    def _validate_confirmation_token(
        action: AssistantAction,
        confirmation_token: str,
    ) -> None:
        if not secrets.compare_digest(
            action.confirmation_token_hash,
            AssistantService._token_hash(confirmation_token),
        ):
            raise ValueError("Token de confirmacao invalido.")

    @staticmethod
    def _token_hash(confirmation_token: str) -> str:
        return hashlib.sha256(confirmation_token.encode("utf-8")).hexdigest()
