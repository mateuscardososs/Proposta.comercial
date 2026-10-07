from __future__ import annotations

from datetime import date
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db import Base, get_db, ensure_service_history_guards_for_engine
from app.main import app
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


@pytest.fixture
def service_report_app(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'service-report-routes.sqlite3'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    ensure_service_history_guards_for_engine(engine)

    def override_db():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    output_dir = tmp_path / "generated"
    settings = type("TestSettings", (), {
        "output_dir": output_dir,
        "template_doc_path": Path(__file__).resolve().parents[1] / "doc_templates" / "proposta_template.docx",
        "technical_report_template_path": Path(__file__).resolve().parents[1] / "doc_templates" / "relatorio_tecnico_template.docx",
        "libreoffice_cmd": "soffice",
        "assistant_timezone": "America/Recife",
    })()
    monkeypatch.setattr("app.routers.services.get_settings", lambda: settings)
    with Session(engine, expire_on_commit=False) as db:
        client = Client(
            razao_social="Cliente Sintético de Rota",
            cnpj="11.111.111/0001-11",
            telefone="(11) 1111-1111",
            endereco_linha1="Av. de Teste, 11",
            cidade_uf="Recife/PE",
        )
        conversation = AssistantConversation()
        db.add_all([client, conversation])
        db.flush()
        action = AssistantAction(
            conversation_id=conversation.id,
            request_id="route-service-source",
            confirmation_token_hash="b" * 64,
            action_type="register_service_event",
            status="executed",
        )
        db.add(action)
        db.flush()
        call = ServiceCall(
            client_id=client.id,
            summary="Verificação da balança",
            opened_on=date(2026, 10, 1),
            execution_status="completed",
        )
        db.add(call)
        db.flush()
        for step in ("report", "proposal", "proposal_sent", "invoice", "receipt"):
            db.add(ServiceWorkflowStep(service_call_id=call.id, step_type=step))
        db.add(ServiceEvent(
            service_call_id=call.id,
            assistant_action_id=action.id,
            conversation_id=conversation.id,
            event_type="execution_completed",
            occurred_on=date(2026, 10, 2),
            description=(
                "Equipamento: Balança sintética\n"
                "Problema relatado: Desvio de leitura\n"
                "Análise: Evidência registrada\n"
                "Serviço executado: Ajuste registrado"
            ),
        ))
        db.commit()
        call_id = call.id
    try:
        yield TestClient(app), engine, call_id, output_dir
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_service_page_previews_then_confirms_report_once(service_report_app, monkeypatch):
    client, engine, call_id, output_dir = service_report_app
    pdf_conversions = []

    def fake_pdf(docx_path: Path, pdf_path: Path, libreoffice_cmd: str, *, docker_image: str = "") -> Path:
        del libreoffice_cmd
        del docker_image
        pdf_conversions.append(docx_path.name)
        pdf_path.write_bytes(b"%PDF-1.4 synthetic test artifact")
        return pdf_path

    monkeypatch.setattr(service_report_service.pdf_service, "convert_docx_to_pdf", fake_pdf)

    detail = client.get(f"/web/services/{call_id}")
    assert detail.status_code == 200
    assert f"/web/services/{call_id}/relatorio/previa" in detail.text
    preview = client.get(f"/web/services/{call_id}/relatorio/previa")
    assert preview.status_code == 200
    assert "Desvio de leitura" in preview.text
    assert "não será preenchido por inferência" in preview.text
    with Session(engine) as db:
        assert db.query(ServiceTechnicalReport).count() == 0
        assert db.query(ServiceEvent).count() == 1
        assert db.query(AssistantAction).count() == 1

    idempotency_key = re.search(r'name="idempotency_key" value="([^"]+)"', preview.text).group(1)
    source_fingerprint = re.search(r'name="source_fingerprint" value="([^"]+)"', preview.text).group(1)
    endpoint = f"/web/services/{call_id}/relatorio/gerar"
    fields = {
        "idempotency_key": idempotency_key,
        "source_fingerprint": source_fingerprint,
        "client_name": "Cliente Sintético de Rota",
        "client_cnpj": "11.111.111/0001-11",
        "client_phone": "(11) 1111-1111",
        "client_address": "Av. de Teste, 11 · Recife/PE",
        "equipment": "Balança sintética",
        "completion_date": "2026-10-02",
        "reported_problem": "Desvio de leitura",
        "analysis": "Evidência registrada",
        "work_performed": "Ajuste revisado pela pessoa",
        "verification_result": "Revisão humana informada",
    }
    unconfirmed = client.post(endpoint, data=fields, follow_redirects=False)
    assert unconfirmed.status_code == 200
    assert "autorizo gerar DOCX e PDF" in unconfirmed.text
    with Session(engine) as db:
        assert db.query(ServiceTechnicalReport).count() == 0

    confirmation = {**fields, "confirmed": "yes"}
    generated = client.post(endpoint, data=confirmation, follow_redirects=False)
    assert generated.status_code == 303
    repeated = client.post(endpoint, data=confirmation, follow_redirects=False)
    assert repeated.status_code == 303
    with Session(engine) as db:
        report = db.query(ServiceTechnicalReport).one()
        assert report.service_call_id == call_id
        assert report.fields_json["work_performed"] == "Ajuste revisado pela pessoa"
        assert db.query(ServiceEvent).count() == 2
        assert db.query(AssistantAction).count() == 2
        report_id = report.id
        step = db.query(ServiceWorkflowStep).filter_by(service_call_id=call_id, step_type="report").one()
        assert step.status == "completed"

    assert len(pdf_conversions) == 1
    assert client.get(f"/web/services/relatorios/{report_id}/docx").status_code == 200
    assert client.get(f"/web/services/relatorios/{report_id}/pdf").content.startswith(b"%PDF-")


def test_incomplete_service_cannot_open_report_preview(service_report_app):
    client, engine, call_id, _ = service_report_app
    with Session(engine) as db:
        call = db.get(ServiceCall, call_id)
        call.execution_status = "in_progress"
        db.commit()
    response = client.get(f"/web/services/{call_id}/relatorio/previa")
    assert response.status_code == 409
    assert "após a conclusão explícita" in response.text
