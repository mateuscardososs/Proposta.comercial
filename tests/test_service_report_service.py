from __future__ import annotations

import hashlib
import os
import zipfile
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base, ensure_service_history_guards_for_engine
from app.models import (
    AssistantAction,
    AssistantConversation,
    Client,
    ServiceCall,
    ServiceEvent,
    ServiceTechnicalReport,
    ServiceWorkflowStep,
)
from app.schemas import ServiceTechnicalReportFields
from app.services import service_report_service


@pytest.fixture
def report_db(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'service-reports.sqlite3'}")
    Base.metadata.create_all(engine)
    ensure_service_history_guards_for_engine(engine)
    try:
        with Session(engine, expire_on_commit=False) as db:
            yield db, tmp_path
    finally:
        engine.dispose()


def _completed_call(
    db: Session, *, include_details: bool = True, client_details: bool = True,
) -> ServiceCall:
    client_data = {
        "cnpj": "00.000.000/0001-00",
        "telefone": "(00) 0000-0000",
        "endereco_linha1": "Rua de Teste, 100",
        "cidade_uf": "Recife/PE",
    } if client_details else {}
    client = Client(razao_social="Cliente Sintético", **client_data)
    conversation = AssistantConversation()
    db.add_all([client, conversation])
    db.flush()
    call = ServiceCall(
        client_id=client.id,
        summary="Reparo de balança de bancada",
        opened_on=date(2026, 10, 1),
        execution_status="completed",
    )
    db.add(call)
    db.flush()
    for kind in ("report", "proposal", "proposal_sent", "invoice", "receipt"):
        db.add(ServiceWorkflowStep(service_call_id=call.id, step_type=kind))
    details = (
        "Equipamento: Balança de bancada\n"
        "Problema relatado: Leitura oscilando\n"
        "Análise: Registro sintético de análise\n"
        "Serviço executado: Ajuste registrado no chamado"
        if include_details else "Execução concluída sem detalhes técnicos registrados."
    )
    event = ServiceEvent(
        service_call_id=call.id,
        assistant_action_id=1,
        conversation_id=conversation.id,
        event_type="execution_completed",
        occurred_on=date(2026, 10, 2),
        description=details,
    )
    action = AssistantAction(
        conversation_id=conversation.id,
        request_id="service-report-source",
        confirmation_token_hash="a" * 64,
        action_type="register_service_event",
        status="executed",
    )
    db.add(action)
    db.flush()
    event.assistant_action_id = action.id
    db.add(event)
    db.commit()
    return call


def test_preview_uses_only_effective_recorded_facts_and_marks_missing_fields(report_db):
    db, _ = report_db
    call = _completed_call(db)
    preview = service_report_service.build_preview(db, call.id)

    assert preview.fields.equipment == "Balança de bancada"
    assert preview.fields.reported_problem == "Leitura oscilando"
    assert preview.fields.analysis == "Registro sintético de análise"
    assert preview.fields.work_performed == "Ajuste registrado no chamado"
    assert preview.fields.verification_result == ""
    assert preview.missing_fields == ["verification_result"]
    assert preview.source_event_ids == [1]
    assert db.scalar(select(ServiceTechnicalReport.id)) is None


def test_preview_refuses_call_without_explicit_technical_completion(report_db):
    db, _ = report_db
    call = _completed_call(db)
    call.execution_status = "in_progress"
    db.flush()

    with pytest.raises(service_report_service.ServiceReportNotReady):
        service_report_service.build_preview(db, call.id)


def test_preview_reads_corrected_effective_event_without_changing_original(report_db):
    db, _ = report_db
    call = _completed_call(db)
    original = db.scalar(select(ServiceEvent).where(ServiceEvent.service_call_id == call.id))
    correction_action = AssistantAction(
        conversation_id=original.conversation_id,
        request_id="service-report-correction",
        confirmation_token_hash=hashlib.sha256(b"service-report-correction").hexdigest(),
        action_type="correct_service_event",
        status="executed",
    )
    db.add(correction_action)
    db.flush()
    corrected = ServiceEvent(
        service_call_id=call.id,
        assistant_action_id=correction_action.id,
        conversation_id=original.conversation_id,
        event_type="correction",
        occurred_on=date(2026, 10, 3),
        description="Correção append-only",
        supersedes_event_id=original.id,
        correction_reason="Equipamento especificado incorretamente",
        corrected_description=(
            "Equipamento: Balança industrial\n"
            "Problema relatado: Leitura oscilando\n"
            "Análise: Registro sintético de análise\n"
            "Serviço executado: Ajuste registrado no chamado"
        ),
    )
    db.add(corrected)
    db.commit()

    preview = service_report_service.build_preview(db, call.id)

    assert preview.fields.equipment == "Balança industrial"
    assert original.description.startswith("Equipamento: Balança de bancada")
    assert db.query(ServiceEvent).filter_by(service_call_id=call.id).count() == 2


