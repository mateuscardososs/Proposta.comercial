from __future__ import annotations

import hashlib
import platform
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DocumentTextIndex,
    DocumentTextIndexEntry,
    Proposal,
    ServiceTechnicalReport,
)
from app.services import local_pdf_ocr as _local_pdf_ocr
from app.services import pdf_import_service, proposal_file_service
from app.services.local_pdf_ocr import (
    LocalOCRUnavailable,
    local_tesseract_ocr,
    local_vision_ocr,
)

# Preserve historical OCR imports and their original object identity.
OCR_SCRIPT = _local_pdf_ocr.OCR_SCRIPT
OCR_TIMEOUT_SECONDS = _local_pdf_ocr.OCR_TIMEOUT_SECONDS
TESSERACT_DPI = _local_pdf_ocr.TESSERACT_DPI
TESSERACT_MAX_PAGES = _local_pdf_ocr.TESSERACT_MAX_PAGES
TESSERACT_PAGE_TIMEOUT_SECONDS = _local_pdf_ocr.TESSERACT_PAGE_TIMEOUT_SECONDS
_render_pdf_pages = _local_pdf_ocr._render_pdf_pages

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class ReindexResult:
    discovered: int = 0
    indexed: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: int = 0
    blocked: int = 0
    unsearchable: int = 0
    removed: int = 0
    ocr_pages: int = 0


class _Counters:
    def __init__(self) -> None:
        for name in ReindexResult.__dataclass_fields__:
            setattr(self, name, 0)

    def freeze(self) -> ReindexResult:
        return ReindexResult(**{name: getattr(self, name) for name in ReindexResult.__dataclass_fields__})


def local_ocr_for_platform(pdf_path: Path, *, system: str | None = None) -> list[str] | None:
    """Keep Apple Vision on macOS and select Tesseract only for Windows."""
    current_platform = system or platform.system()
    if current_platform == "Darwin":
        return local_vision_ocr(pdf_path)
    if current_platform == "Windows":
        return local_tesseract_ocr(pdf_path)
    return None


def _ocr_language() -> str:
    return "por" if platform.system() == "Windows" else "pt-BR"


def _source_records(db: Session) -> list[tuple[str, int, str, str]]:
    records: list[tuple[str, int, str, str]] = []
    for source_type, model in (("proposal", Proposal), ("service_report", ServiceTechnicalReport)):
        rows = db.scalars(select(model).order_by(model.id)).all()
        for row in rows:
            for source_slot in ("pdf", "docx"):
                relative_path = str(getattr(row, f"{source_slot}_path", "") or "").strip()
                if relative_path:
                    records.append((source_type, int(row.id), source_slot, relative_path))
    return records


def _safe_registered_path(relative_path: str, root: Path, suffix: str) -> tuple[Path | None, str]:
    try:
        resolved_root = root.resolve()
        candidate = (resolved_root / relative_path).resolve()
        if not candidate.is_relative_to(resolved_root) or candidate.suffix.casefold() != suffix:
            return None, "blocked"
        if not candidate.is_file():
            return None, "missing"
        if candidate.stat().st_size > MAX_DOCUMENT_BYTES:
            return None, "blocked"
        return candidate, ""
    except (OSError, RuntimeError, ValueError):
        return None, "blocked"


def _entries_for_file(
    path: Path,
    suffix: str,
    *,
    ocr_adapter: Callable[[Path], list[str] | None],
) -> tuple[list[tuple[int | None, str | None, str]], str, str, int, bool]:
    """Return page/section chunks, extraction method, language, OCR page count, and partial flag."""
    payload = path.read_bytes()
    entries: list[tuple[int | None, str | None, str]] = []
    if suffix == ".docx":
        sections = proposal_file_service.extract_docx_sections(payload)
        for section, text in sections:
            if text.strip():
                entries.append((None, section, text.strip()))
        return entries, "docx_text", "", 0, False

    try:
        pages = pdf_import_service.extract_pdf_pages(payload)
    except Exception:  # noqa: BLE001 - parser failure must result in an unsearchable, not falsely empty, file.
        pages = []
        # Parsers can report an image-only PDF as having no text; platform-local
        # OCR still gets the already-registered file, never an arbitrary path.
        ocr_pages = ocr_adapter(path)
        if ocr_pages is None:
            raise LocalOCRUnavailable("ocr_unavailable")
        chunks = [(number, None, text.strip()) for number, text in enumerate(ocr_pages, start=1) if text.strip()]
        ocr_count = len(chunks)
        unresolved = len(chunks) != len(ocr_pages) or not chunks
        method = "vision_ocr" if platform.system() == "Darwin" else "tesseract_ocr"
        return chunks, method, _ocr_language(), ocr_count, unresolved
    needs_ocr = any(not text.strip() for text in pages)
    ocr_pages: list[str] | None = None
    ocr_failure = ""
    if needs_ocr:
        try:
            ocr_pages = ocr_adapter(path)
        except LocalOCRUnavailable as exc:
            ocr_failure = exc.code
    ocr_count = 0
    unresolved = False
    for index, page_text in enumerate(pages):
        extracted = page_text.strip()
        if not extracted:
            if ocr_pages is not None and index < len(ocr_pages) and ocr_pages[index].strip():
                extracted = ocr_pages[index].strip()
                ocr_count += 1
            else:
                unresolved = True
        if extracted:
            entries.append((index + 1, None, extracted))
    if ocr_count:
        method = "pdf_text+vision_ocr" if platform.system() == "Darwin" else "pdf_text+tesseract_ocr"
    elif needs_ocr and ocr_pages is None:
        method = f"pdf_text+{ocr_failure or 'ocr_unavailable'}"
    else:
        method = "pdf_text"
    language = _ocr_language() if ocr_count else ""
    return entries, method, language, ocr_count, unresolved


