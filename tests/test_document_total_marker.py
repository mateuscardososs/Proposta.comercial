from __future__ import annotations

import shutil
import subprocess
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree

import pytest

from app.config import get_settings
from app.models import Client, Proposal, User
from app.services import document_service, proposal_file_service, proposal_service


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": WORD_NS}
TAG_ATTRIBUTE = f"{{{WORD_NS}}}val"
TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "doc_templates" / "proposta_template.docx"


def _count_total_tags(path: Path) -> int:
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    return sum(
        1
        for tag in root.findall(".//w:sdt/w:sdtPr/w:tag", NS)
        if tag.get(TAG_ATTRIBUTE) == proposal_file_service.DOCX_TOTAL_TAG
    )


def _proposal_with_details(db) -> Proposal:
    client = Client(razao_social="Cliente Marcador")
    user = User(nome="Responsável Marcador", email="marcador@example.com", senha_hash="hash")
    db.add_all([client, user])
    db.flush()
    proposal = Proposal(
        numero=900,
        revisao="00",
        data_geracao=date(2026, 8, 31),
        client_id=client.id,
        user_id=user.id,
        valor_total=Decimal("4321.09"),
    )
    db.add(proposal)
    db.commit()
    loaded = proposal_service.get_proposal_with_details(db, proposal.id)
    assert loaded is not None
    return loaded


def test_source_template_contains_exactly_one_total_marker():
    assert _count_total_tags(TEMPLATE_PATH) == 1


def test_total_marker_survives_docxtpl_render(db, tmp_path):
    proposal = _proposal_with_details(db)
    rendered = tmp_path / "rendered.docx"

    document_service.render_docx_from_template(
        TEMPLATE_PATH,
        document_service.build_template_context(proposal),
        rendered,
    )
    analysis = proposal_file_service.analyze_word_reupload(
        rendered.name,
        rendered.read_bytes(),
    )

    assert analysis.marker_found is True
    assert analysis.valor_total == proposal.valor_total


def test_total_marker_survives_libreoffice_round_trip(db, tmp_path):
    settings = get_settings()
    executable = shutil.which(settings.libreoffice_cmd)
    if not executable:
        pytest.skip("LibreOffice não está disponível neste ambiente.")
    proposal = _proposal_with_details(db)
    source_dir = tmp_path / "source"
    saved_dir = tmp_path / "saved"
    source_dir.mkdir()
    saved_dir.mkdir()
    rendered = source_dir / "roundtrip.docx"
    document_service.render_docx_from_template(
        TEMPLATE_PATH,
        document_service.build_template_context(proposal),
        rendered,
    )

    completed = subprocess.run(
        [
            executable,
            "--headless",
            "--convert-to",
            "docx",
            "--outdir",
            str(saved_dir),
            str(rendered),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    round_tripped = saved_dir / rendered.name
    analysis = proposal_file_service.analyze_word_reupload(
        round_tripped.name,
        round_tripped.read_bytes(),
    )
    assert analysis.marker_found is True
    assert analysis.valor_total == proposal.valor_total