def test_preview_uses_recorded_return_verification_result(report_db):
    db, _ = report_db
    call = _completed_call(db)
    source = db.scalar(select(ServiceEvent).where(ServiceEvent.service_call_id == call.id))
    verification_action = AssistantAction(
        conversation_id=source.conversation_id,
        request_id="service-report-verification",
        confirmation_token_hash=hashlib.sha256(b"service-report-verification").hexdigest(),
        action_type="register_service_event",
        status="executed",
    )
    db.add(verification_action)
    db.flush()
    db.add(ServiceEvent(
        service_call_id=call.id,
        assistant_action_id=verification_action.id,
        conversation_id=source.conversation_id,
        event_type="note",
        occurred_on=date(2026, 10, 4),
        description="Verificacao de retorno — tarefa #8: resolvido.\nLeitura estabilizada na conferência.",
    ))
    db.commit()

    preview = service_report_service.build_preview(db, call.id)

    assert preview.fields.verification_result == (
        "Retorno registrado como resolvido. Leitura estabilizada na conferência."
    )
    assert preview.event_timeline[-1]["type"] == "Observação"


def test_report_snapshot_cannot_be_updated_or_deleted(report_db, monkeypatch, tmp_path):
    db, _ = report_db
    call = _completed_call(db)
    settings = service_report_service.ReportGenerationSettings(
        output_dir=tmp_path / "reports",
        template_path=Path("doc_templates/relatorio_tecnico_template.docx"),
        libreoffice_cmd="soffice",
        timezone="America/Recife",
    )

    def fake_pdf(docx_path: Path, pdf_path: Path, libreoffice_cmd: str, *, docker_image: str = "") -> Path:
        del libreoffice_cmd
        del docker_image
        pdf_path.write_bytes(b"%PDF-1.4 synthetic test artifact")
        return pdf_path

    monkeypatch.setattr(service_report_service.pdf_service, "convert_docx_to_pdf", fake_pdf)
    result = service_report_service.generate_report(
        db,
        call.id,
        ServiceTechnicalReportFields(
            client_name="Cliente Sintético",
            client_cnpj="12.345.678/0001-90",
            completion_date="2026-10-02",
        ),
        idempotency_key="immutable-report",
        settings=settings,
        confirmed=True,
    )

    result.report.fields_json = {**result.report.fields_json, "work_performed": "alterado"}
    with pytest.raises(ValueError, match="Historico de servico imutavel"):
        db.flush()
    db.rollback()
    report = db.get(ServiceTechnicalReport, result.report.id)
    db.delete(report)
    with pytest.raises(ValueError, match="Historico de servico imutavel"):
        db.flush()


def test_generation_requires_confirmation_and_persists_review_snapshot_idempotently(
    report_db, monkeypatch, tmp_path
):
    db, _ = report_db
    call = _completed_call(db)
    settings = service_report_service.ReportGenerationSettings(
        output_dir=tmp_path / "reports",
        template_path=Path("doc_templates/relatorio_tecnico_template.docx"),
        libreoffice_cmd="soffice",
        timezone="America/Recife",
    )

    with pytest.raises(service_report_service.ReportConfirmationRequired):
        service_report_service.generate_report(
            db,
            call.id,
            ServiceTechnicalReportFields(),
            idempotency_key="retry-safe-report-1",
            settings=settings,
            confirmed=False,
        )
    assert db.scalar(select(ServiceTechnicalReport.id)) is None

    def fake_pdf(docx_path: Path, pdf_path: Path, libreoffice_cmd: str, *, docker_image: str = "") -> Path:
        del libreoffice_cmd
        del docker_image
        pdf_path.write_bytes(b"%PDF-1.4 synthetic test artifact")
        return pdf_path

    monkeypatch.setattr(service_report_service.pdf_service, "convert_docx_to_pdf", fake_pdf)
    reviewed = ServiceTechnicalReportFields(
        client_name="Cliente Sintético",
        client_cnpj="00.000.000/0001-00",
        client_phone="(00) 0000-0000",
        client_address="Rua de Teste, 100 · Recife/PE",
        equipment="Balança de bancada",  # reviewed from the call
        completion_date="2026-10-02",
        reported_problem="Oscilação confirmada pelo técnico",
        analysis="Registro sintético de análise",
        work_performed="Ajuste registrado no chamado",
        verification_result="Revisão manual pendente",
    )
    report = service_report_service.generate_report(
        db,
        call.id,
        reviewed,
        idempotency_key="retry-safe-report-1",
        settings=settings,
        confirmed=True,
    )
    event_count = db.query(ServiceEvent).count()
    action_count = db.query(AssistantAction).count()
    repeated = service_report_service.generate_report(
        db,
        call.id,
        reviewed,
        idempotency_key="retry-safe-report-1",
        settings=settings,
        confirmed=True,
    )

    assert repeated.report.id == report.report.id
    assert report.docx_path.is_file() and report.pdf_path.is_file()
    assert report.report.fields_json["reported_problem"] == "Oscilação confirmada pelo técnico"
    assert report.report.source_event_ids == [1]
    assert db.query(ServiceTechnicalReport).count() == 1
    assert db.query(ServiceEvent).count() == event_count == 1
    assert report.report.document_event_id is None
    assert db.query(AssistantAction).count() == action_count == 2
    with zipfile.ZipFile(report.docx_path) as archive:
        docx_text = archive.read("word/document.xml").decode("utf-8")
    assert "Oscilação confirmada pelo técnico" in docx_text
    assert "PENDENTE DE REVISÃO" not in docx_text
    assert "{{" not in docx_text
    assert "00.000.000/0001-00" in docx_text


