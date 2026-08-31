from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import SessionLocal
from app.main import app
from app.models import Client, Proposal, User
from app.routers import proposal_files as proposal_files_router
from app.services import proposal_file_service


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CONTENT_TYPES = b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
</Types>
"""


def _docx(body: str) -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{WORD_NS}"><w:body>{body}</w:body></w:document>'
    ).encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("word/document.xml", document)
    return stream.getvalue()


def _marked_docx(value: str = "R$ 1.234,56") -> bytes:
    return _docx(
        "<w:sdt><w:sdtPr><w:tag w:val=\"AD_VALOR_TOTAL\"/></w:sdtPr>"
        f"<w:sdtContent><w:r><w:t>{value}</w:t></w:r></w:sdtContent></w:sdt>"
    )


def _source_proposal(db, *, relative_path: str = "fontes/fonte.docx") -> Proposal:
    client = Client(razao_social="Cliente Word")
    user = User(nome="Responsável Word", email="word@example.com", senha_hash="hash")
    db.add_all([client, user])
    db.flush()
    proposal = Proposal(
        numero=77,
        revisao="00",
        data_geracao=date(2026, 8, 1),
        client_id=client.id,
        user_id=user.id,
        valor_total=Decimal("1234.56"),
        docx_path=relative_path,
    )
    db.add(proposal)
    db.commit()
    return proposal


def _write_source(proposal: Proposal, payload: bytes) -> Path:
    path = proposal_files_router.settings.output_dir / proposal.docx_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _fake_converter(*, docx_path, pdf_path, libreoffice_cmd):
    del docx_path, libreoffice_cmd
    pdf_path.write_bytes(b"%PDF-generated")
    return pdf_path


@pytest.fixture(autouse=True)
def isolated_output(tmp_path, monkeypatch):
    settings = Settings(
        output_dir=tmp_path / "output",
        template_doc_path=tmp_path / "template.docx",
        libreoffice_cmd="soffice-test",
    )
    settings.output_dir.mkdir(parents=True)
    monkeypatch.setattr(proposal_files_router, "settings", settings)
    return settings


def test_word_preview_returns_marker_without_persisting(db):
    payload = _marked_docx()
    source = _source_proposal(db)
    source_path = _write_source(source, payload)
    proposal_count = db.query(Proposal).count()
    files_before = sorted(
        path for path in proposal_files_router.settings.output_dir.rglob("*.*")
    )

    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/proposal-files/{source.id}/word-preview",
                files={"file": ("editado.docx", payload, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )

        assert response.status_code == 200
        assert response.json() == {
            "filename": "editado.docx",
            "valor_total": "1234.56",
            "marker_found": True,
            "warnings": [],
        }
        db.expire_all()
        assert db.query(Proposal).count() == proposal_count
        assert sorted(
            path for path in proposal_files_router.settings.output_dir.rglob("*.*")
        ) == files_before
    finally:
        source_path.unlink(missing_ok=True)


def test_external_preview_returns_suggestions_without_persisting(db):
    client_record = Client(razao_social="Cliente Externo Rota")
    db.add(client_record)
    db.commit()
    payload = _docx(
        "<w:p><w:r><w:t>Cliente Externo Rota</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Valor total: R$ 9.876,00</w:t></w:r></w:p>"
    )
    proposal_count = db.query(Proposal).count()

    with TestClient(app) as client:
        response = client.post(
            "/api/proposal-files/upload-externo/preview",
            files={"file": ("externa.docx", payload, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "filename": "externa.docx",
        "file_type": "docx",
        "suggested_client_id": client_record.id,
        "suggested_client_name": "Cliente Externo Rota",
        "client_confidence": 1.0,
        "suggested_valor_total": "9876.00",
        "warnings": [],
    }
    db.expire_all()
    assert db.query(Proposal).count() == proposal_count


def test_preview_rejects_upload_over_limit(db, monkeypatch):
    source = _source_proposal(db)
    payload = _marked_docx()
    source_path = _write_source(source, payload)
    monkeypatch.setattr(proposal_file_service, "MAX_UPLOAD_BYTES", len(payload) - 1)

    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/proposal-files/{source.id}/word-preview",
                files={"file": ("editado.docx", payload)},
            )
        assert response.status_code == 422
        assert "20 MB" in response.json()["detail"]
    finally:
        source_path.unlink(missing_ok=True)


def test_download_word_is_attachment(db):
    source = _source_proposal(db)
    source_path = _write_source(source, _marked_docx())

    try:
        with TestClient(app) as client:
            response = client.get(f"/web/proposals/{source.id}/baixar-word")
        assert response.status_code == 200
        assert response.content == source_path.read_bytes()
        assert "attachment" in response.headers["content-disposition"]
        assert source_path.name in response.headers["content-disposition"]
    finally:
        source_path.unlink(missing_ok=True)


@pytest.mark.parametrize("case", ["missing_proposal", "empty_path", "missing_file", "outside"])
def test_download_word_returns_404_for_invalid_source(db, tmp_path, case):
    if case == "missing_proposal":
        proposal_id = 99999
    else:
        relative_path = {
            "empty_path": "",
            "missing_file": "fontes/inexistente.docx",
            "outside": "../../fora.docx",
        }[case]
        proposal_id = _source_proposal(db, relative_path=relative_path).id

    with TestClient(app) as client:
        response = client.get(f"/web/proposals/{proposal_id}/baixar-word")

    assert response.status_code == 404
    assert "caminho" not in response.text.lower()


def test_confirm_word_reupload_creates_revision_and_redirects(db, monkeypatch):
    payload = _marked_docx("R$ 4.500,00")
    source = _source_proposal(db)
    source_path = _write_source(source, payload)
    monkeypatch.setattr(proposal_file_service.pdf_service, "convert_docx_to_pdf", _fake_converter)

    try:
        with TestClient(app) as client:
            response = client.post(
                f"/web/proposals/{source.id}/reenviar-word",
                files={"file": ("editado.docx", payload)},
                data={"valor_total": "4.500,00"},
                follow_redirects=False,
            )
        assert response.status_code == 303
        created_id = int(response.headers["location"].rsplit("/", 1)[1])
        with SessionLocal() as check_db:
            created = check_db.get(Proposal, created_id)
            assert created is not None
            assert (created.numero, created.revisao) == (77, "01")
            assert created.valor_total == Decimal("4500.00")
    finally:
        source_path.unlink(missing_ok=True)


def test_confirm_external_pdf_creates_proposal_and_redirects(db):
    client_record = Client(razao_social="Cliente Confirmação")
    user = User(nome="Responsável Confirmação", email="confirma@example.com", senha_hash="hash")
    db.add_all([client_record, user])
    db.commit()

    with TestClient(app) as client:
        response = client.post(
            "/web/proposals/upload-externo",
            files={"file": ("externa.pdf", b"%PDF-original", "application/pdf")},
            data={
                "client_id": str(client_record.id),
                "user_id": str(user.id),
                "data_geracao": "2026-08-31",
                "valor_total": "2.345,67",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    created_id = int(response.headers["location"].rsplit("/", 1)[1])
    with SessionLocal() as check_db:
        created = check_db.get(Proposal, created_id)
        assert created is not None
        assert created.origem == "upload_externo"
        assert created.valor_total == Decimal("2345.67")


def test_confirm_external_rejects_invalid_fields_without_persisting(db):
    with TestClient(app) as client:
        response = client.post(
            "/web/proposals/upload-externo",
            files={"file": ("externa.pdf", b"%PDF-original")},
            data={
                "client_id": "invalido",
                "user_id": "1",
                "data_geracao": "31/08/2026",
                "valor_total": "valor",
            },
            follow_redirects=False,
        )

    assert response.status_code == 422
    assert "Dados de cliente inválidos" in response.json()["detail"]
    assert "invalid literal" not in response.text
    with SessionLocal() as check_db:
        assert check_db.query(Proposal).count() == 0


def test_word_reupload_page_uses_confirmation_flow(db):
    source = _source_proposal(db)
    source_path = _write_source(source, _marked_docx())

    try:
        with TestClient(app) as client:
            response = client.get(f"/web/proposals/{source.id}/reenviar-word")
        assert response.status_code == 200
        assert "Reenviar Word editado" in response.text
        assert "Analisar arquivo" in response.text
        assert 'id="confirmWordButton"' in response.text
        assert 'id="confirmWordButton" class="btn btn-primary" type="submit" disabled' in response.text
        assert "textContent" in response.text
    finally:
        source_path.unlink(missing_ok=True)


def test_word_reupload_page_requires_available_docx(db):
    without_file = _source_proposal(db, relative_path="")

    with TestClient(app) as client:
        response = client.get(f"/web/proposals/{without_file.id}/reenviar-word")

    assert response.status_code == 409
    assert "Word" in response.text


def test_external_upload_page_lists_clients_only_active_users_and_today(db):
    client_record = Client(razao_social="Cliente Disponível")
    active = User(nome="Usuário Ativo", email="ativo-upload@example.com", senha_hash="hash")
    inactive = User(
        nome="Usuário Inativo Upload",
        email="inativo-upload@example.com",
        senha_hash="hash",
        ativo=False,
    )
    db.add_all([client_record, active, inactive])
    db.commit()

    with TestClient(app) as client:
        response = client.get("/web/proposals/upload-externo")

    assert response.status_code == 200
    assert "Upload externo de proposta" in response.text
    assert "Confirmar e registrar proposta" in response.text
    assert "Cliente Disponível" in response.text
    assert "Usuário Ativo" in response.text
    assert "Usuário Inativo Upload" not in response.text
    assert date.today().isoformat() in response.text
    assert 'id="confirmExternalButton"' in response.text
    assert "disabled" in response.text
    assert "textContent" in response.text


def test_listing_and_details_distinguish_proposal_origins(db):
    client_record = Client(razao_social="Cliente Origens")
    user = User(nome="Responsável Origens", email="origens-route@example.com", senha_hash="hash")
    db.add_all([client_record, user])
    db.flush()
    proposals = []
    for numero, origem in enumerate(
        ("sistema", "reupload_editado", "upload_externo"),
        start=100,
    ):
        proposal = Proposal(
            numero=numero,
            revisao="00",
            data_geracao=date(2026, 8, 31),
            client_id=client_record.id,
            user_id=user.id,
            origem=origem,
            valor_total=Decimal("100.00"),
        )
        db.add(proposal)
        proposals.append(proposal)
    db.commit()

    with TestClient(app) as client:
        listing = client.get("/web/proposals")
        structured_detail = client.get(f"/web/proposals/{proposals[0].id}")
        documental_detail = client.get(f"/web/proposals/{proposals[2].id}")

    assert listing.status_code == 200
    assert "Sistema" in listing.text
    assert "Word reenviado" in listing.text
    assert "Upload externo" in listing.text
    assert "Proposta documental" in documental_detail.text
    assert "Itens e servicos" not in documental_detail.text
    assert "Itens e servicos" in structured_detail.text
