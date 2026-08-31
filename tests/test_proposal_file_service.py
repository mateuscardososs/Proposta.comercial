from __future__ import annotations

import io
import struct
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.models import Client, Proposal, ProposalItem, ProposalScheduleItem, User
from app.services import pdf_import_service, proposal_file_service


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CONTENT_TYPES = b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
</Types>
"""


def _document_xml(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{WORD_NS}"><w:body>{body}</w:body></w:document>'
    ).encode()


def build_docx(
    body: str = "<w:p><w:r><w:t>Cliente Exemplo Ltda</w:t></w:r></w:p>",
    *,
    extra_entries: dict[str, bytes] | None = None,
) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("word/document.xml", _document_xml(body))
        for name, content in (extra_entries or {}).items():
            archive.writestr(name, content)
    return stream.getvalue()


def _mark_first_zip_entry_encrypted(payload: bytes) -> bytes:
    data = bytearray(payload)
    local = data.find(b"PK\x03\x04")
    central = data.find(b"PK\x01\x02")
    assert local >= 0 and central >= 0
    local_flags = struct.unpack_from("<H", data, local + 6)[0] | 0x1
    central_flags = struct.unpack_from("<H", data, central + 8)[0] | 0x1
    struct.pack_into("<H", data, local + 6, local_flags)
    struct.pack_into("<H", data, central + 8, central_flags)
    return bytes(data)


@pytest.mark.parametrize(
    ("filename", "payload", "allowed"),
    [
        ("arquivo.doc", b"conteudo", frozenset({".docx"})),
        ("arquivo.docm", b"conteudo", frozenset({".docx"})),
        ("arquivo.docx", b"nao-e-zip", frozenset({".docx"})),
        ("arquivo.pdf", b"nao-e-pdf", frozenset({".pdf"})),
        ("arquivo.docx", b"", frozenset({".docx"})),
    ],
)
def test_validate_upload_rejects_invalid_basic_inputs(filename, payload, allowed):
    with pytest.raises(proposal_file_service.ProposalFileValidationError):
        proposal_file_service.validate_upload(filename, payload, allowed)


def test_validate_upload_rejects_payload_over_20_mb(monkeypatch):
    payload = build_docx()
    monkeypatch.setattr(proposal_file_service, "MAX_UPLOAD_BYTES", len(payload) - 1)

    with pytest.raises(proposal_file_service.ProposalFileValidationError, match="20 MB"):
        proposal_file_service.validate_upload(
            "arquivo.docx",
            payload,
            frozenset({".docx"}),
        )


@pytest.mark.parametrize(
    "extra_entries",
    [
        {"../escape.xml": b"x"},
        {"/absolute.xml": b"x"},
        {"word/vbaProject.bin": b"macro"},
    ],
)
def test_validate_upload_rejects_unsafe_docx_entries(extra_entries):
    with pytest.raises(proposal_file_service.ProposalFileValidationError):
        proposal_file_service.validate_upload(
            "arquivo.docx",
            build_docx(extra_entries=extra_entries),
            frozenset({".docx"}),
        )


def test_validate_upload_rejects_encrypted_docx():
    payload = _mark_first_zip_entry_encrypted(build_docx())

    with pytest.raises(proposal_file_service.ProposalFileValidationError, match="criptografado"):
        proposal_file_service.validate_upload(
            "arquivo.docx",
            payload,
            frozenset({".docx"}),
        )


def test_validate_upload_rejects_too_many_entries(monkeypatch):
    monkeypatch.setattr(proposal_file_service, "DOCX_MAX_ENTRIES", 2)

    with pytest.raises(proposal_file_service.ProposalFileValidationError, match="entradas"):
        proposal_file_service.validate_upload(
            "arquivo.docx",
            build_docx(extra_entries={"word/header1.xml": b"<x/>"}),
            frozenset({".docx"}),
        )


def test_validate_upload_rejects_excessive_uncompressed_size(monkeypatch):
    payload = build_docx()
    monkeypatch.setattr(proposal_file_service, "DOCX_MAX_UNCOMPRESSED_BYTES", 10)

    with pytest.raises(proposal_file_service.ProposalFileValidationError, match="descompactado"):
        proposal_file_service.validate_upload(
            "arquivo.docx",
            payload,
            frozenset({".docx"}),
        )


def test_validate_upload_requires_ooxml_entries():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("word/document.xml", _document_xml(""))

    with pytest.raises(proposal_file_service.ProposalFileValidationError, match="OOXML"):
        proposal_file_service.validate_upload(
            "arquivo.docx",
            stream.getvalue(),
            frozenset({".docx"}),
        )


def test_extract_docx_text_reads_document_tables_headers_and_footers():
    payload = build_docx(
        """
        <w:p><w:r><w:t>Cliente Exemplo Ltda</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Serviço em tabela</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
        """,
        extra_entries={
            "word/header1.xml": (
                f'<w:hdr xmlns:w="{WORD_NS}"><w:p><w:r><w:t>Cabeçalho comercial</w:t></w:r></w:p></w:hdr>'
            ).encode(),
            "word/footer1.xml": (
                f'<w:ftr xmlns:w="{WORD_NS}"><w:p><w:r><w:t>Rodapé comercial</w:t></w:r></w:p></w:ftr>'
            ).encode(),
        },
    )

    text = proposal_file_service.extract_docx_text(payload)

    assert "Cliente Exemplo Ltda" in text
    assert "Serviço em tabela" in text
    assert "Cabeçalho comercial" in text
    assert "Rodapé comercial" in text


def _marked_total(value_runs: str) -> str:
    return f"""
    <w:sdt>
      <w:sdtPr><w:tag w:val="AD_VALOR_TOTAL"/></w:sdtPr>
      <w:sdtContent>{value_runs}</w:sdtContent>
    </w:sdt>
    """


def test_analyze_word_reupload_reads_marker_split_across_text_nodes():
    payload = build_docx(
        _marked_total(
            "<w:r><w:t>R$ 1.</w:t></w:r>"
            "<w:r><w:t>234,56</w:t></w:r>"
        )
    )

    analysis = proposal_file_service.analyze_word_reupload("editado.docx", payload)

    assert analysis.valor_total == Decimal("1234.56")
    assert analysis.marker_found is True
    assert analysis.warnings == ()


@pytest.mark.parametrize(
    "body",
    [
        "<w:p><w:r><w:t>R$ 100,00</w:t></w:r></w:p>",
        _marked_total("<w:r><w:t></w:t></w:r>"),
        _marked_total("<w:r><w:t>valor inválido</w:t></w:r>"),
        _marked_total("<w:r><w:t>R$ 10,00</w:t></w:r>")
        + _marked_total("<w:r><w:t>R$ 20,00</w:t></w:r>"),
    ],
)
def test_analyze_word_reupload_requires_manual_value_for_unusable_marker(body):
    analysis = proposal_file_service.analyze_word_reupload(
        "antigo.docx",
        build_docx(body),
    )

    assert analysis.valor_total is None
    assert analysis.marker_found is False
    assert "manualmente" in analysis.warnings[0]


def test_suggest_client_prefers_normalized_exact_name(db):
    client = Client(razao_social="Companhia Siderúrgica Nacional")
    db.add(client)
    db.commit()

    suggestion = proposal_file_service.suggest_client(
        "CLIENTE: Companhia Siderurgica Nacional",
        [client],
    )

    assert suggestion.client_id == client.id
    assert suggestion.client_name == client.razao_social
    assert suggestion.confidence == 1.0


def test_suggest_client_accepts_clear_approximate_match(db):
    expected = Client(razao_social="Companhia Siderúrgica Nacional")
    unrelated = Client(razao_social="Metalúrgica do Vale Ltda")
    db.add_all([expected, unrelated])
    db.commit()

    suggestion = proposal_file_service.suggest_client(
        "Companhia Siderurgica Nacionau",
        [expected, unrelated],
    )

    assert suggestion.client_id == expected.id
    assert 0.82 <= suggestion.confidence <= 1.0


def test_suggest_client_returns_none_for_ambiguous_or_unrelated_text(db):
    clients = [
        Client(razao_social="Metalúrgica Horizonte Ltda"),
        Client(razao_social="Metalúrgica Horizonte Serviços Ltda"),
    ]
    db.add_all(clients)
    db.commit()

    assert proposal_file_service.suggest_client("Metalurgica Horizonte", clients) is None
    assert proposal_file_service.suggest_client("apelido sem relação", clients) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Valor total: R$ 1.234,56", Decimal("1234.56")),
        ("TOTAL DA PROPOSTA\nR$ 9.876,00", Decimal("9876.00")),
        ("Subtotal R$ 100,00\nValor total: R$ 250,00", Decimal("250.00")),
        ("Valor total R$ 100,00 e R$ 200,00", None),
        ("Preço R$ 100,00", None),
    ],
)
def test_suggest_total_uses_only_clear_total_labels(text, expected):
    assert proposal_file_service.suggest_total(text) == expected


def test_analyze_external_docx_suggests_client_and_total(db):
    client = Client(razao_social="Cliente Exemplo Ltda")
    db.add(client)
    db.commit()
    payload = build_docx(
        """
        <w:p><w:r><w:t>Cliente Exemplo Ltda</w:t></w:r></w:p>
        <w:p><w:r><w:t>Valor total: R$ 4.500,00</w:t></w:r></w:p>
        """
    )

    analysis = proposal_file_service.analyze_external_upload(
        db,
        "externa.docx",
        payload,
    )

    assert analysis.file_type == "docx"
    assert analysis.suggested_client.client_id == client.id
    assert analysis.suggested_valor_total == Decimal("4500.00")
    assert analysis.warnings == ()


def test_analyze_external_scanned_pdf_uses_manual_confirmation(db, monkeypatch):
    def no_text(_):
        raise pdf_import_service.PDFNoTextError("PDF sem texto extraível.")

    monkeypatch.setattr(pdf_import_service, "extract_text_from_pdf", no_text)

    analysis = proposal_file_service.analyze_external_upload(
        db,
        "scanned.pdf",
        b"%PDF-scanned",
    )

    assert analysis.file_type == "pdf"
    assert analysis.suggested_client is None
    assert analysis.suggested_valor_total is None
    assert "parece escaneado" in analysis.warnings[0]


def test_analyze_external_invalid_pdf_hides_parser_details(db, monkeypatch):
    def invalid_pdf(_):
        raise pdf_import_service.PDFImportError(
            "pdfplumber error: caminho/interno | pymupdf error: detalhe técnico"
        )

    monkeypatch.setattr(pdf_import_service, "extract_text_from_pdf", invalid_pdf)

    with pytest.raises(
        proposal_file_service.ProposalFileValidationError,
        match="Não foi possível ler o PDF enviado",
    ) as error:
        proposal_file_service.analyze_external_upload(
            db,
            "corrompido.pdf",
            b"%PDF-corrompido",
        )

    assert "caminho/interno" not in str(error.value)


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(
        output_dir=tmp_path,
        template_doc_path=tmp_path / "template.docx",
        libreoffice_cmd="soffice-test",
    )


def _make_document_source(db, tmp_path: Path) -> tuple[Proposal, bytes]:
    client = Client(razao_social="Cliente Documento")
    user = User(
        nome="Responsável Documento",
        email="documento@example.com",
        senha_hash="hash",
    )
    db.add_all([client, user])
    db.flush()
    payload = build_docx(
        _marked_total("<w:r><w:t>R$ 5.000,00</w:t></w:r>")
    )
    source_path = tmp_path / "originais" / "fonte.docx"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(payload)
    source = Proposal(
        numero=42,
        revisao="00",
        data_geracao=date(2026, 8, 1),
        client_id=client.id,
        user_id=user.id,
        valor_total=Decimal("5000.00"),
        docx_path="originais/fonte.docx",
        pdf_path="originais/fonte.pdf",
    )
    db.add(source)
    db.flush()
    db.add(
        ProposalItem(
            proposal_id=source.id,
            ordem=1,
            descricao="Item anterior",
            unidade="UN",
            qtd=Decimal("1.00"),
            valor_unit=Decimal("5000.00"),
            total=Decimal("5000.00"),
        )
    )
    db.add(
        ProposalScheduleItem(
            proposal_id=source.id,
            ordem=1,
            dia_label="Dia 1",
            descricao="Etapa anterior",
            horas_servico="8",
        )
    )
    db.commit()
    return source, payload


def _fake_converter(*, docx_path, pdf_path, libreoffice_cmd):
    del docx_path, libreoffice_cmd
    pdf_path.write_bytes(b"%PDF-generated")
    return pdf_path


def test_copy_exclusive_removes_partial_destination_on_copy_failure(tmp_path, monkeypatch):
    source = tmp_path / "source.docx"
    destination = tmp_path / "destination.docx"
    source.write_bytes(b"complete")

    def partial_copy(src, dst):
        del src
        dst.write(b"partial")
        raise OSError("disco indisponível")

    monkeypatch.setattr(proposal_file_service.shutil, "copyfileobj", partial_copy)

    with pytest.raises(OSError, match="disco"):
        proposal_file_service._copy_exclusive(source, destination)

    assert not destination.exists()


def test_create_word_revision_preserves_source_and_creates_official_files(
    db,
    tmp_path,
    monkeypatch,
):
    source, payload = _make_document_source(db, tmp_path)
    monkeypatch.setattr(
        proposal_file_service.pdf_service,
        "convert_docx_to_pdf",
        _fake_converter,
    )

    created = proposal_file_service.create_word_revision(
        db,
        source.id,
        "editado.docx",
        payload,
        Decimal("4500.00"),
        _test_settings(tmp_path),
    )

    assert (created.numero, created.revisao) == (42, "01")
    assert created.origem == "reupload_editado"
    assert created.client_id == source.client_id
    assert created.user_id == source.user_id
    assert created.valor_total == Decimal("4500.00")
    assert created.items == []
    assert created.schedule_items == []
    assert (tmp_path / created.docx_path).read_bytes() == payload
    assert (tmp_path / created.pdf_path).read_bytes() == b"%PDF-generated"
    db.refresh(source)
    assert source.docx_path == "originais/fonte.docx"
    assert (tmp_path / source.docx_path).read_bytes() == payload


def test_create_external_docx_uses_confirmed_fields_and_empty_structured_rows(
    db,
    tmp_path,
    monkeypatch,
):
    client = Client(razao_social="Cliente Externo")
    user = User(
        nome="Responsável Externo",
        email="externo@example.com",
        senha_hash="hash",
    )
    db.add_all([client, user])
    db.commit()
    payload = build_docx()
    monkeypatch.setattr(
        proposal_file_service.pdf_service,
        "convert_docx_to_pdf",
        _fake_converter,
    )

    created = proposal_file_service.create_external_proposal(
        db,
        "externa.docx",
        payload,
        client.id,
        user.id,
        date(2026, 8, 31),
        Decimal("789.10"),
        _test_settings(tmp_path),
    )

    assert created.revisao == "00"
    assert created.origem == "upload_externo"
    assert created.data_geracao == date(2026, 8, 31)
    assert created.valor_total == Decimal("789.10")
    assert created.items == []
    assert created.schedule_items == []
    assert (tmp_path / created.docx_path).read_bytes() == payload
    assert (tmp_path / created.pdf_path).read_bytes() == b"%PDF-generated"


def test_create_external_pdf_preserves_original_without_docx(db, tmp_path):
    client = Client(razao_social="Cliente PDF")
    user = User(
        nome="Responsável PDF",
        email="pdf@example.com",
        senha_hash="hash",
    )
    db.add_all([client, user])
    db.commit()
    payload = b"%PDF-original"

    created = proposal_file_service.create_external_proposal(
        db,
        "externa.pdf",
        payload,
        client.id,
        user.id,
        date(2026, 8, 31),
        Decimal("100.00"),
        _test_settings(tmp_path),
    )

    assert created.origem == "upload_externo"
    assert created.docx_path == ""
    assert (tmp_path / created.pdf_path).read_bytes() == payload


def test_documental_creation_validates_total_and_references(db, tmp_path):
    client = Client(razao_social="Cliente Validação")
    inactive_user = User(
        nome="Usuário Inativo",
        email="inativo@example.com",
        senha_hash="hash",
        ativo=False,
    )
    db.add_all([client, inactive_user])
    db.commit()

    with pytest.raises(proposal_file_service.ProposalFileValidationError):
        proposal_file_service.create_external_proposal(
            db,
            "externa.pdf",
            b"%PDF-original",
            client.id,
            inactive_user.id,
            date(2026, 8, 31),
            Decimal("100.00"),
            _test_settings(tmp_path),
        )
    with pytest.raises(proposal_file_service.ProposalFileValidationError):
        proposal_file_service.create_external_proposal(
            db,
            "externa.pdf",
            b"%PDF-original",
            99999,
            inactive_user.id,
            date(2026, 8, 31),
            Decimal("-0.01"),
            _test_settings(tmp_path),
        )


def test_word_revision_rolls_back_database_and_files_when_conversion_fails(
    db,
    tmp_path,
    monkeypatch,
):
    source, payload = _make_document_source(db, tmp_path)

    def fail_conversion(**kwargs):
        del kwargs
        raise RuntimeError("LibreOffice indisponível")

    monkeypatch.setattr(
        proposal_file_service.pdf_service,
        "convert_docx_to_pdf",
        fail_conversion,
    )
    original_files = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*.*"))

    with pytest.raises(RuntimeError, match="LibreOffice"):
        proposal_file_service.create_word_revision(
            db,
            source.id,
            "editado.docx",
            payload,
            Decimal("4500.00"),
            _test_settings(tmp_path),
        )

    assert db.query(Proposal).count() == 1
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*.*")) == original_files


def test_word_revision_removes_first_promoted_file_when_second_promotion_fails(
    db,
    tmp_path,
    monkeypatch,
):
    source, payload = _make_document_source(db, tmp_path)
    monkeypatch.setattr(
        proposal_file_service.pdf_service,
        "convert_docx_to_pdf",
        _fake_converter,
    )
    original_copy = proposal_file_service._copy_exclusive
    copy_count = 0

    def fail_second_copy(source_path, destination_path):
        nonlocal copy_count
        copy_count += 1
        if copy_count == 2:
            raise RuntimeError("falha ao promover PDF")
        original_copy(source_path, destination_path)

    monkeypatch.setattr(proposal_file_service, "_copy_exclusive", fail_second_copy)
    original_files = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*.*"))

    with pytest.raises(RuntimeError, match="promover PDF"):
        proposal_file_service.create_word_revision(
            db,
            source.id,
            "editado.docx",
            payload,
            Decimal("4500.00"),
            _test_settings(tmp_path),
        )

    assert db.query(Proposal).count() == 1
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*.*")) == original_files


def test_external_creation_removes_promoted_file_when_database_commit_fails(
    db,
    tmp_path,
    monkeypatch,
):
    client = Client(razao_social="Cliente Concorrente")
    user = User(
        nome="Responsável Concorrente",
        email="concorrente@example.com",
        senha_hash="hash",
    )
    db.add_all([client, user])
    db.commit()
    original_commit = db.commit

    def fail_commit():
        raise IntegrityError("insert", {}, RuntimeError("concorrência"))

    monkeypatch.setattr(db, "commit", fail_commit)

    with pytest.raises(proposal_file_service.ProposalFileConflictError):
        proposal_file_service.create_external_proposal(
            db,
            "externa.pdf",
            b"%PDF-original",
            client.id,
            user.id,
            date(2026, 8, 31),
            Decimal("100.00"),
            _test_settings(tmp_path),
        )

    monkeypatch.setattr(db, "commit", original_commit)
    assert db.query(Proposal).count() == 0
    assert list(tmp_path.rglob("*.pdf")) == []