def test_commit_response_loss_reconciles_by_confirmation_key(report_db, monkeypatch, tmp_path):
    db, _ = report_db
    call = _completed_call(db)
    settings = service_report_service.ReportGenerationSettings(
        output_dir=tmp_path / "reports",
        template_path=Path("doc_templates/relatorio_tecnico_template.docx"),
        libreoffice_cmd="soffice",
        timezone="America/Recife",
    )

    def fake_pdf(docx_path: Path, pdf_path: Path, libreoffice_cmd: str, *, docker_image: str = "") -> Path:
        del libreoffice_cmd
        del docker_image
        pdf_path.write_bytes(b"%PDF-1.4 synthetic test artifact")
        return pdf_path

    monkeypatch.setattr(service_report_service.pdf_service, "convert_docx_to_pdf", fake_pdf)
    original_refresh = db.refresh

    def lose_commit_ack(instance, *args, **kwargs):
        if isinstance(instance, ServiceTechnicalReport):
            raise RuntimeError("synthetic connection interruption after commit")
        return original_refresh(instance, *args, **kwargs)

    monkeypatch.setattr(db, "refresh", lose_commit_ack)
    result = service_report_service.generate_report(
        db,
        call.id,
        ServiceTechnicalReportFields(
            client_name="Cliente Sintético",
            client_cnpj="12.345.678/0001-90",
            completion_date="2026-10-02",
        ),
        idempotency_key="ambiguous-commit-report",
        settings=settings,
        confirmed=True,
    )

    assert result.replayed is True
    assert result.docx_path.is_file() and result.pdf_path.is_file()
    assert db.query(ServiceTechnicalReport).filter_by(
        idempotency_key="ambiguous-commit-report"
    ).count() == 1


def test_stale_preview_and_pdf_failure_do_not_save_report(report_db, monkeypatch, tmp_path):
    db, _ = report_db
    call = _completed_call(db)
    preview = service_report_service.build_preview(db, call.id)
    source_event = db.scalar(select(ServiceEvent).where(ServiceEvent.service_call_id == call.id))
    correction_action = AssistantAction(
        conversation_id=source_event.conversation_id,
        request_id="service-report-stale-correction",
        confirmation_token_hash=hashlib.sha256(b"service-report-stale-correction").hexdigest(),
        action_type="correct_service_event",
        status="executed",
    )
    db.add(correction_action)
    db.flush()
    db.add(ServiceEvent(
        service_call_id=call.id,
        assistant_action_id=correction_action.id,
        conversation_id=source_event.conversation_id,
        event_type="correction",
        occurred_on=date(2026, 10, 3),
        description="Correção de teste",
        supersedes_event_id=source_event.id,
        correction_reason="Correção de origem",
        corrected_description="Equipamento: Balança revista",
    ))
    db.commit()
    settings = service_report_service.ReportGenerationSettings(
        output_dir=tmp_path / "reports",
        template_path=Path("doc_templates/relatorio_tecnico_template.docx"),
        libreoffice_cmd="soffice",
        timezone="America/Recife",
    )
    with pytest.raises(service_report_service.ReportPreviewOutdated):
        service_report_service.generate_report(
            db,
            call.id,
            preview.fields,
            idempotency_key="stale-report-preview",
            settings=settings,
            confirmed=True,
            expected_fingerprint=preview.source_fingerprint,
        )

    current = service_report_service.build_preview(db, call.id)
    monkeypatch.setattr(
        service_report_service.pdf_service,
        "convert_docx_to_pdf",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("local converter unavailable")),
    )
    with pytest.raises(service_report_service.ReportGenerationError, match="Nenhum relatório foi registrado"):
        service_report_service.generate_report(
            db,
            call.id,
            current.fields,
            idempotency_key="pdf-failure-report",
            settings=settings,
            confirmed=True,
            expected_fingerprint=current.source_fingerprint,
        )
    assert db.query(ServiceTechnicalReport).count() == 0
    assert db.query(ServiceEvent).count() == 2
    assert not list((tmp_path / "reports").rglob("*.docx"))


