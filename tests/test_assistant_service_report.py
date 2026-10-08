from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.assistant.contracts import (
    CancelActionCommand,
    CorrectServiceReportCommand,
    PrepareServiceReportCommand,
)
from app.assistant.service import AssistantService
from app.models import (
    AssistantAction,
    AssistantConversation,
    Client,
    ServiceCall,
    ServiceEvent,
    ServiceTechnicalReport,
    ServiceWorkflowStep,
)
from app.services import service_report_service


class QueueProvider:
    def __init__(self, *commands):
        self.commands = list(commands)
        self.calls = []

    def interpret(self, messages, **context):
        self.calls.append((messages, context))
        return self.commands.pop(0)


def _now():
    return datetime(2026, 10, 7, 10, 0, tzinfo=ZoneInfo("America/Recife"))


def _completed_call(db, client_name: str, summary: str = "Manutenção sintética"):
    client = Client(razao_social=client_name)
    conversation = AssistantConversation()
    db.add_all([client, conversation])
    db.flush()
    call = ServiceCall(
        client_id=client.id,
        summary=summary,
        opened_on=date(2026, 10, 1),
        execution_status="completed",
    )
    db.add(call)
    db.flush()
    action = AssistantAction(
        conversation_id=conversation.id,
        request_id=f"service-event-{call.id}",
        confirmation_token_hash=f"{call.id:064d}",
        action_type="register_service_event",
        status="executed",
    )
    db.add(action)
    db.flush()
    db.add(ServiceEvent(
        service_call_id=call.id,
        assistant_action_id=action.id,
        conversation_id=conversation.id,
        event_type="execution_completed",
        occurred_on=date(2026, 10, 2),
        description=(
            "Equipamento: Balança de bancada\n"
            "Problema relatado: Falha sintética\n"
            "Análise: Análise sintética\n"
            "Serviço executado: Reparo sintético"
        ),
    ))
    for step_type in ("report", "proposal", "proposal_sent", "invoice", "receipt"):
        db.add(ServiceWorkflowStep(service_call_id=call.id, step_type=step_type))
    db.commit()
    return call


def test_report_source_refresh_preserves_reviewed_fields(db):
    call = _completed_call(db, "Fonte sintética")
    assistant = AssistantService(db, None, now=_now)
    conversation = AssistantConversation()
    db.add(conversation)
    db.flush()
    first = assistant._prepare_service_report(
        conversation.id, "source-refresh", PrepareServiceReportCommand(service_call_id=call.id)
    )
    action = db.get(AssistantAction, first.action_id)
    corrected = assistant._update_service_report_preview(action, {"equipment": "Equipamento revisado"})
    old_fingerprint = action.arguments_json["source_fingerprint"]
    call.client.razao_social = "Fonte atualizada sintética"
    db.flush()
    refreshed = assistant._update_service_report_preview(action, {})
    assert refreshed.kind == "confirmation"
    assert refreshed.report_fields["equipment"] == "Equipamento revisado"
    assert refreshed.confirmation_token != corrected.confirmation_token
    assert action.arguments_json["source_fingerprint"] != old_fingerprint
    assert action.arguments_json["source_fingerprint"] == service_report_service.build_preview(db, call.id).source_fingerprint


def test_report_request_with_multiple_matching_calls_asks_which_without_preparing(db):
    first = _completed_call(db, "Alfa Serviços", "Revisão da balança")
    second = _completed_call(db, "Alfa Serviços", "Troca do indicador")
    provider = QueueProvider(PrepareServiceReportCommand(client="Alfa Serviços"))
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="Gere o relatório do serviço da Alfa Serviços",
        request_id="report-ambiguous",
    )

    assert reply.kind == "clarification"
    assert str(first.id) in reply.message and str(second.id) in reply.message
    assert db.query(AssistantAction).filter_by(action_type="generate_service_report").count() == 0
    assert db.query(ServiceTechnicalReport).count() == 0


def test_large_report_ambiguity_bounds_chat_options_and_requests_refinement(db):
    for index in range(12):
        _completed_call(db, f"Cliente Sintético {index:02d}", f"Serviço {index:02d}")
    provider = QueueProvider(PrepareServiceReportCommand())
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="Prepare um relatório técnico de serviço concluído",
        request_id="report-many-candidates",
    )

    assert reply.kind == "clarification"
    assert len(reply.report_candidates) == 10
    assert "mais de 10 chamados concluídos" in reply.message
    assert "empresa, descrição ou número" in reply.message
    assert [item["id"] for item in reply.report_candidates] == list(range(12, 2, -1))
    assert db.query(AssistantAction).filter_by(action_type="generate_service_report").count() == 0


