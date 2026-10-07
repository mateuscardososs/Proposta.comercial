from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant.dates import normalize_text
from app.models import DocumentTextIndex, DocumentTextIndexEntry, Proposal
from app.services.document_index_service import reindex_registered_documents

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_RESULTS = 5
_STOP_WORDS = {
    "a", "as", "ao", "aos", "com", "da", "das", "de", "do", "dos", "e", "em", "na", "nas", "no",
    "nos", "o", "os", "para", "por", "qual", "quais", "que", "sobre", "um", "uma", "tem", "consta",
    "diz", "documento", "documentos", "arquivo", "arquivos", "proposta", "propostas", "pdf", "docx", "word",
}
_SYNONYMS = {
    "prazo": {"prazo", "pagamento", "condicao", "vencimento", "dias"},
    "prazos": {"prazo", "pagamento", "condicao", "vencimento", "dias"},
    "condicao": {"condicao", "pagamento", "prazo", "dias"},
    "condicoes": {"condicao", "pagamento", "prazo", "dias"},
    "pagamento": {"pagamento", "condicao", "prazo", "dias"},
    "pagamentos": {"pagamento", "condicao", "prazo", "dias"},
    "valor": {"valor", "total", "preco", "montante"},
    "valores": {"valor", "total", "preco", "montante"},
    "total": {"total", "valor", "preco", "montante"},
    "preco": {"preco", "valor", "total", "montante"},
    "cliente": {"cliente", "razao", "contratante"},
    "equipamento": {"equipamento", "balanca", "instrumento"},
    "equipamentos": {"equipamento", "balanca", "instrumento"},
}
_INSTRUCTION_LIKE = re.compile(
    r"\b(?:ignore|desconsidere|siga estas instru[cç][oõ]es|execute este comando|obede[cç]a|"
    r"crie uma tarefa|envie um e-mail|altere o banco|ignore as regras)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DocumentEvidence:
    document_name: str
    proposal_number: int | None
    revision: str | None
    page: int | None
    section: str | None
    excerpt: str
    score: float

    def as_dict(self) -> dict[str, object]:
        return {
            "document_name": self.document_name,
            "page": self.page,
            "section": self.section,
            "excerpt": self.excerpt,
        }

    def citation(self) -> str:
        location = f"página {self.page}" if self.page is not None else f"seção {self.section or 'não identificada'}"
        return f"{self.document_name}, {location}"


@dataclass(frozen=True)
class DocumentSearchResult:
    evidence: tuple[DocumentEvidence, ...]
    registered_documents: int
    readable_documents: int
    unreadable_documents: int
    ocr_unavailable_documents: int = 0
    partial_documents: int = 0
    ocr_unavailable_reasons: tuple[str, ...] = ()


_OCR_REASON_LABELS = {
    "ocr_tesseract_missing": "executável Tesseract ausente (configure TESSERACT_CMD ou o PATH)",
    "pdf_text+ocr_tesseract_missing": "executável Tesseract ausente (configure TESSERACT_CMD ou o PATH)",
    "ocr_language_missing": "dados do idioma português (por) ausentes no tessdata",
    "pdf_text+ocr_language_missing": "dados do idioma português (por) ausentes no tessdata",
    "ocr_converter_missing": "pypdfium2/PDFium ausente; instale o extra local de OCR para Windows",
    "pdf_text+ocr_converter_missing": "pypdfium2/PDFium ausente; instale o extra local de OCR para Windows",
    "ocr_render_failed": "falha na conversão local do PDF em imagem",
    "pdf_text+ocr_render_failed": "falha na conversão local do PDF em imagem",
    "ocr_tesseract_failed": "falha ao executar o Tesseract local",
    "pdf_text+ocr_tesseract_failed": "falha ao executar o Tesseract local",
    "ocr_tesseract_timeout": "tempo limite do Tesseract local excedido",
    "ocr_page_limit": "PDF excede o limite de páginas para OCR local",
    "ocr_unavailable": "OCR local da plataforma indisponível",
    "pdf_text+ocr_unavailable": "OCR local da plataforma indisponível",
}


def _proposal_number(query: str) -> int | None:
    match = re.search(r"\bproposta\s+(?:n(?:[ºo.]|umero)?\s*)?(\d+)\b", normalize_text(query))
    return int(match.group(1)) if match else None


def _query_terms(query: str) -> set[str]:
    tokens = set(re.findall(r"[a-z]{3,}", normalize_text(query))) - _STOP_WORDS
    expanded = set(tokens)
    for token in tokens:
        expanded.update(_SYNONYMS.get(token, ()))
    return expanded


def _resolve_registered_file(relative_path: str, output_root: Path, suffix: str) -> Path | None:
    if not relative_path:
        return None
    root = output_root.resolve()
    try:
        candidate = (root / relative_path).resolve()
        if not candidate.is_relative_to(root) or candidate.suffix.casefold() != suffix or not candidate.is_file():
            return None
        if candidate.stat().st_size > MAX_DOCUMENT_BYTES:
            return None
        return candidate
    except (OSError, RuntimeError, ValueError):
        return None


def _segments(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\n+|(?<=[.!?;])\s+", text) if part.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _score_segment(segment: str, query_terms: set[str]) -> float:
    if not query_terms or _INSTRUCTION_LIKE.search(segment):
        return 0.0
    content_terms = set(re.findall(r"[a-z]{3,}", normalize_text(segment)))
    matched = query_terms & content_terms
    if not matched:
        return 0.0
    return len(matched) / len(query_terms)


def _search_document(
    *,
    path: Path,
    proposal: Proposal,
    query_terms: set[str],
    page: int | None,
    section: str | None,
    text: str,
) -> list[DocumentEvidence]:
    evidence: list[DocumentEvidence] = []
    for segment in _segments(text):
        score = _score_segment(segment, query_terms)
        if score:
            evidence.append(
                DocumentEvidence(
                    document_name=path.name,
                    proposal_number=proposal.numero,
                    revision=proposal.revisao,
                    page=page,
                    section=section,
                    excerpt=segment[:700],
                    score=score,
                )
            )
    return evidence


def search_proposal_documents(
    db: Session,
    *,
    output_dir: Path,
    query: str,
    limit: int = MAX_RESULTS,
) -> DocumentSearchResult:
    """Reconcile and search the persistent index of system-registered documents."""
    reindex_registered_documents(db, output_dir=output_dir)
    return search_document_index(db, query=query, limit=limit)


def search_document_index(
    db: Session,
    *,
    query: str,
    limit: int = MAX_RESULTS,
) -> DocumentSearchResult:
    requested_number = _proposal_number(query)
    query_terms = _query_terms(query)
    indexes = db.scalars(select(DocumentTextIndex).order_by(DocumentTextIndex.id)).all()
    registered_documents = len(indexes)
    readable_documents = sum(index.status in {"searchable", "partial"} for index in indexes)
    partial_documents = sum(index.status == "partial" for index in indexes)
    unreadable_documents = sum(index.status not in {"searchable", "partial"} for index in indexes)
    ocr_indexes = [index for index in indexes if "ocr_" in index.extraction_method]
    ocr_unavailable_documents = len(ocr_indexes)
    ocr_reasons = tuple(sorted({
        _OCR_REASON_LABELS.get(index.extraction_method, "falha no OCR local")
        for index in ocr_indexes
    }))
    if requested_number is not None:
        proposal_ids = set(
            db.scalars(select(Proposal.id).where(Proposal.numero == requested_number)).all()
        )
        indexes = [
            index for index in indexes
            if index.source_type == "proposal" and index.source_id in proposal_ids
        ]
    evidence: list[DocumentEvidence] = []
    for index in indexes:
        if index.status not in {"searchable", "partial"}:
            continue
        proposal: Proposal | None = None
        if index.source_type == "proposal":
            proposal = db.get(Proposal, index.source_id)
        for entry in db.scalars(
            select(DocumentTextIndexEntry)
            .where(DocumentTextIndexEntry.document_index_id == index.id)
            .order_by(DocumentTextIndexEntry.ordinal)
        ).all():
            for segment in _segments(entry.text):
                score = _score_segment(segment, query_terms)
                if not score:
                    continue
                evidence.append(
                    DocumentEvidence(
                        document_name=index.document_name,
                        proposal_number=proposal.numero if proposal else None,
                        revision=proposal.revisao if proposal else None,
                        page=entry.page,
                        section=entry.section,
                        excerpt=segment[:700],
                        score=score,
                    )
                )

    evidence.sort(
        key=lambda item: (
            -item.score,
            -(item.proposal_number or 0),
            item.document_name,
            item.page or 0,
            item.section or "",
        )
    )
    return DocumentSearchResult(
        evidence=tuple(evidence[: max(1, min(limit, MAX_RESULTS))]),
        registered_documents=registered_documents,
        readable_documents=readable_documents,
        unreadable_documents=unreadable_documents,
        ocr_unavailable_documents=ocr_unavailable_documents,
        partial_documents=partial_documents,
        ocr_unavailable_reasons=ocr_reasons,
    )
