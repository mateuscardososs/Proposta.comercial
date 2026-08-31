import pytest

from app.services import pdf_import_service


def test_valid_pdf_without_text_raises_typed_error(monkeypatch):
    monkeypatch.setattr(pdf_import_service, "_extract_text_pdfplumber", lambda _: "")
    monkeypatch.setattr(pdf_import_service, "_extract_text_pymupdf", lambda _: "")

    with pytest.raises(pdf_import_service.PDFNoTextError):
        pdf_import_service.extract_text_from_pdf(b"%PDF-valid")


def test_pdf_with_both_extractors_failing_raises_technical_error(monkeypatch):
    def fail(_):
        raise RuntimeError("parser failed")

    monkeypatch.setattr(pdf_import_service, "_extract_text_pdfplumber", fail)
    monkeypatch.setattr(pdf_import_service, "_extract_text_pymupdf", fail)

    with pytest.raises(pdf_import_service.PDFImportError) as exc_info:
        pdf_import_service.extract_text_from_pdf(b"%PDF-invalid")

    assert not isinstance(exc_info.value, pdf_import_service.PDFNoTextError)


def test_legacy_safe_parser_still_returns_error_tuple_for_pdf_without_text(monkeypatch):
    monkeypatch.setattr(pdf_import_service, "_extract_text_pdfplumber", lambda _: "")
    monkeypatch.setattr(pdf_import_service, "_extract_text_pymupdf", lambda _: "")

    parsed, error = pdf_import_service.parse_pdf_bytes_safe(
        b"%PDF-scanned",
        filename="scanned.pdf",
    )

    assert parsed is None
    assert error == "PDF sem texto extraível."
