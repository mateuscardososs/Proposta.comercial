from __future__ import annotations

import io
import logging

from app.services import proposal_pdf_parser

PDFImportError = proposal_pdf_parser.PDFImportError
PDFNoTextError = proposal_pdf_parser.PDFNoTextError
ParsedProposalItem = proposal_pdf_parser.ParsedProposalItem
ParsedScheduleRow = proposal_pdf_parser.ParsedScheduleRow
ParsedProposalData = proposal_pdf_parser.ParsedProposalData
_normalize_text = proposal_pdf_parser._normalize_text
_parse_decimal = proposal_pdf_parser._parse_decimal
_find_label_value = proposal_pdf_parser._find_label_value
_find_first_candidate_client = proposal_pdf_parser._find_first_candidate_client
_extract_section = proposal_pdf_parser._extract_section
_parse_schedule_rows = proposal_pdf_parser._parse_schedule_rows
_parse_item_rows = proposal_pdf_parser._parse_item_rows
_extract_payment_days = proposal_pdf_parser._extract_payment_days
_extract_tax_percent = proposal_pdf_parser._extract_tax_percent
parse_pdf_text = proposal_pdf_parser.parse_pdf_text

logger = logging.getLogger(__name__)


def _extract_pages_pdfplumber(file_bytes: bytes) -> list[str]:
    import pdfplumber  # type: ignore[import-not-found]

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        return [(page.extract_text() or "").strip() for page in pdf.pages]

def _extract_text_pdfplumber(file_bytes: bytes) -> str:
    return "\n".join(_extract_pages_pdfplumber(file_bytes)).strip()

def _extract_pages_pymupdf(file_bytes: bytes) -> list[str]:
    import fitz  # type: ignore[import-not-found]

    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        return [(page.get_text() or "").strip() for page in doc]

def _extract_text_pymupdf(file_bytes: bytes) -> str:
    return "\n".join(_extract_pages_pymupdf(file_bytes)).strip()

def extract_pdf_pages(file_bytes: bytes) -> list[str]:
    """Extract page text with page boundaries, reusing the configured PDF extractors."""
    errors: list[str] = []
    empty_results = 0
    try:
        pages = _extract_pages_pdfplumber(file_bytes)
        if any(pages):
            return pages
        empty_results += 1
        errors.append("pdfplumber returned empty text")
    except Exception as exc:
        errors.append(f"pdfplumber error: {exc}")

    try:
        pages = _extract_pages_pymupdf(file_bytes)
        if any(pages):
            return pages
        empty_results += 1
        errors.append("pymupdf returned empty text")
    except Exception as exc:
        errors.append(f"pymupdf error: {exc}")

    if empty_results:
        raise PDFNoTextError("PDF sem texto extraível.")
    raise PDFImportError("Failed to extract text from PDF: " + " | ".join(errors))

def extract_text_from_pdf(file_bytes: bytes) -> str:
    errors: list[str] = []
    empty_results = 0
    try:
        text = _extract_text_pdfplumber(file_bytes)
        if text:
            return text
        empty_results += 1
        errors.append("pdfplumber returned empty text")
    except Exception as exc:
        errors.append(f"pdfplumber error: {exc}")

    try:
        text = _extract_text_pymupdf(file_bytes)
        if text:
            return text
        empty_results += 1
        errors.append("pymupdf returned empty text")
    except Exception as exc:
        errors.append(f"pymupdf error: {exc}")

    if empty_results:
        raise PDFNoTextError("PDF sem texto extraível.")
    raise PDFImportError("Failed to extract text from PDF: " + " | ".join(errors))

def parse_pdf_bytes(file_bytes: bytes, filename: str = "") -> ParsedProposalData:
    text = extract_text_from_pdf(file_bytes)
    return parse_pdf_text(text=text, filename=filename)

def parse_pdf_bytes_safe(file_bytes: bytes, filename: str = "") -> tuple[ParsedProposalData | None, str | None]:
    try:
        parsed = parse_pdf_bytes(file_bytes=file_bytes, filename=filename)
        return parsed, None
    except Exception as exc:
        logger.exception("PDF import parsing failed for file '%s': %s", filename, exc)
        return None, str(exc)