def reindex_registered_documents(
    db: Session,
    *,
    output_dir: Path,
    force: bool = False,
    ocr_adapter: Callable[[Path], list[str] | None] | None = None,
) -> ReindexResult:
    """Reconcile a persistent index against only paths referenced by registered rows."""
    root = Path(output_dir)
    ocr = ocr_adapter or local_ocr_for_platform
    counters = _Counters()
    records = _source_records(db)
    counters.discovered = len(records)
    desired: set[tuple[str, int, str]] = set()

    for source_type, source_id, source_slot, relative_path in records:
        key = (source_type, source_id, source_slot)
        desired.add(key)
        index = db.scalar(
            select(DocumentTextIndex).where(
                DocumentTextIndex.source_type == source_type,
                DocumentTextIndex.source_id == source_id,
                DocumentTextIndex.source_slot == source_slot,
            )
        )
        suffix = f".{source_slot}"
        path, failure = _safe_registered_path(relative_path, root, suffix)
        if path is None:
            if index is None:
                index = DocumentTextIndex(
                    source_type=source_type,
                    source_id=source_id,
                    source_slot=source_slot,
                    relative_path=relative_path,
                    document_name=Path(relative_path).name[:255],
                    status=failure,
                )
                db.add(index)
            else:
                index.relative_path = relative_path
                index.document_name = Path(relative_path).name[:255]
                index.status = failure
                index.content_sha256 = ""
                index.file_size = 0
                index.mtime_ns = 0
                index.extraction_method = ""
                index.language = ""
                index.entries.clear()
                index.indexed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            if failure == "missing":
                counters.missing += 1
            else:
                counters.blocked += 1
            continue

        stat = path.stat()
        if (
            not force
            and index is not None
            and index.relative_path == relative_path
            and index.file_size == stat.st_size
            and index.mtime_ns == stat.st_mtime_ns
            and index.status in {"searchable", "partial"}
        ):
            counters.unchanged += 1
            continue

        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if (
            not force
            and index is not None
            and index.content_sha256 == digest
            and index.status in {"searchable", "partial"}
        ):
            index.relative_path = relative_path
            index.document_name = path.name[:255]
            index.file_size = stat.st_size
            index.mtime_ns = stat.st_mtime_ns
            counters.unchanged += 1
            continue

        if index is None:
            index = DocumentTextIndex(
                source_type=source_type,
                source_id=source_id,
                source_slot=source_slot,
                relative_path=relative_path,
                document_name=path.name[:255],
                status="unsearchable",
            )
            db.add(index)
            db.flush()
            counters.indexed += 1
        else:
            index.entries.clear()
            # Delete old unique ordinals before inserting the replacement projection.
            db.flush()
            counters.updated += 1
        index.relative_path = relative_path
        index.document_name = path.name[:255]
        index.content_sha256 = digest
        index.file_size = stat.st_size
        index.mtime_ns = stat.st_mtime_ns
        index.status = "unsearchable"
        index.extraction_method = ""
        index.language = ""
        index.indexed_at = datetime.now(timezone.utc).replace(tzinfo=None)

        try:
            chunks, method, language, ocr_count, partial = _entries_for_file(path, suffix, ocr_adapter=ocr)
            counters.ocr_pages += ocr_count
            for ordinal, (page, section, text) in enumerate(chunks, start=1):
                db.add(DocumentTextIndexEntry(
                    document_index_id=index.id,
                    ordinal=ordinal,
                    page=page,
                    section=section,
                    text=text,
                ))
            index.extraction_method = method
            index.language = language
            if chunks and partial:
                index.status = "partial"
            elif chunks:
                index.status = "searchable"
            else:
                index.status = "unsearchable"
            if index.status == "unsearchable":
                counters.unsearchable += 1
        except LocalOCRUnavailable as exc:
            # The file stays visible as unsearchable; never claim a no-evidence result as a confirmed absence.
            index.status = "unsearchable"
            index.extraction_method = exc.code[:30]
            index.language = ""
            counters.unsearchable += 1
        except Exception:  # noqa: BLE001 - never leak parser diagnostics or document content to logs.
            # Parsing errors are represented as unavailable; do not log path or document content.
            index.status = "unsearchable"
            index.extraction_method = ""
            index.language = ""
            counters.unsearchable += 1

    for index in db.scalars(select(DocumentTextIndex)).all():
        if (index.source_type, index.source_id, index.source_slot) not in desired:
            db.delete(index)
            counters.removed += 1
    db.flush()
    return counters.freeze()
