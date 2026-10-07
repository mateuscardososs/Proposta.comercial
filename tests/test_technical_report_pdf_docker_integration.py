from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.services import pdf_service, technical_report_document_service


@pytest.mark.skipif(
    os.getenv("RUN_REPORT_DOCKER_CONVERTER_TEST") != "1",
    reason="explicit opt-in integration test; requires a local converter image",
)
def test_synthetic_technical_report_converts_to_pdf_in_local_isolated_container(tmp_path: Path):
    image = os.getenv("TECHNICAL_REPORT_PDF_CONVERTER_IMAGE", "").strip()
    assert image, "Set TECHNICAL_REPORT_PDF_CONVERTER_IMAGE to a local trusted image."
    docx_path = tmp_path / "synthetic-service-report.docx"
    pdf_path = tmp_path / "synthetic-service-report.pdf"
    technical_report_document_service.render_technical_report(
        template_path=Path("doc_templates/relatorio_tecnico_template.docx"),
        context={
            "CALL_ID": "SINTÉTICO-1",
            "SUMMARY": "Manutenção de equipamento sintético",
            "CLIENT": "Cliente Sintético",
            "CLIENT_CNPJ": "00.000.000/0001-00",
            "CLIENT_PHONE": "(00) 0000-0000",
            "CLIENT_ADDRESS": "Endereço de teste",
            "EQUIPMENT": "Balança sintética",
            "OPENED_ON": "01/10/2026",
            "COMPLETED_ON": "02/10/2026",
            "REPORT_DATE": "06/10/2026",
            "REPORTED_PROBLEM": "Leitura instável relatada no dado sintético",
            "ANALYSIS": "Análise sintética registrada",
            "WORK_PERFORMED": "Procedimento sintético registrado",
            "VERIFICATION_RESULT": "PENDENTE DE REVISÃO",
            "EVENT_TIMELINE": "02/10/2026 · Execução concluída: registro sintético",
            "MANUAL_OVERRIDES": "Nenhum",
        },
        missing_fields=["verification_result"],
        output_path=docx_path,
    )

    pdf_service.convert_docx_to_pdf(
        docx_path,
        pdf_path,
        libreoffice_cmd="__not_installed__",
        docker_image=image,
    )

    assert docx_path.is_file()
    assert pdf_path.read_bytes().startswith(b"%PDF-")
