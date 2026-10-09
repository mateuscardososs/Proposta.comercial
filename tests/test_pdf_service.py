from __future__ import annotations

from pathlib import Path

import pytest

from app.services import pdf_service


def test_technical_report_converter_uses_networkless_local_docker_fallback(
    tmp_path: Path, monkeypatch
):
    document = tmp_path / "report.docx"
    document.write_bytes(b"synthetic docx")
    expected_pdf = tmp_path / "report.pdf"
    calls: list[list[str]] = []

    monkeypatch.setattr(pdf_service.shutil, "which", lambda command: None)

    def fake_run(command, *, check, capture_output, text, timeout):
        assert check is True
        assert capture_output is True
        assert text is True
        assert timeout == 120
        calls.append(command)
        if command[0] != "docker":
            raise FileNotFoundError(command[0])
        expected_pdf.write_bytes(b"%PDF-1.4 synthetic report")

    monkeypatch.setattr(pdf_service.subprocess, "run", fake_run)

    result = pdf_service.convert_docx_to_pdf(
        document,
        expected_pdf,
        libreoffice_cmd="soffice",
        docker_image="local-doc-converter:test",
    )

    assert result == expected_pdf
    assert result.read_bytes().startswith(b"%PDF-")
    docker_call = calls[-1]
    assert docker_call[0:3] == ["docker", "run", "--rm"]
    assert "--network" in docker_call and docker_call[docker_call.index("--network") + 1] == "none"
    assert "--read-only" in docker_call
    assert docker_call[docker_call.index("--entrypoint") + 1] == "/usr/bin/soffice"
    assert docker_call[-1] == "/work/report.docx"


def test_missing_host_and_docker_converters_fail_without_claiming_pdf(
    tmp_path: Path, monkeypatch
):
    document = tmp_path / "report.docx"
    document.write_bytes(b"synthetic docx")
    monkeypatch.setattr(pdf_service.shutil, "which", lambda command: None)

    with pytest.raises(RuntimeError, match="LibreOffice command not found"):
        pdf_service.convert_docx_to_pdf(document, tmp_path / "report.pdf")

    assert not (tmp_path / "report.pdf").exists()
