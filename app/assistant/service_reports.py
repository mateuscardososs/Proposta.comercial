"""Report preview preparation; confirmation transactions belong to AssistantService."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import date

from sqlalchemy.orm import Session

from app.assistant.contracts import (
    AssistantReply,
    CorrectServiceReportCommand,
    PrepareServiceReportCommand,
)
from app.models import AssistantAction
from app.schemas import ServiceTechnicalReportFields
from app.services import service_report_service


class AssistantServiceReportAdapter:
    def __init__(self, db: Session, *, token_hash: Callable[[str], str]) -> None:
        self.db = db
        self.token_hash = token_hash

    def prepare(
        self,
        conversation_id: int,
        request_id: str,
        command: PrepareServiceReportCommand,
    ) -> AssistantReply:
        candidates = service_report_service.completed_service_calls(
            self.db,
            service_call_id=command.service_call_id,
            client=command.client,
            reference=command.reference,
        )

        if not candidates:
            requested = (
                command.client
                or command.reference
                or (f"chamado #{command.service_call_id}" if command.service_call_id else "")
            )
            return AssistantReply(
                conversation_id=conversation_id,
                kind="clarification",
                message=(
                    f"Não encontrei chamado concluído correspondente a {requested!r}. Relatórios só podem ser preparados para execução explicitamente concluída."
                ),
            )
        if len(candidates) > 1:
            display_candidates = candidates[:10]
            options = [
                {
                    "id": call.id,
                    "client": call.client.razao_social,
                    "summary": call.summary,
                    "opened_on": call.opened_on.isoformat(),
                }
                for call in display_candidates
            ]
            lines = [
                (
                    "Encontrei mais de 10 chamados concluídos. Qual deles devo usar?"
                    if len(candidates) > 10
                    else f"Encontrei {len(candidates)} chamados concluídos. Qual deles devo usar?"
                )
            ]
            if len(candidates) > len(display_candidates):
                lines.append(
                    "Mostro os 10 mais recentes; informe empresa, descrição ou número do chamado para refinar."
                )
            lines.extend(
                f"#{item['id']} — {item['client']} — {item['summary']} — aberto em {item['opened_on']}"
                for item in options
            )
            return AssistantReply(
                conversation_id=conversation_id,
                kind="clarification",
                message="\n".join(lines),
                report_candidates=options,
            )

        call = candidates[0]
        pending_report = self.pending_action(conversation_id)
        if pending_report is not None:
            pending_call_id = int(pending_report.arguments_json.get("service_call_id") or 0)
            if pending_call_id != call.id:
                return AssistantReply(
                    conversation_id=conversation_id,
                    kind="clarification",
                    message=(
                        f"A prévia do chamado #{pending_call_id} ainda aguarda confirmação ou cancelamento. Resolva essa prévia antes de preparar outro relatório."
                    ),
                )
            return self.update_preview(pending_report, {})
        try:
            preview = service_report_service.build_preview(self.db, call.id)
        except service_report_service.ServiceReportError as exc:
            return AssistantReply(conversation_id=conversation_id, kind="error", message=str(exc))

        request_key = hashlib.sha256(request_id.encode()).hexdigest()[:40]
        token = secrets.token_urlsafe(32)
        action = AssistantAction(
            conversation_id=conversation_id,
            request_id=f"report-preview-{request_key}",
            confirmation_token_hash=self.token_hash(token),
            action_type="generate_service_report",
            status="pending",
            arguments_json={
                "service_call_id": call.id,
                "source_fingerprint": preview.source_fingerprint,
                "fields_json": preview.fields.model_dump(),
                "source_fields_json": preview.fields.model_dump(),
                "report_idempotency_key": f"assistant-report-{request_key}",
            },
        )
        self.db.add(action)
        self.db.flush()
        reply = self.preview_reply(action, token, preview.fields, preview.missing_fields)
        reply.message = self.preview_message(call.id, preview.missing_fields)
        return reply

    def correct(
        self,
        conversation_id: int,
        command: CorrectServiceReportCommand,
    ) -> AssistantReply:
        action = self.pending_action(conversation_id)
        if action is None:
            return AssistantReply(
                conversation_id=conversation_id,
                kind="clarification",
                message="Não há prévia de relatório técnico pendente para corrigir.",
            )
        return self.update_preview(
            action,
            command.model_dump(exclude_unset=True, exclude={"tool"}),
        )

    def pending_action(self, conversation_id: int) -> AssistantAction | None:
        return (
            self.db.query(AssistantAction)
            .filter(
                AssistantAction.conversation_id == conversation_id,
                AssistantAction.action_type == "generate_service_report",
                AssistantAction.status == "pending",
            )
            .order_by(AssistantAction.id.desc())
            .first()
        )

    def update_preview(
        self,
        action: AssistantAction,
        updates: dict[str, object],
    ) -> AssistantReply:
        call_id = int(action.arguments_json["service_call_id"])
        try:
            preview = service_report_service.build_preview(self.db, call_id)
            current_fields = dict(action.arguments_json.get("fields_json") or {})
            old_source = dict(action.arguments_json.get("source_fields_json") or {})
            source_fields = preview.fields.model_dump()
            if action.arguments_json.get("source_fingerprint") != preview.source_fingerprint:
                for name in service_report_service.FIELD_LABELS:
                    if current_fields.get(name) != old_source.get(name):
                        source_fields[name] = current_fields[name]
                current_fields = source_fields
            else:
                source_fields = old_source or source_fields
            current_fields.update(updates)
            reviewed_fields = ServiceTechnicalReportFields.model_validate(current_fields)
            if reviewed_fields.completion_date:
                date.fromisoformat(reviewed_fields.completion_date)
        except (service_report_service.ServiceReportError, ValueError) as exc:
            if isinstance(exc, service_report_service.ServiceReportError):
                message = str(exc)
            else:
                message = "A data da execução deve estar no formato AAAA-MM-DD."
            return AssistantReply(conversation_id=action.conversation_id, kind="error", message=message)

        token = secrets.token_urlsafe(32)
        action.arguments_json = {
            **action.arguments_json,
            "source_fingerprint": preview.source_fingerprint,
            "fields_json": reviewed_fields.model_dump(),
            "source_fields_json": source_fields,
        }
        action.confirmation_token_hash = self.token_hash(token)
        missing_fields = service_report_service._missing_fields(reviewed_fields)
        reply = self.preview_reply(action, token, reviewed_fields, missing_fields)
        reply.message = self.preview_message(call_id, missing_fields)
        return reply

    @staticmethod
    def preview_message(service_call_id: int, missing_fields: list[str]) -> str:
        call = f"#{service_call_id}"
        missing = (
            "Campos sem informação registrada e destacados para revisão: "
            + ", ".join(service_report_service.FIELD_LABELS[name] for name in missing_fields)
            + ". "
            if missing_fields
            else "Não há campos ausentes na prévia. "
        )
        return (
            f"Prévia editável do relatório técnico do chamado {call}. {missing}"
            "Revise os dados; qualquer correção exige nova confirmação. DOCX e PDF só serão gerados após confirmar."
        )

    @staticmethod
    def preview_reply(
        action: AssistantAction,
        token: str,
        fields: ServiceTechnicalReportFields,
        missing_fields: list[str],
    ) -> AssistantReply:
        return AssistantReply(
            conversation_id=action.conversation_id,
            kind="confirmation",
            message="Prévia de relatório técnico pronta para revisão.",
            action_id=action.id,
            confirmation_token=token,
            service_call_id=int(action.arguments_json["service_call_id"]),
            report_fields=fields.model_dump(),
            report_field_labels=dict(service_report_service.FIELD_LABELS),
            report_missing_fields=missing_fields,
        )

