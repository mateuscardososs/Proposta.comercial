from __future__ import annotations

import io
import zipfile

import pytest

from app.services import proposal_file_service as service


def package(body: str, extras: dict[str, bytes] | None = None) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("word/document.xml", xml(body))
        for name, content in (extras or {}).items():
            archive.writestr(name, content)
    return stream.getvalue()


def xml(body: str) -> bytes:
    return f'<w:document xmlns:w="{service.WORD_NS}">{body}</w:document>'.encode()


def paragraph(text: str, style: str = "") -> str:
    properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{properties}<w:r><w:t>{text}</w:t></w:r></w:p>"


def test_literal_order_tables_and_sections():
    payload = package(
        paragraph("Intro") + paragraph("Título", "Título2") + paragraph("Corpo")
        + "<w:tbl><w:tr><w:tc>" + paragraph("Tabela") + "</w:tc></w:tr></w:tbl>",
        {
            "word/footer2.xml": xml(paragraph("F2")),
            "word/header2.xml": xml(paragraph("H2")),
            "word/header10.xml": xml(paragraph("H10")),
            "word/footer10.xml": xml(paragraph("F10")),
            "word/headerX.xml": b"invalid ignored XML",
        },
    )
    assert service.extract_docx_text(payload) == "Intro\nTítulo\nCorpo\nTabela\nH10\nH2\nF10\nF2"
    assert service.extract_docx_sections(payload) == [
        ("Parágrafo 2", "Intro"), ("Cabeçalho 5", "H10"),
        ("Cabeçalho 6", "H2"), ("Rodapé 7", "F10"),
        ("Rodapé 8", "F2"), ("Título", "Corpo\nTabela"),
    ]


def test_untitled_paragraphs_and_run_whitespace():
    payload = package('<w:p><w:r><w:t> A </w:t></w:r><w:r><w:t>B</w:t></w:r></w:p>'
                      + paragraph(" ") + paragraph("C"))
    assert service.extract_docx_text(payload) == "A\nB\nC"
    assert service.extract_docx_sections(payload) == [("Parágrafo 2", "A B\nC")]


@pytest.mark.parametrize("extractor", [service.extract_docx_text, service.extract_docx_sections])
def test_invalid_xml_preserves_error_and_cause(extractor):
    with pytest.raises(service.ProposalFileValidationError, match="O DOCX contém XML inválido\\.") as error:
        extractor(package("<broken>"))
    assert error.value.__cause__.__class__.__name__ == "ParseError"


@pytest.mark.parametrize("extractor", [service.extract_docx_text, service.extract_docx_sections])
@pytest.mark.parametrize("extra,message", [
    ({"../escape.xml": b"x"}, "caminho interno inseguro"),
    ({"word/vbaProject.bin": b"x"}, "macro"),
    ({"[Content_Types].xml": b"macroenabled"}, "macro"),
])
def test_security_rejection_precedes_invalid_xml(extractor, extra, message):
    if "[Content_Types].xml" in extra:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("[Content_Types].xml", extra["[Content_Types].xml"])
            archive.writestr("word/document.xml", b"invalid")
        payload = stream.getvalue()
    else:
        payload = package("<broken>", extra)
    with pytest.raises(service.ProposalFileValidationError, match=message):
        extractor(payload)


@pytest.mark.parametrize("extractor", [service.extract_docx_text, service.extract_docx_sections])
@pytest.mark.parametrize("constant,message", [
    ("DOCX_MAX_ENTRIES", "entradas"),
    ("DOCX_MAX_UNCOMPRESSED_BYTES", "descompactado"),
])
def test_public_limits_precede_invalid_xml(extractor, constant, message, monkeypatch):
    monkeypatch.setattr(service, constant, 1)
    with pytest.raises(service.ProposalFileValidationError, match=message):
        extractor(package("<broken>"))