def test_completed_report_lookup_fetches_only_newest_eleven_candidates(db):
    calls = [
        _completed_call(db, f"Cliente Sintético {index:02d}", f"Serviço {index:02d}")
        for index in range(12)
    ]

    matches = service_report_service.completed_service_calls(db)

    assert len(matches) == 11
    assert [call.id for call in matches] == [call.id for call in reversed(calls[1:])]


def test_report_lookup_preserves_accent_insensitive_client_and_summary_search(db):
    call = _completed_call(db, "Alfa Serviços", "Revisão da balança")

    matches = service_report_service.completed_service_calls(
        db,
        client="alfa servicos",
        reference="revisao da balanca",
    )

    assert [item.id for item in matches] == [call.id]


def test_explicit_service_call_id_is_authoritative_over_other_hints(db):
    call = _completed_call(db, "Alfa Serviços", "Revisão da balança")
    provider = QueueProvider(
        PrepareServiceReportCommand(
            service_call_id=call.id,
            client="Empresa errada",
            reference="resumo que não corresponde",
        )
    )
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message=f"Prepare o relatório técnico do chamado #{call.id}",
        request_id="report-explicit-id-wins",
    )

    assert reply.kind == "confirmation"
    assert reply.service_call_id == call.id


def test_out_of_range_service_id_is_treated_as_not_found(db):
    _completed_call(db, "Alfa Serviços", "Revisão da balança")
    out_of_range_id = 9_999_999_999_999_999_999_999

    assert service_report_service.completed_service_calls(
        db, service_call_id=out_of_range_id
    ) == []
    assert service_report_service.completed_service_calls(
        db, reference=str(out_of_range_id)
    ) == []


def test_report_ambiguity_can_continue_with_selected_call_in_same_conversation(db):
    _completed_call(db, "Alfa Serviços", "Revisão da balança")
    second = _completed_call(db, "Alfa Serviços", "Troca do indicador")
    provider = QueueProvider(
        PrepareServiceReportCommand(client="Alfa Serviços"),
        PrepareServiceReportCommand(service_call_id=second.id),
    )
    service = AssistantService(db, provider, now=_now)
    ambiguous = service.handle_message(
        message="Prepare o relatório do serviço da Alfa Serviços",
        request_id="report-ambiguous-followup",
    )
    selected = service.handle_message(
        message="Use o segundo chamado",
        request_id="report-ambiguous-selected",
        conversation_id=ambiguous.conversation_id,
    )

    assert ambiguous.kind == "clarification"
    assert selected.kind == "confirmation"
    assert selected.service_call_id == second.id
    assert db.query(ServiceTechnicalReport).count() == 0


def test_report_preview_includes_missing_fields_and_correction_rotates_confirmation(db):
    call = _completed_call(db, "Cliente Sintético")
    provider = QueueProvider(
        PrepareServiceReportCommand(service_call_id=call.id),
        CorrectServiceReportCommand(equipment="Balança plataforma"),
    )
    service = AssistantService(db, provider, now=_now)

    preview = service.handle_message(
        message="Prepare o relatório técnico do chamado #1",
        request_id="report-preview",
    )

    assert preview.kind == "confirmation"
    assert preview.report_fields["equipment"] == "Balança de bancada"
    assert "verification_result" in preview.report_missing_fields
    corrected = service.handle_message(
        message="Corrija o equipamento para balança plataforma",
        request_id="report-correction",
        conversation_id=preview.conversation_id,
    )

    assert corrected.kind == "confirmation"
    assert corrected.action_id == preview.action_id
    assert corrected.report_fields["equipment"] == "Balança plataforma"
    assert corrected.confirmation_token != preview.confirmation_token
    assert db.query(ServiceTechnicalReport).count() == 0
    with pytest.raises(ValueError, match="Token de confirmacao invalido"):
        service.confirm_action(preview.action_id, preview.confirmation_token)


