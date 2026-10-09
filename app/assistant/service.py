from __future__ import annotations

import hashlib
import logging
import re
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import TypeVar
from zoneinfo import ZoneInfo

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.assistant import evidence as _evidence
from app.assistant import day_presentation, intent_routing
from app.assistant.capabilities import CapabilityRegistry
from app.assistant.contracts import (
    AssistantMessageView,
    AssistantReply,
    CancelActionCommand,
    ConfirmActionCommand,
    ConversationCommand,
    CorrectServiceReportCommand,
    EmailQueryCommand,
    PrepareServiceReportCommand,
    ServiceDraftCorrectionCommand,
    ServiceEventDraftCommand,
    ServiceQueryCommand,
    ServiceReminderDraftCommand,
    TaskCreateCommand,
    TaskDraftCorrectionCommand,
    TaskQueryCommand,
    UnsupportedCommand,
)
from app.assistant.dates import normalize_text, resolve_date_expression
from app.assistant.email import contracts as _email_contracts
from app.assistant.email.provider import EmailReader
from app.assistant.email.query_presentation import (
    EmailQueryExecution,
    build_email_query,
    present_email_query,
)
from app.assistant.evidence import validate_conversation_claims
from app.assistant.entity_resolution import AssistantEntityResolver
from app.assistant.provider import (
    AssistantProvider,
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderInferenceTrace,
    ProviderInterpretation,
    ProviderMessage,
    ProviderModelUnavailableError,
    ProviderPendingAction,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderToolResult,
    ProviderUnavailableError,
)
from app.assistant.service_records import AssistantServiceRecordAdapter
from app.assistant.task_drafts import AssistantTaskDraftAdapter
from app.assistant.service_reports import AssistantServiceReportAdapter
from app.models import (
    AssistantAction,
    AssistantConversation,
    AssistantEmailTaskLink,
    AssistantMessage,
    AssistantRequest,
    Client,
    Task,
    User,
)
from app.schemas import ServiceTechnicalReportFields, TaskCreate
from app.services import board_service, service_report_service
from app.services.daily_brief_service import build_daily_brief
from app.services.daily_schedule_service import (
    ScheduleChangedError,
    build_daily_schedule,
    save_daily_schedule_snapshot,
)
from app.services.document_search_service import search_proposal_documents
from app.services.today_service import TASK_STATUS_LABELS, get_task_day_plan

# Preserve historical imports without restricting wildcard exports.
EmailQuery = _email_contracts.EmailQuery
references_prior_email_context = _evidence.references_prior_email_context
validate_execution_claims = _evidence.validate_execution_claims

logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", Client, User)

STATUS_LABELS = TASK_STATUS_LABELS

FOLLOW_UP_TOOLS = {
    "responder_conversa",
    "consultar_tarefas",
    "consultar_emails",
}

INITIAL_TOOLS = {
    "responder_conversa",
    "consultar_tarefas",
    "consultar_emails",
    "criar_tarefa",
    "consultar_servicos",
    "registrar_evento_servico",
    "corrigir_registro_servico",
    "criar_lembretes_servico",
    "fora_do_escopo",
    "preparar_relatorio_tecnico",
    "corrigir_previa_relatorio_tecnico",
}