def test_missing_source_fields_are_highlighted_in_docx(report_db, monkeypatch, tmp_path):
    db, _ = report_db
    call = _completed_call(db, include_details=False, client_details=False)
    preview = service_report_service.build_preview(db, call.id)
    assert set(preview.missing_fields) == {
        "equipment", "reported_problem", "analysis", "work_performed", "verification_result",
        "client_cnpj", "client_phone", "client_address",
    }
    settings = service_report_service.ReportGenerationSettings(
        output_dir=tmp_path / "reports",
        template_path=Path("doc_templates/relatorio_tecnico_template.docx"),
        libreoffice_cmd="soffice",
        timezone="America/Recife",
    )

    def fake_pdf(docx_path: Path, pdf_path: Path, libreoffice_cmd: str, *, docker_image: str = "") -> Path:
        del libreoffice_cmd
        del docker_image
        pdf_path.write_bytes(b"%PDF-1.4 synthetic test artifact")
        return pdf_path

    monkeypatch.setattr(service_report_service.pdf_service, "convert_docx_to_pdf", fake_pdf)
    report = service_report_service.generate_report(
        db,
        call.id,
        ServiceTechnicalReportFields(
            client_name="Cliente Sintético",
            client_cnpj="12.345.678/0001-90",
            completion_date="2026-10-02",
        ),
        idempotency_key="missing-fields-report",
        settings=settings,
        confirmed=True,
    )
    with zipfile.ZipFile(report.docx_path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")

    assert "PENDENTE DE REVISÃO" in xml
    assert "w:highlight" in xml
    assert len(report.report.missing_fields_json) == 7
    assert "client_cnpj" not in report.report.missing_fields_json


@pytest.mark.skipif(
    os.getenv("RUN_REPORT_DOCKER_CONVERTER_TEST") != "1",
    reason="explicit opt-in integration test; requires a local converter image",
)
def test_confirmed_service_report_generates_docx_and_pdf_with_local_container(
    report_db, tmp_path
):
    db, _ = report_db
    call = _completed_call(db)
    image = os.getenv("TECHNICAL_REPORT_PDF_CONVERTER_IMAGE", "").strip()
    assert image, "Set TECHNICAL_REPORT_PDF_CONVERTER_IMAGE to a local trusted image."
    settings = service_report_service.ReportGenerationSettings(
        output_dir=tmp_path / "reports",
        template_path=Path("doc_templates/relatorio_tecnico_template.docx"),
        libreoffice_cmd="__not_installed__",
        timezone="America/Recife",
        libreoffice_docker_image=image,
    )

    result = service_report_service.generate_report(
        db,
        call.id,
        ServiceTechnicalReportFields(
            client_name="Cliente Sintético",
            client_cnpj="00.000.000/0001-00",
            completion_date="2026-10-02",
        ),
        idempotency_key="real-local-converter-report",
        settings=settings,
        confirmed=True,
    )

    assert result.docx_path.is_file()
    assert result.pdf_path.read_bytes().startswith(b"%PDF-")
    assert db.query(ServiceTechnicalReport).count() == 1


def test_report_rejects_path_escape_and_preserves_existing_files(report_db, tmp_path):
    db, _ = report_db
    _completed_call(db)
    settings = service_report_service.ReportGenerationSettings(
        output_dir=tmp_path / "reports",
        template_path=Path("doc_templates/relatorio_tecnico_template.docx"),
        libreoffice_cmd="soffice",
        timezone="America/Recife",
    )
    with pytest.raises(service_report_service.ReportGenerationError):
        service_report_service.resolve_report_file("../../outside.pdf", settings.output_dir)
    assert db.query(ServiceTechnicalReport).count() == 0