def test_repeated_preview_request_reuses_one_pending_action_and_rotates_token(db):
    call = _completed_call(db, "Cliente Sintético")
    provider = QueueProvider(
        PrepareServiceReportCommand(service_call_id=call.id),
        PrepareServiceReportCommand(service_call_id=call.id),
    )
    service = AssistantService(db, provider, now=_now)
    first = service.handle_message(
        message="Prepare o relatório técnico do chamado #1",
        request_id="report-preview-retry",
    )
    replay = service.handle_message(
        message="Prepare o relatório técnico do chamado #1",
        request_id="report-preview-retry",
        conversation_id=first.conversation_id,
        retry=True,
    )
    repeated_intent = service.handle_message(
        message="Gere novamente o relatório desse chamado",
        request_id="report-preview-repeat-intent",
        conversation_id=first.conversation_id,
    )

    assert replay.action_id == first.action_id
    assert replay.confirmation_token != first.confirmation_token
    assert repeated_intent.action_id == first.action_id
    assert repeated_intent.confirmation_token != replay.confirmation_token
    assert db.query(AssistantAction).filter_by(action_type="generate_service_report").count() == 1
    assert db.query(ServiceTechnicalReport).count() == 0


def test_cancel_report_preview_does_not_generate_or_change_service_events(db):
    call = _completed_call(db, "Cliente Sintético")
    provider = QueueProvider(PrepareServiceReportCommand(service_call_id=call.id))
    service = AssistantService(db, provider, now=_now)
    preview = service.handle_message(
        message="Gere o relatório técnico do chamado #1",
        request_id="report-cancel-preview",
    )
    provider.commands = [CancelActionCommand()]

    cancelled = service.handle_message(
        message="Cancela",
        request_id="report-cancel",
        conversation_id=preview.conversation_id,
    )

    assert cancelled.kind == "text"
    assert db.query(ServiceTechnicalReport).count() == 0
    assert db.query(ServiceEvent).filter_by(service_call_id=call.id).count() == 1
    assert db.query(AssistantAction).filter_by(action_type="generate_service_report").one().status == "cancelled"


def test_report_confirmation_generates_once_and_returns_chat_download_links(db, monkeypatch, tmp_path):
    call = _completed_call(db, "Cliente Sintético")
    provider = QueueProvider(PrepareServiceReportCommand(service_call_id=call.id))
    service = AssistantService(db, provider, now=_now)
    preview = service.handle_message(
        message="Gere o relatório técnico do chamado #1",
        request_id="report-confirm-preview",
    )

    def fake_pdf(docx_path: Path, pdf_path: Path, libreoffice_cmd: str, *, docker_image: str = ""):
        del docx_path, libreoffice_cmd, docker_image
        pdf_path.write_bytes(b"%PDF-1.4 synthetic report")
        return pdf_path

    monkeypatch.setattr(service_report_service.pdf_service, "convert_docx_to_pdf", fake_pdf)
    settings = service_report_service.ReportGenerationSettings(
        output_dir=tmp_path / "reports",
        template_path=Path("doc_templates/relatorio_tecnico_template.docx"),
        libreoffice_cmd="soffice",
        timezone="America/Recife",
    )
    monkeypatch.setattr(service_report_service, "assistant_generation_settings", lambda: settings, raising=False)

    saved = service.confirm_action(preview.action_id, preview.confirmation_token)
    repeated = service.confirm_action(preview.action_id, preview.confirmation_token)

    assert saved.kind == "success"
    assert saved.report_docx_url and saved.report_pdf_url
    assert repeated.report_id == saved.report_id
    assert db.query(ServiceTechnicalReport).count() == 1
    assert db.query(ServiceEvent).filter_by(service_call_id=call.id).count() == 1
    assert db.query(AssistantAction).filter_by(action_type="generate_service_report").count() == 1
    assert db.query(AssistantAction).filter_by(action_type="generate_service_report").one().status == "executed"


def test_voice_and_text_use_same_report_confirmation_flow(db):
    call = _completed_call(db, "Cliente Sintético")
    provider = QueueProvider(PrepareServiceReportCommand(service_call_id=call.id))
    service = AssistantService(db, provider, now=_now)

    reply = service.handle_message(
        message="Gere o relatório do chamado número 1",
        request_id="report-voice",
        source="voice",
    )

    assert reply.kind == "confirmation"
    assert reply.action_id is not None
    assert db.query(ServiceTechnicalReport).count() == 0
    assert provider.calls[0][1]["allowed_tools"] >= {"preparar_relatorio_tecnico"}