@dataclass(frozen=True)
class TaskQueryExecution:
    reply: AssistantReply
    result: ProviderToolResult | None = None


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
        max_tool_rounds: int = 2,
        email_reader: EmailReader | None = None,
        capabilities: CapabilityRegistry | None = None,
        email_history_retention_days: int = 14,
        email_provider: str = "disabled",
        email_mailbox_key: str = "primary",
        email_freshness_seconds: int = 1800,
        today_lookahead_days: int = 7,
        output_dir: Path | None = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self.timezone_name = timezone
        self.timezone = ZoneInfo(timezone)
        self.now = now or (lambda: datetime.now(self.timezone))
        self.context_messages = max(2, min(context_messages, 30))
        self.request_lease_seconds = max(30, min(request_lease_seconds, 900))
        self.max_tool_rounds = max(1, min(max_tool_rounds, 3))
        self.email_reader = email_reader
        self.capabilities = capabilities or CapabilityRegistry(
            email_provider="disabled" if email_reader is None else "configured"
        )
        self.email_history_retention_days = max(1, min(email_history_retention_days, 3650))
        self.email_provider = email_provider
        self.email_mailbox_key = email_mailbox_key
        self.email_freshness_seconds = max(1, email_freshness_seconds)
        self.today_lookahead_days = max(1, min(today_lookahead_days, 31))
        if output_dir is None:
            from app.config import get_settings

            output_dir = get_settings().output_dir
        self.output_dir = output_dir
        self.entity_resolver = AssistantEntityResolver(db)
        self.service_reports = AssistantServiceReportAdapter(db, token_hash=self._token_hash)
        self.task_drafts = AssistantTaskDraftAdapter(
            db, token_hash=self._token_hash,
            resolve_task_client=self._resolve_task_client,
            resolve_user=self._resolve_user,
        )
        self.service_records = AssistantServiceRecordAdapter(
            db,
            today=lambda: self._local_now().date(),
            resolve_client=self._resolve_client,
            resolve_user=self._resolve_user,
            token_hash=self._token_hash,
        )

    def handle_message(
        self,
        *,
        message: str,
        request_id: str,
        conversation_id: int | None = None,
        retry: bool = False,
        source: str = "text",
    ) -> AssistantReply:
        clean_message = message.strip()
        clean_request_id = request_id.strip()
        if source not in {"text", "voice"}:
            raise ValueError("Origem da mensagem inválida.")
        if not clean_message:
            raise ValueError("A mensagem nao pode ficar vazia.")
        if len(clean_message) > 4000:
            raise ValueError("A mensagem deve ter no maximo 4000 caracteres.")
        if not clean_request_id or len(clean_request_id) > 100:
            raise ValueError("Identificador de requisicao invalido.")

        cached = self._cached_reply(clean_request_id)
        if cached is not None and not (retry and cached.retryable):
            return cached

        claimed_request = self._claim_or_create_request(
            message=clean_message,
            request_id=clean_request_id,
            conversation_id=conversation_id,
            retry=retry,
            source=source,
        )
        if isinstance(claimed_request, AssistantReply):
            return claimed_request
        conversation = claimed_request

        current_date = self._local_now().date()
        tool_results: list[ProviderToolResult] = []
        provider_inferences: list[ProviderInferenceTrace] = []
        executed_tools: list[str] = []
        if retry:
            tool_results.extend(self._retryable_cached_tool_results(clean_request_id))
            executed_tools.extend(result.tool for result in tool_results)
        reply: AssistantReply | None = None
        try:
            direct_control = self._direct_control_command(clean_message)
            command = direct_control
            if command is None and self._direct_document_query(clean_message):
                reply = self._execute_document_query(conversation.id, clean_message)
            if command is None and self._direct_daily_brief_request(clean_message):
                if reply is None:
                    reply = self._execute_daily_brief(conversation.id)
            if (
                command is None
                and reply is None
                and self._request_targets_email_read(clean_message)
                and self.capabilities.get("email_read").state != "available"
            ):
                command = UnsupportedCommand(
                    message=(
                        "A leitura de e-mail está implementada, mas não está configurada neste ambiente. Nenhuma caixa foi consultada."
                    )
                )
            if command is None and reply is None:
                command = self._direct_pending_client_correction(
                    conversation.id,
                    clean_message,
                )
            if command is None and reply is None:
                command = self._direct_pending_date_correction(
                    conversation.id,
                    clean_message,
                )
            if command is None and reply is None:
                command = self._direct_email_task_command(clean_message)
            if command is None and self._direct_schedule_save_request(clean_message):
                reply = self._prepare_daily_schedule_snapshot(conversation.id, clean_request_id, current_date)
            if command is None and reply is None:
                command = self._direct_task_create(conversation.id, clean_message)
            if command is None and reply is None and self._direct_service_report_request(clean_message):
                if self.provider is None:
                    raise ProviderUnavailableError("Provedor nao configurado.")
                pending_report = self._pending_service_report_action(conversation.id)
                if pending_report is not None and not self._direct_service_report_correction(clean_message):
                    reply = self._update_service_report_preview(pending_report, {})
                    command = None
                else:
                    command = self._interpret_service_report_request(
                        conversation.id,
                        clean_message,
                        current_date,
                        provider_inferences,
                    )
            if command is None and reply is None:
                direct_email_query = self._direct_email_query(clean_message)
                if direct_email_query is not None:
                    prior_result = next(
                        (item for item in tool_results if item.tool == "consultar_emails"),
                        None,
                    )
                    execution = (
                        None
                        if prior_result is not None
                        else self._execute_email_query(conversation.id, direct_email_query)
                    )
                    if execution is None:
                        if self.provider is None:
                            raise ProviderUnavailableError("Provedor nao configurado.")
                        command = self._interpret_provider(
                            self._provider_messages(conversation.id),
                            today=current_date,
                            timezone=self.timezone_name,
                            tool_results=tuple(tool_results),
                            pending_action=self._provider_pending_action(conversation.id),
                            allowed_tools={"responder_conversa"},
                            traces=provider_inferences,
                        )
                    elif execution.result is None or execution.result.state == "failed":
                        command = direct_email_query
                        reply = execution.reply
                        if execution.result is not None:
                            tool_results.append(execution.result)
                            executed_tools.append(direct_email_query.tool)
                    else:
                        if self.provider is None:
                            raise ProviderUnavailableError("Provedor nao configurado.")
                        tool_results.append(execution.result)
                        executed_tools.append(direct_email_query.tool)
                        command = self._interpret_provider(
                            self._provider_messages(conversation.id),
                            today=current_date,
                            timezone=self.timezone_name,
                            tool_results=tuple(tool_results),
                            pending_action=self._provider_pending_action(conversation.id),
                            allowed_tools={"responder_conversa"},
                            traces=provider_inferences,
                        )
            if command is None and reply is None and self._direct_board_query(clean_message):
                reply, task_result = self._execute_task_agenda(conversation.id, current_date)
                tool_results.append(task_result)
                executed_tools.append("consultar_tarefas")
            if command is None and reply is None and self._direct_service_return_query(clean_message):
                if self.provider is None:
                    raise ProviderUnavailableError("Provedor nao configurado.")
                execution = self.service_records.execute_query(
                    conversation.id,
                    ServiceQueryCommand(return_tasks_only=True, limit=50),
                )
                if execution.result is not None:
                    tool_results.append(execution.result)
                    executed_tools.append("consultar_servicos")
                command = self._interpret_provider(
                    self._provider_messages(conversation.id),
                    today=current_date,
                    timezone=self.timezone_name,
                    tool_results=tuple(tool_results),
                    pending_action=self._provider_pending_action(conversation.id),
                    allowed_tools={"responder_conversa"},
                    traces=provider_inferences,
                )
            if command is None and reply is None:
                if self.provider is None:
                    raise ProviderUnavailableError("Provedor nao configurado.")
                pending_action = self._provider_pending_action(conversation.id)
                initial_tools = set(INITIAL_TOOLS)
                if self.capabilities.get("email_read").state != "available":
                    initial_tools.discard("consultar_emails")
                if pending_action is not None:
                    initial_tools.discard("criar_tarefa")
                    if pending_action.action_type == "generate_service_report":
                        initial_tools.discard("preparar_relatorio_tecnico")
                        initial_tools.add("corrigir_previa_relatorio_tecnico")
                    elif pending_action.action_type == "register_service_event":
                        initial_tools.add("registrar_evento_servico")
                        initial_tools.add("corrigir_registro_servico")
                    elif pending_action.action_type == "correct_service_event":
                        initial_tools.add("corrigir_registro_servico")
                    elif pending_action.action_type == "create_service_reminders":
                        initial_tools.add("criar_lembretes_servico")
                    else:
                        initial_tools.add("corrigir_tarefa")
                command = self._interpret_provider(
                    self._provider_messages(conversation.id),
                    today=current_date,
                    timezone=self.timezone_name,
                    pending_action=pending_action,
                    allowed_tools=initial_tools,
                    traces=provider_inferences,
                )
                seen_queries: set[str] = set()
                last_query_reply: AssistantReply | None = None
                while isinstance(command, (TaskQueryCommand, EmailQueryCommand, ServiceQueryCommand)):
                    if isinstance(command, TaskQueryCommand):
                        command = self._ground_task_query(clean_message, command)
                    elif isinstance(command, EmailQueryCommand):
                        command = self._ground_email_query(clean_message, command)
                    query_key = command.model_dump_json()
                    if query_key in seen_queries:
                        if last_query_reply is None or not tool_results:  # pragma: no cover - defensive
                            raise ProviderResponseError("Consulta repetida sem resultado anterior.")
                        forced_reply_tools = self._follow_up_tools()
                        forced_reply_tools.discard("consultar_tarefas")
                        command = self._interpret_provider(
                            self._provider_messages(conversation.id),
                            today=current_date,
                            timezone=self.timezone_name,
                            tool_results=tuple(tool_results),
                            pending_action=self._provider_pending_action(conversation.id),
                            allowed_tools=forced_reply_tools,
                            traces=provider_inferences,
                        )
                        reply = None
                        break
                    seen_queries.add(query_key)
                    if isinstance(command, TaskQueryCommand):
                        execution = self._execute_task_query(conversation.id, command, current_date)
                    elif isinstance(command, EmailQueryCommand):
                        execution = self._execute_email_query(conversation.id, command)
                    else:
                        grounded_query = command
                        if command.client and normalize_text(command.client) not in normalize_text(clean_message):
                            grounded_query = command.model_copy(update={"client": None})
                        execution = self.service_records.execute_query(conversation.id, grounded_query)
                    last_query_reply = execution.reply
                    if execution.result is None:
                        reply = execution.reply
                        break
                    tool_results.append(execution.result)
                    executed_tools.append(command.tool)
                    if execution.result.state == "failed":
                        reply = execution.reply
                        break
                    allowed_tools = self._follow_up_tools()
                    if command.tool == "consultar_emails":
                        allowed_tools = {"responder_conversa"}
                    elif command.tool == "consultar_servicos":
                        allowed_tools = {"responder_conversa"}
                    if len(tool_results) >= self.max_tool_rounds:
                        allowed_tools.discard("consultar_tarefas")
                        allowed_tools.discard("consultar_emails")
                        allowed_tools.discard("consultar_servicos")
                    command = self._interpret_provider(
                        self._provider_messages(conversation.id),
                        today=current_date,
                        timezone=self.timezone_name,
                        tool_results=tuple(tool_results),
                        pending_action=self._provider_pending_action(conversation.id),
                        allowed_tools=allowed_tools,
                        traces=provider_inferences,
                    )
                else:
                    reply = None
            if reply is not None:
                pass
            elif direct_control is None and isinstance(command, (ConfirmActionCommand, CancelActionCommand)):
                reply = AssistantReply(
                    conversation_id=conversation.id,
                    kind="clarification",
                    message=(
                        "Nao entendi essa confirmacao com seguranca. Diga 'Pode criar' para confirmar ou 'Cancela' para cancelar."
                    ),
                )
            elif isinstance(command, TaskQueryCommand):
                # The bounded loop only leaves a query here when no provider was used.
                reply = self._execute_task_query(conversation.id, command, current_date).reply
            elif isinstance(command, EmailQueryCommand):
                reply = self._execute_email_query(conversation.id, command).reply
            elif isinstance(command, ServiceQueryCommand):
                reply = self.service_records.execute_query(conversation.id, command).reply
            elif isinstance(command, ServiceEventDraftCommand):
                executed_tools.append(command.tool)
                reply = self.service_records.prepare_event(
                    conversation.id,
                    clean_request_id,
                    command,
                    clean_message,
                )
            elif isinstance(command, ServiceDraftCorrectionCommand):
                executed_tools.append(command.tool)
                reply = self.service_records.prepare_correction(
                    conversation.id,
                    clean_request_id,
                    command,
                    clean_message,
                )
            elif isinstance(command, ServiceReminderDraftCommand):
                executed_tools.append(command.tool)
                reply = self.service_records.prepare_reminders(
                    conversation.id,
                    clean_request_id,
                    command,
                    clean_message,
                )
            elif isinstance(command, PrepareServiceReportCommand):
                executed_tools.append(command.tool)
                reply = self._prepare_service_report(conversation.id, clean_request_id, command)
            elif isinstance(command, CorrectServiceReportCommand):
                executed_tools.append(command.tool)
                reply = self._correct_pending_service_report(conversation.id, command)
            elif isinstance(command, TaskCreateCommand):
                if self._task_creation_is_forbidden(clean_message):
                    reply = AssistantReply(
                        conversation_id=conversation.id,
                        kind="error",
                        message=(
                            "Ainda nao executo esse tipo de operacao. Posso ajudar a organizar o relato ou preparar uma tarefa, se voce pedir isso explicitamente."
                        ),
                    )
                else:
                    source_item, source_question = self._resolve_task_email_source(
                        conversation.id,
                        clean_message,
                        command.source_email_reference,
                    )
                    if source_question:
                        reply = AssistantReply(
                            conversation_id=conversation.id,
                            kind="clarification",
                            message=source_question,
                        )
                        command = None
                    elif source_item is not None:
                        source_reference = str(source_item["reference"])
                        title = (command.title or "").strip()
                        if not title or normalize_text(title) in {
                            "responder",
                            "responder esse",
                            "responder email",
                        }:
                            title = f"Responder e-mail: {source_item.get('subject') or '(sem assunto)'}"
                        origin = (
                            f"E-mail {source_reference}, de {source_item.get('sender') or 'remetente desconhecido'}."
                        )
                        description = command.description.strip()
                        command = command.model_copy(
                            update={
                                "title": title,
                                "description": f"{description}\n{origin}".strip(),
                                "source_email_reference": source_reference,
                            }
                        )
                    if command is None:
                        pass
                    else:
                        executed_tools.append("criar_tarefa")
                        command = self._ground_task_creation(
                            conversation.id,
                            clean_message,
                            command,
                        )
                        reply = self._prepare_task(
                            conversation.id,
                            clean_request_id,
                            command,
                            current_date,
                        )
            elif isinstance(command, ConfirmActionCommand):
                executed_tools.append("confirmar_acao")
                reply = self._confirm_latest(conversation.id)
            elif isinstance(command, CancelActionCommand):
                executed_tools.append("cancelar_acao")
                reply = self._cancel_latest(conversation.id)
            elif isinstance(command, TaskDraftCorrectionCommand):
                executed_tools.append("corrigir_tarefa")
                reply = self._correct_pending_task(
                    conversation.id,
                    clean_request_id,
                    command,
                    current_date,
                )
            elif isinstance(command, UnsupportedCommand):
                reply = AssistantReply(
                    conversation_id=conversation.id,
                    kind="error",
                    message=command.message,
                )
            elif isinstance(command, ConversationCommand):
                if (
                    self._request_targets_unavailable_operation(clean_message)
                    and not tool_results
                    and not self._response_states_limitation(command.message)
                ):
                    reply = AssistantReply(
                        conversation_id=conversation.id,
                        kind="error",
                        message=(
                            "Essa funcao ainda nao esta disponivel. Posso ajudar a organizar o conteudo sem registrar, enviar, excluir ou alterar dados fora do quadro."
                        ),
                    )
                else:
                    reply = self._conversation_reply(
                        conversation.id,
                        command,
                        tool_results=tool_results,
                        current_message=clean_message,
                    )
            else:  # pragma: no cover - protected by the provider contract
                raise ProviderResponseError("Comando desconhecido.")
        except ProviderAuthenticationError as exc:
            reply = AssistantReply(
                conversation_id=conversation.id,
                kind="error",
                retryable=False,
                message=str(exc),
            )
        except ProviderRateLimitError as exc:
            reply = AssistantReply(
                conversation_id=conversation.id,
                kind="error",
                retryable=True,
                message=str(exc),
            )
        except ProviderModelUnavailableError as exc:
            reply = AssistantReply(
                conversation_id=conversation.id,
                kind="error",
                retryable=True,
                message=self._provider_error_message(
                    exc,
                    ollama=(
                        "O serviço Ollama está ativo, mas o modelo configurado não está instalado localmente. Confira OLLAMA_MODEL e os modelos disponíveis."
                    ),
                ),
            )
        except ProviderTimeoutError as exc:
            reply = AssistantReply(
                conversation_id=conversation.id,
                kind="error",
                retryable=True,
                message=self._provider_error_message(
                    exc,
                    ollama=(
                        "O Ollama excedeu o tempo limite desta solicitação. Nada foi alterado; você pode tentar novamente."
                    ),
                ),
            )
        except ProviderConnectionError as exc:
            reply = AssistantReply(
                conversation_id=conversation.id,
                kind="error",
                retryable=True,
                message=self._provider_error_message(
                    exc,
                    ollama=(
                        "Não foi possível alcançar o serviço Ollama local. Verifique se ele está iniciado no endereço configurado; nenhuma ação foi concluída."
                    ),
                ),
            )
        except ProviderUnavailableError as exc:
            reply = AssistantReply(
                conversation_id=conversation.id,
                kind="error",
                retryable=True,
                message=self._provider_error_message(
                    exc,
                    ollama=(
                        "O serviço Ollama local não está disponível. Nenhuma ação foi concluída; confira a configuração local."
                    ),
                ),
            )
        except ProviderResponseError as exc:
            provider_inferences.extend(trace for trace in exc.inferences if trace not in provider_inferences)
            if self._request_targets_unavailable_operation(clean_message):
                message = (
                    "Essa funcao ainda nao esta disponivel no assistente. Nada foi executado. "
                    "Posso ajudar a organizar ou redigir o conteudo sem registrar, enviar, "
                    "excluir ou alterar dados fora do quadro."
                )
            else:
                message = self._provider_error_message(
                    exc,
                    ollama=(
                        "O Ollama respondeu fora do formato esperado. Nada foi alterado; reformule a mensagem e tente novamente."
                    ),
                )
            reply = AssistantReply(
                conversation_id=conversation.id,
                kind="error",
                retryable=True,
                message=message,
            )

        return self._save_reply(
            clean_request_id,
            reply,
            tool_results=tool_results,
            provider_inferences=provider_inferences,
            executed_tools=executed_tools,
        )

    def _provider_error_message(self, exc: Exception, *, ollama: str) -> str:
        if getattr(self.provider, "display_name", "Ollama") == "Gemini":
            # Gemini adapter errors are deliberately mapped to safe, user-facing messages.
            return str(exc)
        return ollama

    def _interpret_provider(
        self,
        messages: Sequence[ProviderMessage],
        *,
        today: date,
        timezone: str,
        traces: list[ProviderInferenceTrace],
        tool_results: Sequence[ProviderToolResult] = (),
        pending_action: ProviderPendingAction | None = None,
        allowed_tools: set[str] | None = None,
    ):
        if self.provider is None:  # pragma: no cover - guarded by caller
            raise ProviderUnavailableError("Provedor nao configurado.")
        traced_interpreter = getattr(self.provider, "interpret_with_trace", None)
        if callable(traced_interpreter):
            interpretation: ProviderInterpretation = traced_interpreter(
                messages,
                today=today,
                timezone=timezone,
                tool_results=tool_results,
                pending_action=pending_action,
                allowed_tools=allowed_tools,
            )
            traces.extend(interpretation.inferences)
            command = interpretation.command
        else:
            command = self.provider.interpret(
                messages,
                today=today,
                timezone=timezone,
                tool_results=tool_results,
                pending_action=pending_action,
                allowed_tools=allowed_tools,
            )
        guarded_pending_control = pending_action is not None and isinstance(
            command, (ConfirmActionCommand, CancelActionCommand)
        )
        clarification_rewrite = (
            pending_action is not None
            and pending_action.status == "needs_clarification"
            and isinstance(command, TaskCreateCommand)
            and allowed_tools is not None
            and "corrigir_tarefa" in allowed_tools
        )
        if (
            allowed_tools is not None
            and command.tool not in allowed_tools
            and not guarded_pending_control
            and not clarification_rewrite
        ):
            raise ProviderResponseError("O provedor solicitou uma ferramenta nao permitida nesta rodada.")
        return command

    @staticmethod
    def _direct_control_command(
        message: str,
    ) -> ConfirmActionCommand | CancelActionCommand | None:
        normalized = re.sub(r"[^a-z0-9 ]+", " ", normalize_text(message))
        normalized = " ".join(normalized.split())
        if normalized in {
            "pode criar",
            "pode confirmar",
            "confirmo",
            "sim pode criar",
            "pode registrar",
            "sim pode registrar",
            "pode salvar",
        }:
            return ConfirmActionCommand()
        if normalized in {"cancela", "cancelar", "nao cancela"}:
            return CancelActionCommand()
        return None

    def _follow_up_tools(self) -> set[str]:
        tools = set(FOLLOW_UP_TOOLS)
        if self.capabilities.get("email_read").state != "available":
            tools.discard("consultar_emails")
        return tools

    _ground_task_query = staticmethod(intent_routing.ground_task_query)

    _ground_email_query = staticmethod(intent_routing.ground_email_query)

    _direct_email_query = staticmethod(intent_routing.direct_email_query)

    _direct_document_query = staticmethod(intent_routing.direct_document_query)

    def _execute_document_query(self, conversation_id: int, query: str) -> AssistantReply:
        result = search_proposal_documents(
            self.db,
            output_dir=self.output_dir,
            query=query,
        )
        items = [evidence.as_dict() for evidence in result.evidence]
        if items:
            lines = ["Encontrei estes trechos nos documentos registrados:"]
            for item in items:
                source = str(item["document_name"])
                if item.get("page") is not None:
                    source += f", página {item['page']}"
                else:
                    source += f", seção {item.get('section') or 'não identificada'}"
                lines.append(f"• “{item['excerpt']}”\n  Fonte: {source}.")
            message = "\n\n".join(lines)
            if result.partial_documents:
                message += (
                    f"\n\nA busca é parcial: {result.partial_documents} arquivo(s) foram indexados parcialmente; "
                    "a ausência de outras informações não está confirmada."
                )
            if result.unreadable_documents:
                message += (
                    f"\n\n{result.unreadable_documents} arquivo(s) registrado(s) não puderam ser consultados; "
                    "a ausência de outras informações não está confirmada."
                )
            if result.ocr_unavailable_documents:
                message += self._document_ocr_limitation(result)
            spoken_message = f"Encontrei {len(items)} trecho(s) com referência de documento. "
            spoken_message += " ".join(
                f"{item['excerpt']} Fonte: {item['document_name']}, "
                f"{'página ' + str(item['page']) if item.get('page') is not None else 'seção ' + str(item.get('section') or 'não identificada')}."
                for item in items[:2]
            )
        elif result.registered_documents == 0:
            message = "Não encontrei documentos importados e registrados para consulta nesta aplicação."
            spoken_message = "Não encontrei documentos registrados para consulta."
        elif result.readable_documents == 0 and result.unreadable_documents:
            message = (
                "Não consegui consultar os arquivos registrados. "
                "Não posso confirmar se a informação solicitada existe nos documentos."
            )
            if result.ocr_unavailable_documents:
                message += self._document_ocr_limitation(result)
            spoken_message = "Não consegui consultar os arquivos registrados; não posso confirmar essa informação."
        else:
            message = "Não encontrei evidência suficiente nos documentos consultáveis para responder."
            if result.unreadable_documents:
                message += (
                    f" A busca é parcial: {result.unreadable_documents} arquivo(s) registrado(s) "
                    "não puderam ser consultados; a ausência não está confirmada."
                )
            if result.partial_documents:
                message += (
                    f" {result.partial_documents} arquivo(s) foram indexados parcialmente; "
                    "a ausência de outras informações não está confirmada."
                )
            if result.ocr_unavailable_documents:
                message += self._document_ocr_limitation(result)
            spoken_message = "Não encontrei evidência suficiente nos documentos consultáveis para responder."
        if result.unreadable_documents or result.partial_documents:
            spoken_message += " A busca foi parcial, então não posso confirmar ausência de outras informações."
        return AssistantReply(
            conversation_id=conversation_id,
            kind="text",
            message=message,
            spoken_message=spoken_message,
            document_items=items,
            limitations=(
                (
                    ["A busca foi parcial porque há arquivos registrados que não puderam ser consultados."]
                    + (["OCR local indisponível para alguns PDFs sem camada de texto."] if result.ocr_unavailable_documents else [])
                )
                if result.unreadable_documents or result.partial_documents else []
            ),
        )

    @staticmethod
    def _document_ocr_limitation(result) -> str:
        note = (
            f" OCR local não está disponível para {result.ocr_unavailable_documents} PDF(s) "
            "sem texto pesquisável."
        )
        if result.ocr_unavailable_reasons:
            note += " Motivo identificado: " + "; ".join(result.ocr_unavailable_reasons) + "."
        return note

    _direct_board_query = staticmethod(intent_routing.direct_board_query)

    _direct_daily_brief_request = staticmethod(intent_routing.direct_daily_brief_request)

    def _execute_daily_brief(self, conversation_id: int) -> AssistantReply:
        brief = build_daily_brief(
            self.db,
            now=self._local_now(),
            timezone=self.timezone_name,
            email_provider=self.email_provider,
            email_mailbox_key=self.email_mailbox_key,
            email_freshness_seconds=self.email_freshness_seconds,
            lookahead_days=self.today_lookahead_days,
        )
        return day_presentation.present_daily_brief(conversation_id, brief)

    _direct_service_return_query = staticmethod(intent_routing.direct_service_return_query)

    _direct_service_report_request = staticmethod(intent_routing.direct_service_report_request)

    _direct_service_report_correction = staticmethod(intent_routing.direct_service_report_correction)

    def _interpret_service_report_request(
        self,
        conversation_id: int,
        message: str,
        today: date,
        traces: list[ProviderInferenceTrace],
    ):
        pending_report = self._pending_service_report_action(conversation_id)
        allowed_tool = (
            "corrigir_previa_relatorio_tecnico"
            if pending_report is not None and self._direct_service_report_correction(message)
            else "preparar_relatorio_tecnico"
        )
        return self._interpret_provider(
            self._provider_messages(conversation_id),
            today=today,
            timezone=self.timezone_name,
            pending_action=self._provider_pending_action(conversation_id),
            allowed_tools={allowed_tool},
            traces=traces,
        )

    def _execute_task_agenda(
        self,
        conversation_id: int,
        today: date,
    ) -> tuple[AssistantReply, ProviderToolResult]:
        plan = get_task_day_plan(self.db, today=today)
        schedule = build_daily_schedule(
            self.db,
            today=today,
            now=self._local_now(),
            timezone=self.timezone_name,
            task_plan=plan,
        )
        message = day_presentation.task_agenda_message(plan, schedule, today)

        duration_by_task = {
            task.id: task.estimated_duration_minutes
            for task in self.db.query(Task).filter(Task.id.in_([item.task_id for item in plan.items])).all()
        }
        result = day_presentation.task_agenda_result(plan, schedule, today, duration_by_task)
        return AssistantReply(conversation_id=conversation_id, kind="text", message=message), result

    _direct_schedule_save_request = staticmethod(intent_routing.direct_schedule_save_request)

    def _prepare_daily_schedule_snapshot(
        self,
        conversation_id: int,
        request_id: str,
        today: date,
    ) -> AssistantReply:
        pending = (
            self.db.query(AssistantAction)
            .filter(
                AssistantAction.conversation_id == conversation_id,
                AssistantAction.action_type == "save_daily_schedule",
                AssistantAction.status.in_(("pending", "needs_clarification")),
            )
            .order_by(AssistantAction.id.desc())
            .first()
        )
        if pending is not None:
            return AssistantReply(
                conversation_id=conversation_id,
                kind="clarification",
                message=(
                    "Já existe uma prévia de agenda aguardando confirmação ou cancelamento. Resolva essa prévia antes de gerar outra; nenhum snapshot foi salvo."
                ),
                action_id=pending.id,
            )
        schedule = build_daily_schedule(
            self.db,
            today=today,
            now=self._local_now(),
            timezone=self.timezone_name,
        )
        token = secrets.token_urlsafe(32)
        action = AssistantAction(
            conversation_id=conversation_id,
            request_id=request_id,
            confirmation_token_hash=self._token_hash(token),
            action_type="save_daily_schedule",
            status="pending",
            arguments_json={
                "date": today.isoformat(),
                "snapshot": schedule.snapshot(),
                "expected_previous_snapshot_id": (schedule.prior_snapshot.id if schedule.prior_snapshot else None),
            },
            result_json={},
        )
        self.db.add(action)
        self.db.flush()
        replacing = schedule.prior_snapshot is not None
        message = f"Confirme para salvar o snapshot da agenda de {today:%d/%m/%Y}. "
        if replacing:
            message += f"Será criada a versão {schedule.prior_snapshot.version + 1}; a versão anterior continuará no histórico. "
        else:
            message += "Esta será a primeira versão salva. "
        message += "Nada será salvo até a confirmação e as tarefas não serão alteradas."
        return AssistantReply(
            conversation_id=conversation_id,
            kind="confirmation",
            message=message,
            action_id=action.id,
            confirmation_token=token,
            fields={
                "data": today.strftime("%d/%m/%Y"),
                "blocos": str(len(schedule.blocks)),
                "tarefas_nao_alocadas": str(len(schedule.unscheduled)),
                "substitui": str(schedule.prior_snapshot.version) if replacing else "não",
            },
        )

    def _direct_pending_date_correction(
        self,
        conversation_id: int,
        message: str,
    ) -> TaskDraftCorrectionCommand | None:
        action = self._latest_create_action(conversation_id)
        if action is None or action.action_type != "create_task" or action.status != "pending":
            return None
        normalized = normalize_text(message)
        correction_cues = ("na verdade", "prazo", "data", "vence", "vencimento")
        if not any(cue in normalized for cue in correction_cues):
            return None
        if "sem prazo" in normalized:
            return TaskDraftCorrectionCommand(clear_due_date=True)
        relative_dates = (
            "depois de amanha",
            "fim da semana",
            "esta semana",
            "nesta semana",
            "amanha",
            "hoje",
            "segunda",
            "terca",
            "quarta",
            "quinta",
            "sexta",
            "sabado",
            "domingo",
        )
        due_date = next((term for term in relative_dates if term in normalized), None)
        if due_date is None:
            match = re.search(
                r"\b(?:daqui a|em)\s+\d{1,3}\s+dias?\b|"
                r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|"
                r"\b\d{4}-\d{2}-\d{2}\b",
                normalized,
            )
            due_date = match.group(0) if match else None
        if due_date is None:
            return None
        updates: dict[str, object] = {"due_date": due_date}
        client_match = re.search(
            r"\b(?:use|usar|vincule|vincular)\s+(?:a\s+)?(?:empresa|cliente)?\s*"
            r"(.+?)(?=\s+(?:e|mas|na verdade|prazo)\b|[,;.!?]|$)",
            message.strip(),
            re.IGNORECASE,
        )
        if client_match:
            client_name = client_match.group(1).strip()[:255]
            if client_name:
                updates["client"] = client_name
        return TaskDraftCorrectionCommand(**updates)

    def _direct_pending_client_correction(
        self, conversation_id: int, message: str
    ) -> TaskDraftCorrectionCommand | None:
        action = self._latest_create_action(conversation_id)
        if action is None or action.status not in {"pending", "needs_clarification"}:
            return None
        normalized = normalize_text(message).strip(" .,!?:;")
        explicit_register = re.search(
            r"\b(?:cadastre|cadastra|cadastrar|registre|registra)\s+"
            r"(?:a\s+)?(?:empresa|cliente)\s+(.+?)\s*[.!?]*$",
            message.strip(),
            re.IGNORECASE,
        )
        explicit_use = re.search(
            r"\b(?:use|usar|vincule|vincular)\s+(?:a\s+)?(?:empresa|cliente)\s+(.+?)\s*[.!?]*$",
            message.strip(),
            re.IGNORECASE,
        )
        match = explicit_register or explicit_use
        if match:
            company = match.group(1).strip(" \t.,!?\"'")[:255]
            if company:
                return TaskDraftCorrectionCommand(client=company)
        if (
            action.status == "pending"
            and action.arguments_json.get("client_link_status")
            in {
                "pending_review",
                "needs_confirmation",
            }
            and len(normalized.split()) == 1
            and normalized
            not in {
                "sim",
                "nao",
                "confirmo",
                "cancela",
                "cancelar",
                "cria",
                "criar",
            }
        ):
            return TaskDraftCorrectionCommand(client=message.strip()[:255])
        if action.status != "needs_clarification":
            return None
        raw_draft = action.arguments_json
        if "client" not in raw_draft or len(normalized.split()) > 5:
            return None
        last_question = (
            self.db.query(AssistantMessage)
            .filter(
                AssistantMessage.conversation_id == conversation_id,
                AssistantMessage.role == "assistant",
                AssistantMessage.kind == "clarification",
            )
            .order_by(AssistantMessage.id.desc())
            .first()
        )
        if last_question is None or "cliente" not in normalize_text(last_question.content):
            return None
        if normalized in {"o que voce recomenda", "qual voce recomenda", "nao sei"}:
            original_client = raw_draft.get("client")
            if original_client:
                return TaskDraftCorrectionCommand(client=str(original_client)[:255])
            return None
        return TaskDraftCorrectionCommand(client=message.strip()[:255])

    @staticmethod
    def _direct_email_task_command(message: str) -> TaskCreateCommand | None:
        normalized = normalize_text(message)
        explicit_creation = bool(
            re.search(
                r"\b(?:crie|cria|criar|prepare)\b.{0,40}\b(?:tarefa|lembrete)\b",
                normalized,
            )
            or re.search(r"\b(?:tarefa|lembrete)\b.{0,40}\b(?:responder|resposta)\b", normalized)
        )
        email_reference = bool(
            re.search(
                r"\b(?:responder|resposta)\b.{0,60}\b(?:e[- ]?mail|esse|este|primeiro|segundo|terceiro)\b",
                normalized,
            )
        )
        if explicit_creation and email_reference:
            return TaskCreateCommand(title="Responder")
        return None

    def _direct_task_create(self, conversation_id: int, message: str) -> TaskCreateCommand | None:
        """Route explicit task-creation syntax deterministically before model interpretation."""
        normalized_message = normalize_text(message)
        if re.search(r"\b(?:chamado|servico)\s*(?:#|n[ºo.]?\s*)\d+", normalized_message):
            return None
        pending = self._latest_create_action(conversation_id)
        if pending is not None and pending.status in {"pending", "needs_clarification"}:
            return None
        match = re.search(
            r"\b(?:crie|cria|criar|adicione|adicionar|coloque|colocar|prepare|prepara)\s+"
            r"(?:uma?\s+)?(?:tarefa|lembrete)\s+(?:(?:para|de)\s+)?(.+)$",
            message.strip(),
            re.IGNORECASE,
        )
        if match is None:
            return None
        remainder = match.group(1).strip()
        due_date = None
        due_match = re.search(
            r"\bsem\s+prazo\b|\b(?:prazo\s+(?:para|em)\s+|(?:para|ate|até|na|no)\s+)?"
            r"(depois\s+de\s+amanha|amanha|hoje|segunda(?:-feira)?|terca(?:-feira)?|"
            r"quarta(?:-feira)?|quinta(?:-feira)?|sexta(?:-feira)?|sabado|domingo|"
            r"\d{1,2}/\d{1,2}(?:/\d{2,4})?|\d{4}-\d{2}-\d{2})\s*[.!?]*$",
            remainder,
            re.IGNORECASE,
        )
        if due_match:
            whole = due_match.group(0).strip(" ,.!?")
            if normalize_text(whole) != "sem prazo":
                due_date = due_match.group(1).strip()
            remainder = remainder[: due_match.start()]

        client_name = None
        client_clause = re.search(
            r"(?P<clause>(?:\s+(?:da|do|de|para)\s+)?(?:empresa|cliente)\s+"
            r"(?P<name>[A-ZÀ-ÿ0-9][A-ZÀ-ÿa-z0-9.&'-]*(?:\s+[A-ZÀ-ÿ0-9][A-ZÀ-ÿa-z0-9.&'-]*){0,3}))"
            r"(?=\s+(?:sem prazo|para|ate|até|na|no|prazo)\b|[,;.!?]|$)",
            remainder,
            re.IGNORECASE,
        )
        if client_clause is None:
            client_clause = re.search(
                r"(?P<clause>\s+(?:da|do|de|para)\s+(?:a\s+)?"
                r"(?P<name>[A-ZÀ-Ý][A-ZÀ-Ýa-z0-9.&'-]*(?:\s+[A-ZÀ-Ý][A-ZÀ-Ýa-z0-9.&'-]*){0,2}))\s*$",
                remainder,
            )
        if client_clause:
            candidate_name = client_clause.group("name").strip()
            if normalize_text(candidate_name) not in {
                "hoje",
                "amanha",
                "depois de amanha",
                "segunda",
                "terca",
                "quarta",
                "quinta",
                "sexta",
                "sabado",
                "domingo",
            }:
                client_name = candidate_name[:255]
                remainder = remainder[: client_clause.start()] + remainder[client_clause.end() :]

        title = remainder.strip(" ,;.!?:\t")
        title = re.sub(r"^(?:para|de)\s+", "", title, flags=re.IGNORECASE).strip()
        if not title:
            return None
        if normalize_text(title) in {
            "tarefa",
            "lembrete",
            "urgente",
            "algo",
            "alguma coisa",
        }:
            return None
        return TaskCreateCommand(title=title[:255], client=client_name, due_date=due_date)

    def _prepare_service_report(self, conversation_id: int, request_id: str, command: PrepareServiceReportCommand) -> AssistantReply:
        return self.service_reports.prepare(conversation_id, request_id, command)

    def _correct_pending_service_report(self, conversation_id: int, command: CorrectServiceReportCommand) -> AssistantReply:
        return self.service_reports.correct(conversation_id, command)

    def edit_service_report_preview(
        self,
        action_id: int,
        confirmation_token: str,
        fields: dict[str, str],
    ) -> AssistantReply:
        action = self.db.get(AssistantAction, action_id)
        if action is None or action.action_type != "generate_service_report":
            raise ValueError("Prévia de relatório técnico não encontrada.")
        self._validate_confirmation_token(action, confirmation_token)
        if action.status != "pending":
            raise ValueError("A prévia não está mais pendente de confirmação.")
        allowed_fields = set(service_report_service.FIELD_LABELS)
        if set(fields) != allowed_fields or any(not isinstance(value, str) for value in fields.values()):
            raise ValueError("Os campos enviados não correspondem à prévia do relatório.")
        reply = self._update_service_report_preview(action, fields)
        if reply.kind == "confirmation":
            self.db.add(
                AssistantMessage(
                    conversation_id=action.conversation_id,
                    role="assistant",
                    kind="confirmation",
                    content=reply.message,
                    details_json=self._safe_reply_details(reply.model_dump(mode="json")),
                )
            )
            self.db.commit()
        return reply

    def _pending_service_report_action(self, conversation_id: int) -> AssistantAction | None:
        return self.service_reports.pending_action(conversation_id)

    def _update_service_report_preview(self, action: AssistantAction, updates: dict[str, object]) -> AssistantReply:
        return self.service_reports.update_preview(action, updates)

    _report_preview_message = staticmethod(AssistantServiceReportAdapter.preview_message)
    _service_report_preview_reply = staticmethod(AssistantServiceReportAdapter.preview_reply)

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
        action.status = "executing"

        arguments = action.arguments_json
        try:
            if action.action_type in {
                "register_service_event",
                "correct_service_event",
                "create_service_reminders",
            }:
                reply = self.service_records.confirm(action)
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
            if action.action_type == "generate_service_report":
                fields = ServiceTechnicalReportFields.model_validate(action.arguments_json["fields_json"])
                service_report_service.generate_report(
                    self.db,
                    int(action.arguments_json["service_call_id"]),
                    fields,
                    idempotency_key=str(action.arguments_json["report_idempotency_key"]),
                    settings=service_report_service.assistant_generation_settings(),
                    confirmed=True,
                    expected_fingerprint=str(action.arguments_json["source_fingerprint"]),
                    assistant_action=action,
                )
                reply = self._success_reply(action)
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
            if action.action_type == "save_daily_schedule":
                try:
                    snapshot = save_daily_schedule_snapshot(
                        self.db,
                        schedule_date=date.fromisoformat(str(arguments["date"])),
                        snapshot=dict(arguments["snapshot"]),
                        assistant_action_id=action.id,
                        idempotency_key=f"assistant-action:{action.id}",
                        expected_previous_snapshot_id=(
                            int(arguments["expected_previous_snapshot_id"])
                            if arguments.get("expected_previous_snapshot_id") is not None
                            else None
                        ),
                    )
                except ScheduleChangedError as exc:
                    self.db.rollback()
                    stale_action = self.db.get(AssistantAction, action.id)
                    if stale_action is not None:
                        stale_action.status = "needs_clarification"
                        stale_action.result_json = {"error": "schedule_changed"}
                        self.db.commit()
                    return AssistantReply(
                        conversation_id=action.conversation_id,
                        kind="clarification",
                        message=f"{exc} Nenhum snapshot foi salvo.",
                        action_id=action.id,
                    )
                action.status = "executed"
                action.result_json = {
                    "snapshot_id": snapshot.id,
                    "schedule_date": snapshot.schedule_date.isoformat(),
                    "version": snapshot.version,
                }
                reply = AssistantReply(
                    conversation_id=action.conversation_id,
                    kind="success",
                    message=(
                        f"Snapshot da agenda de {snapshot.schedule_date:%d/%m/%Y} salvo como versão {snapshot.version}. As tarefas não foram alteradas."
                    ),
                    action_id=action.id,
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
            payload = TaskCreate(
                titulo=str(arguments["titulo"]),
                descricao=str(arguments.get("descricao") or ""),
                status=str(arguments.get("status") or "a_fazer"),
                prazo=date.fromisoformat(str(arguments["prazo"])) if arguments.get("prazo") else None,
                client_id=int(arguments["client_id"]) if arguments.get("client_id") else None,
                client_name=(str(arguments["client_name"]) if arguments.get("client_name") else None),
                client_link_status=str(arguments.get("client_link_status") or "unlinked"),
                proposal_id=int(arguments["proposal_id"]) if arguments.get("proposal_id") else None,
                user_id=int(arguments["user_id"]) if arguments.get("user_id") else None,
                estimated_duration_minutes=(
                    int(arguments["estimated_duration_minutes"])
                    if arguments.get("estimated_duration_minutes")
                    else None
                ),
            )
            task = board_service.create_task(self.db, payload, commit=False)
            source_email_reference = arguments.get("source_email_reference")
            if source_email_reference:
                self.db.add(
                    AssistantEmailTaskLink(
                        conversation_id=action.conversation_id,
                        task_id=task.id,
                        email_reference=str(source_email_reference),
                    )
                )
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
                message="Esta acao ja foi cancelada.",
                action_id=action.id,
            )

        cancelled = self.db.execute(
            update(AssistantAction)
            .where(
                AssistantAction.id == action.id,
                AssistantAction.status.in_(("pending", "needs_clarification")),
            )
            .values(status="cancelled"),
            execution_options={"synchronize_session": False},
        )
        if cancelled.rowcount == 1:
            action.status = "cancelled"
            if action.action_type in {
                "register_service_event",
                "correct_service_event",
            }:
                cancellation_message = "Registro cancelado. Nenhum evento ou correção foi salvo."
            elif action.action_type == "create_service_reminders":
                cancellation_message = "Lembretes cancelados. Nenhuma tarefa foi adicionada ao quadro."
            elif action.action_type == "save_daily_schedule":
                cancellation_message = "Salvamento da agenda cancelado. Nenhum snapshot foi gravado."
            elif action.action_type == "generate_service_report":
                cancellation_message = "Prévia do relatório cancelada. Nenhum DOCX ou PDF foi gerado."
            else:
                cancellation_message = "Criacao cancelada. Nenhuma tarefa foi adicionada ao quadro."
            reply = AssistantReply(
                conversation_id=action.conversation_id,
                kind="text",
                message=cancellation_message,
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
        if self._prune_expired_email_details():
            self.db.commit()
            self.db.refresh(conversation)
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
        retry: bool = False,
        source: str = "text",
    ) -> AssistantConversation | AssistantReply:
        now = self._request_now()
        lease_expires_at = now + timedelta(seconds=self.request_lease_seconds)
        request_record = self.db.query(AssistantRequest).filter(AssistantRequest.request_id == request_id).first()
        if request_record is not None:
            if conversation_id is not None and request_record.conversation_id != conversation_id:
                raise ValueError("O identificador de requisicao pertence a outra conversa.")
            user_message = self.db.get(AssistantMessage, request_record.user_message_id)
            if user_message is None or user_message.content != message:
                raise ValueError("O identificador de requisicao ja foi usado com outra mensagem.")
            if request_record.status == "completed":
                cached = self._cached_reply(request_id)
                if cached is not None:
                    if retry and cached.retryable:
                        claimed = self.db.execute(
                            update(AssistantRequest)
                            .where(
                                AssistantRequest.id == request_record.id,
                                AssistantRequest.status == "completed",
                            )
                            .values(
                                status="processing",
                                lease_expires_at=lease_expires_at,
                                attempts=AssistantRequest.attempts + 1,
                            ),
                            execution_options={"synchronize_session": False},
                        )
                        if claimed.rowcount != 1:
                            self.db.rollback()
                            raise ValueError("Esta solicitacao ainda esta sendo processada; aguarde.")
                        self.db.commit()
                        request_record.status = "processing"
                        request_record.lease_expires_at = lease_expires_at
                        request_record.attempts += 1
                        conversation = self.db.get(AssistantConversation, request_record.conversation_id)
                        if conversation is None:
                            raise ValueError("Conversa da solicitacao nao encontrada.")
                        return conversation
                    return cached
                raise ValueError("A solicitacao foi concluida sem uma resposta reconciliavel.")
            if request_record.lease_expires_at > now:
                raise ValueError("Esta solicitacao ainda esta sendo processada; aguarde antes de repetir.")
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
                raise ValueError("Esta solicitacao ainda esta sendo processada; aguarde antes de repetir.")
            self.db.commit()
            conversation = self.db.get(AssistantConversation, request_record.conversation_id)
            if conversation is None:
                raise ValueError("Conversa da solicitacao nao encontrada.")
            return conversation

        existing_user_message = (
            self.db.query(AssistantMessage).filter(AssistantMessage.request_id == request_id).first()
        )
        if existing_user_message is not None:
            legacy_expiry = existing_user_message.created_at + timedelta(seconds=self.request_lease_seconds)
            if legacy_expiry > now:
                raise ValueError("Esta solicitacao ainda esta sendo processada; aguarde antes de repetir.")
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
            details_json={"source": source},
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
            raise ValueError("Esta solicitacao ainda esta sendo processada; aguarde antes de repetir.")
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
        self._prune_expired_email_details()
        rows = (
            self.db.query(AssistantMessage)
            .filter(AssistantMessage.conversation_id == conversation_id)
            .order_by(AssistantMessage.id.desc())
            .limit(self.context_messages)
            .all()
        )
        messages: list[ProviderMessage] = []
        for row in reversed(rows):
            content = row.content
            raw_items = row.details_json.get("email_items", [])
            if row.role == "assistant" and isinstance(raw_items, list) and raw_items:
                presented = []
                for position, item in enumerate(raw_items[:5], start=1):
                    if not isinstance(item, dict):
                        continue
                    presented.append(
                        {
                            "position": position,
                            "reference": item.get("reference"),
                            "sender": item.get("sender"),
                            "subject": item.get("subject"),
                            "priority": item.get("priority"),
                            "reason": item.get("priority_reason"),
                            "summary": str(item.get("summary") or "")[:280],
                            "seen": item.get("seen"),
                            "action_suggested": item.get("action_suggested"),
                        }
                    )
                content += "\nMensagens exibidas nesta resposta: " + repr(presented)
            report_candidates = row.details_json.get("report_candidates", [])
            if row.role == "assistant" and isinstance(report_candidates, list) and report_candidates:
                presented_calls = [
                    {
                        "id": item.get("id"),
                        "client": item.get("client"),
                        "summary": item.get("summary"),
                        "opened_on": item.get("opened_on"),
                    }
                    for item in report_candidates
                    if isinstance(item, dict)
                ]
                content += "\nChamados concluídos apresentados para escolha: " + repr(presented_calls)
            messages.append(ProviderMessage(role=row.role, content=content))
        return messages

    def _prune_expired_email_details(self) -> bool:
        cutoff = self._request_now() - timedelta(days=self.email_history_retention_days)
        changed = False
        rows = self.db.query(AssistantMessage).filter(AssistantMessage.created_at < cutoff).all()
        for row in rows:
            details = dict(row.details_json)
            if "email_items" not in details and "tool_results" not in details:
                continue
            details.pop("email_items", None)
            raw_results = details.get("tool_results", [])
            if isinstance(raw_results, list):
                sanitized = []
                for result in raw_results:
                    if not isinstance(result, dict) or result.get("tool") != "consultar_emails":
                        sanitized.append(result)
                        continue
                    safe_result = dict(result)
                    payload = dict(safe_result.get("payload") or {})
                    payload.pop("messages", None)
                    safe_result["payload"] = payload
                    sanitized.append(safe_result)
                details["tool_results"] = sanitized
            row.details_json = details
            changed = True
        if changed:
            self.db.flush()
        return changed

    def _provider_pending_action(self, conversation_id: int) -> ProviderPendingAction | None:
        action = (
            self.db.query(AssistantAction)
            .filter(
                AssistantAction.conversation_id == conversation_id,
                AssistantAction.action_type.in_(
                    (
                        "create_task",
                        "register_service_event",
                        "correct_service_event",
                        "create_service_reminders",
                        "save_daily_schedule",
                        "generate_service_report",
                    )
                ),
                AssistantAction.status.in_(("pending", "needs_clarification")),
            )
            .order_by(AssistantAction.id.desc())
            .first()
        )
        if action is None:
            return None
        return ProviderPendingAction(
            action_type=action.action_type,
            status=action.status,
            arguments=dict(action.arguments_json),
        )

    def _cached_reply(self, request_id: str) -> AssistantReply | None:
        message = self.db.query(AssistantMessage).filter(AssistantMessage.reply_to_request_id == request_id).first()
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

    def _retryable_cached_tool_results(self, request_id: str) -> list[ProviderToolResult]:
        message = self.db.query(AssistantMessage).filter(AssistantMessage.reply_to_request_id == request_id).first()
        raw_results = message.details_json.get("tool_results", []) if message else []
        if not isinstance(raw_results, list):
            return []
        recovered: list[ProviderToolResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            try:
                result = ProviderToolResult.model_validate(item)
            except Exception:
                continue
            # Retry may reuse successful read evidence, never a write operation.
            if result.state in {"success", "empty", "partial", "stale"}:
                recovered.append(result)
        return recovered

    def _save_reply(
        self,
        request_id: str,
        reply: AssistantReply,
        *,
        tool_results: Sequence[ProviderToolResult] = (),
        provider_inferences: Sequence[ProviderInferenceTrace] = (),
        executed_tools: Sequence[str] = (),
    ) -> AssistantReply:
        existing_message = (
            self.db.query(AssistantMessage).filter(AssistantMessage.reply_to_request_id == request_id).first()
        )
        request_record = self.db.query(AssistantRequest).filter(AssistantRequest.request_id == request_id).first()
        if existing_message is not None:
            previous_reply = AssistantReply.model_validate(existing_message.details_json)
            retry_in_progress = (
                request_record is not None and request_record.status == "processing" and previous_reply.retryable
            )
            if not retry_in_progress:
                existing = self._cached_reply(request_id)
                if existing is not None:
                    return existing
        details = self._safe_reply_details(reply.model_dump(mode="json"))
        if tool_results:
            details["tool_results"] = [result.model_dump(mode="json") for result in tool_results]
            service_result = next(
                (result for result in reversed(tool_results) if result.tool == "consultar_servicos"),
                None,
            )
            if service_result is not None:
                details["service_calls"] = service_result.payload.get("service_calls", [])
        if provider_inferences:
            details["provider_inferences"] = [trace.model_dump(mode="json") for trace in provider_inferences]
        if executed_tools:
            details["executed_tools"] = list(executed_tools)
        if existing_message is not None:
            reply_message = existing_message
            reply_message.kind = reply.kind
            reply_message.content = reply.message
            reply_message.details_json = details
        else:
            reply_message = AssistantMessage(
                conversation_id=reply.conversation_id,
                role="assistant",
                kind=reply.kind,
                content=reply.message,
                reply_to_request_id=request_id,
                details_json=details,
            )
            self.db.add(reply_message)
        try:
            self.db.flush()
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

    def _execute_task_query(
        self,
        conversation_id: int,
        command: TaskQueryCommand,
        today: date,
    ) -> TaskQueryExecution:
        client, client_question = self._resolve_client(command.client)
        if client_question:
            return TaskQueryExecution(
                AssistantReply(
                    conversation_id=conversation_id,
                    kind="clarification",
                    message=client_question,
                )
            )
        user, user_question = self._resolve_user(command.responsible)
        if user_question:
            return TaskQueryExecution(
                AssistantReply(
                    conversation_id=conversation_id,
                    kind="clarification",
                    message=user_question,
                )
            )
        try:
            due_before = resolve_date_expression(command.due_before, today=today)
        except ValueError as exc:
            return TaskQueryExecution(
                AssistantReply(
                    conversation_id=conversation_id,
                    kind="clarification",
                    message=str(exc),
                )
            )

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
            reply = AssistantReply(
                conversation_id=conversation_id,
                kind="text",
                message=(
                    "Não há tarefas cadastradas com esses critérios. Se quiser, posso ajudar a criar uma nova tarefa."
                ),
            )
            return TaskQueryExecution(
                reply,
                ProviderToolResult(
                    tool="consultar_tarefas",
                    payload={
                        "criteria": command.model_dump(mode="json"),
                        "tasks": [],
                    },
                ),
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
        reply = AssistantReply(conversation_id=conversation_id, kind="text", message="\n".join(lines))
        result_tasks = [
            {
                "id": task.id,
                "title": task.titulo,
                "status": STATUS_LABELS.get(task.status, task.status),
                "due_date": task.prazo.strftime("%d/%m/%Y") if task.prazo else None,
                "client": task.client.razao_social if task.client else None,
                "responsible": task.user.nome if task.user else None,
                "is_overdue": bool(task.prazo and task.prazo < today),
                "days_from_today": (task.prazo - today).days if task.prazo else None,
                "due_relation": self._task_due_relation(task.prazo, today),
                "priority_position": position,
            }
            for position, task in enumerate(tasks, start=1)
        ]
        return TaskQueryExecution(
            reply,
            ProviderToolResult(
                tool="consultar_tarefas",
                payload={
                    "criteria": command.model_dump(mode="json"),
                    "tasks": result_tasks,
                },
            ),
        )

    def _execute_email_query(
        self,
        conversation_id: int,
        command: EmailQueryCommand,
    ) -> EmailQueryExecution:
        if self.email_reader is None:
            return EmailQueryExecution(
                AssistantReply(
                    conversation_id=conversation_id,
                    kind="error",
                    message="A leitura de e-mail está implementada, mas não está configurada neste ambiente.",
                )
            )
        query = build_email_query(conversation_id, command, now=self._local_now(), timezone=self.timezone)
        if isinstance(query, EmailQueryExecution):
            return query

        query_started = monotonic()
        result = self.email_reader.query(query)
        logger.info(
            "assistant_email stage=read outcome=%s category=%s candidates=%d results=%d duration_ms=%d",
            result.state,
            command.category or "all",
            result.candidate_count,
            len(result.messages),
            max(0, round((monotonic() - query_started) * 1000)),
        )
        return present_email_query(
            conversation_id, command, result, start_at=query.start_at, end_at=query.end_at,
            evidence_id=f"email:{secrets.token_hex(12)}",
        )

    @staticmethod
    def _task_due_relation(due_date: date | None, today: date) -> str:
        if due_date is None:
            return "sem prazo"
        difference = (due_date - today).days
        if difference < 0:
            days = abs(difference)
            return f"atrasada ha {days} dia" + ("s" if days != 1 else "")
        if difference == 0:
            return "vence hoje"
        return f"vence em {difference} dia" + ("s" if difference != 1 else "")

    def _ground_task_creation(
        self,
        conversation_id: int,
        source_message: str,
        command: TaskCreateCommand,
    ) -> TaskCreateCommand:
        normalized_source = normalize_text(source_message)
        updates: dict[str, object] = {}
        if command.client and normalize_text(command.client) not in normalized_source:
            updates["client"] = None
        if command.responsible and normalize_text(command.responsible) not in normalized_source:
            updates["responsible"] = None
        if command.due_date is None or self._message_mentions_date(source_message):
            return command.model_copy(update=updates) if updates else command
        clarification = (
            self.db.query(AssistantAction)
            .filter(
                AssistantAction.conversation_id == conversation_id,
                AssistantAction.action_type == "create_task",
                AssistantAction.status == "needs_clarification",
            )
            .order_by(AssistantAction.id.desc())
            .first()
        )
        preserved_due_date = None
        if clarification is not None:
            preserved_due_date = clarification.arguments_json.get("due_date")
        updates["due_date"] = preserved_due_date
        return command.model_copy(update=updates)

    def _resolve_task_email_source(
        self,
        conversation_id: int,
        source_message: str,
        requested_reference: str | None,
    ) -> tuple[dict[str, object] | None, str | None]:
        normalized = normalize_text(source_message)
        references_previous_email = bool(
            requested_reference
            or re.search(
                r"\b(?:responder|resposta|tarefa)\b.{0,60}\b(?:esse|este|segundo|primeiro|terceiro|e[- ]?mail)\b",
                normalized,
            )
        )
        if not references_previous_email:
            return None, None
        message = (
            self.db.query(AssistantMessage)
            .filter(
                AssistantMessage.conversation_id == conversation_id,
                AssistantMessage.role == "assistant",
            )
            .order_by(AssistantMessage.id.desc())
            .first()
        )
        while message is not None:
            raw_items = message.details_json.get("email_items", [])
            if isinstance(raw_items, list) and raw_items:
                items = [item for item in raw_items if isinstance(item, dict)]
                break
            message = (
                self.db.query(AssistantMessage)
                .filter(
                    AssistantMessage.conversation_id == conversation_id,
                    AssistantMessage.role == "assistant",
                    AssistantMessage.id < message.id,
                )
                .order_by(AssistantMessage.id.desc())
                .first()
            )
        else:
            items = []
        if not items:
            return (
                None,
                "Não há um e-mail apresentado nesta conversa para vincular à tarefa.",
            )
        if requested_reference:
            match = next(
                (item for item in items if item.get("reference") == requested_reference),
                None,
            )
            if match is None:
                return (
                    None,
                    "A referência de e-mail não pertence às mensagens apresentadas nesta conversa.",
                )
            return match, None
        ordinal_terms = {"primeiro": 0, "segundo": 1, "terceiro": 2}
        for term, index in ordinal_terms.items():
            if term in normalized:
                if index < len(items):
                    return items[index], None
                return None, f"Não existe um {term} e-mail no último resultado."
        if len(items) == 1:
            return items[0], None
        subjects = "; ".join(
            f"{index}. {item.get('subject') or '(sem assunto)'}" for index, item in enumerate(items, start=1)
        )
        return None, f"Qual e-mail você quer usar? {subjects}"

    _message_mentions_date = staticmethod(intent_routing.message_mentions_date)

    @staticmethod
    def _task_creation_is_forbidden(message: str) -> bool:
        normalized = normalize_text(message)
        explicit_task = bool(re.search(r"\b(?:crie|criar|cria|tarefa|lembrete)\b", normalized))
        service_request = bool(re.search(r"\b(?:servico|chamado|inspecao|conserto|atendimento)\b", normalized))
        if service_request and not explicit_task:
            return True
        return AssistantService._request_targets_unavailable_operation(message) or (
            AssistantService._request_targets_email_read(message) and not explicit_task
        )

    @staticmethod
    def _request_targets_email_read(message: str) -> bool:
        normalized = normalize_text(message)
        return AssistantService._direct_email_query(message) is not None or bool(
            re.search(r"\b(?:e[- ]?mails?|caixa de entrada|mensagens?)\b", normalized)
            and re.search(
                r"\b(?:quais|qual|cheg\w*|receb\w*|resum\w*|ler|leia|nao li|atenção|atencao|"
                r"esperando|resposta|consult\w*|confer\w*|verific\w*|mostr\w*|tem algum)\b",
                normalized,
            )
        )

    @staticmethod
    def _request_targets_unavailable_operation(message: str) -> bool:
        if AssistantService._request_targets_email_read(message):
            return False
        normalized = normalize_text(message)
        return bool(
            re.search(
                r"\b(atendimento|pagamento|financeiro|conta paga|nota fiscal|emitir nota|"
                r"enviar (?:e-mail|email|mensagem)|excluir|apagar)\b",
                normalized,
            )
        )

    @staticmethod
    def _response_states_limitation(message: str) -> bool:
        normalized = normalize_text(message)
        return bool(
            re.search(
                r"\b(?:ainda )?nao (?:posso|consigo|cadastro|registro|executo|esta disponivel|tenho suporte)\b|"
                r"\bindisponivel\b",
                normalized,
            )
        )

    def _conversation_reply(
        self,
        conversation_id: int,
        command: ConversationCommand,
        *,
        tool_results: Sequence[ProviderToolResult] = (),
        current_message: str = "",
    ) -> AssistantReply:
        validate_conversation_claims(
            command.message, tool_results=tool_results, current_message=current_message,
            historical_email_evidence=lambda: self._has_historical_email_evidence(conversation_id),
        )
        email_result = next(
            (result for result in reversed(tool_results) if result.tool == "consultar_emails"),
            None,
        )
        email_items = []
        consulted_interval = None
        limitations = []
        if email_result is not None:
            raw_items = email_result.payload.get("messages", [])
            if isinstance(raw_items, list):
                email_items = [item for item in raw_items if isinstance(item, dict)]
            raw_interval = email_result.payload.get("interval")
            consulted_interval = raw_interval if isinstance(raw_interval, str) else None
            raw_limitations = email_result.payload.get("limitations", [])
            if isinstance(raw_limitations, list):
                limitations = [str(item) for item in raw_limitations]
        reply_message = command.message.strip()
        if limitations and normalize_text(limitations[0]) not in normalize_text(reply_message):
            reply_message = f"{reply_message} Limitação: {limitations[0]}"
        return AssistantReply(
            conversation_id=conversation_id,
            kind="text",
            message=reply_message,
            email_items=email_items,
            consulted_interval=consulted_interval,
            limitations=limitations,
        )

    def _has_historical_email_evidence(self, conversation_id: int) -> bool:
        rows = (
            self.db.query(AssistantMessage)
            .filter(
                AssistantMessage.conversation_id == conversation_id,
                AssistantMessage.role == "assistant",
            )
            .order_by(AssistantMessage.id.desc())
            .limit(self.context_messages)
            .all()
        )
        return any(bool(row.details_json.get("email_items")) for row in rows)

    def _confirm_latest(self, conversation_id: int) -> AssistantReply:
        action = self._latest_create_action(conversation_id)
        if action is None:
            return AssistantReply(
                conversation_id=conversation_id,
                kind="clarification",
                message="Nao ha uma acao pendente nesta conversa para confirmar.",
            )
        if action.status == "cancelled":
            return AssistantReply(
                conversation_id=conversation_id,
                kind="text",
                message="Esta acao ja foi cancelada.",
                action_id=action.id,
            )
        return self._confirm_action_record(action, record_message=False)

    def _cancel_latest(self, conversation_id: int) -> AssistantReply:
        action = self._latest_create_action(conversation_id)
        if action is None:
            return AssistantReply(
                conversation_id=conversation_id,
                kind="clarification",
                message="Nao ha uma acao pendente nesta conversa para cancelar.",
            )
        if action.status == "executed":
            if action.action_type != "create_task":
                return AssistantReply(
                    conversation_id=conversation_id,
                    kind="error",
                    message="Esta ação já foi executada e não pode ser desfeita pelo assistente.",
                    action_id=action.id,
                    service_call_id=int(action.result_json.get("service_call_id") or 0) or None,
                    service_url=(
                        f"/web/services/{action.result_json.get('service_call_id')}"
                        if action.result_json.get("service_call_id")
                        else None
                    ),
                )
            return AssistantReply(
                conversation_id=conversation_id,
                kind="error",
                message="A acao ja foi executada e nao pode ser cancelada pelo assistente.",
                action_id=action.id,
                task_id=action.task_id,
                task_url=f"/web/board/{action.task_id}/edit" if action.task_id else None,
            )
        return self._cancel_action_record(action, record_message=False)

    def _latest_create_action(self, conversation_id: int) -> AssistantAction | None:
        pending = (
            self.db.query(AssistantAction)
            .filter(
                AssistantAction.conversation_id == conversation_id,
                AssistantAction.action_type.in_(
                    (
                        "create_task",
                        "register_service_event",
                        "correct_service_event",
                        "create_service_reminders",
                        "save_daily_schedule",
                        "generate_service_report",
                    )
                ),
                AssistantAction.status.in_(("pending", "needs_clarification")),
            )
            .order_by(AssistantAction.id.desc())
            .first()
        )
        if pending is not None:
            return pending
        return (
            self.db.query(AssistantAction)
            .filter(
                AssistantAction.conversation_id == conversation_id,
                AssistantAction.action_type.in_(
                    (
                        "create_task",
                        "register_service_event",
                        "correct_service_event",
                        "create_service_reminders",
                        "save_daily_schedule",
                        "generate_service_report",
                    )
                ),
            )
            .order_by(AssistantAction.id.desc())
            .first()
        )

    def _correct_pending_task(
        self,
        conversation_id: int,
        request_id: str,
        command: TaskDraftCorrectionCommand,
        today: date,
    ) -> AssistantReply:
        return self.task_drafts.correct(conversation_id, request_id, command, today)

    def _prepare_task(
        self,
        conversation_id: int,
        request_id: str,
        command: TaskCreateCommand,
        today: date,
        *,
        existing_action: AssistantAction | None = None,
    ) -> AssistantReply:
        return self.task_drafts.prepare(conversation_id, request_id, command, today, existing_action=existing_action)

    def _task_confirmation_reply(
        self,
        action: AssistantAction,
        confirmation_token: str,
    ) -> AssistantReply:
        return self.task_drafts.confirmation_reply(action, confirmation_token)

    def _record_clarification_action(
        self,
        conversation_id: int,
        request_id: str,
        command: TaskCreateCommand,
    ) -> None:
        return self.task_drafts.record_clarification(conversation_id, request_id, command)

    def _resolve_client(self, name: str | None) -> tuple[Client | None, str | None]:
        return self.entity_resolver.client(name)

    def _resolve_task_client(self, name: str | None) -> tuple[Client | None, str | None, str]:
        return self.entity_resolver.task_client(name)

    def _resolve_user(self, name: str | None) -> tuple[User | None, str | None]:
        return self.entity_resolver.user(name)

    def _resolve_named(
        self,
        name: str | None,
        candidates: Sequence[ModelT],
        label: Callable[[ModelT], str],
        entity_name: str,
    ) -> tuple[ModelT | None, str | None]:
        return self.entity_resolver.named(name, candidates, label, entity_name)

    def _success_reply(self, action: AssistantAction) -> AssistantReply:
        if action.action_type == "save_daily_schedule":
            result = action.result_json
            return AssistantReply(
                conversation_id=action.conversation_id,
                kind="success",
                message=(
                    f"Snapshot da agenda de {date.fromisoformat(str(result['schedule_date'])):%d/%m/%Y} salvo como versão {result['version']}. As tarefas não foram alteradas."
                ),
                action_id=action.id,
            )
        if action.action_type == "generate_service_report":
            result = action.result_json
            service_call_id = (
                int(result.get("service_call_id") or action.arguments_json.get("service_call_id") or 0) or None
            )
            report_id = int(result.get("report_id") or 0) or None
            return AssistantReply(
                conversation_id=action.conversation_id,
                kind="success",
                message=(
                    f"Relatório técnico do chamado #{service_call_id} gerado em DOCX e PDF. Nenhum evento técnico do chamado foi alterado."
                ),
                action_id=action.id,
                service_call_id=service_call_id,
                service_url=f"/web/services/{service_call_id}" if service_call_id else None,
                report_id=report_id,
                report_docx_url=str(result.get("report_docx_url") or "") or None,
                report_pdf_url=str(result.get("report_pdf_url") or "") or None,
            )
        if action.action_type in {
            "register_service_event",
            "correct_service_event",
            "create_service_reminders",
        }:
            return self.service_records.success(action)
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
