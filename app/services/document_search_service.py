from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.assistant.dates import normalize_text
from app.models import Proposal
from app.services import pdf_import_service, proposal_file_service

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
    proposal_number: int
    revision: str
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
    """Search only files registered on proposal rows and contained in OUTPUT_DIR."""
    requested_number = _proposal_number(query)
    query_terms = _query_terms(query)
    proposals = (
        db.query(Proposal)
        .filter((Proposal.docx_path != "") | (Proposal.pdf_path != ""))
        .order_by(Proposal.data_geracao.desc(), Proposal.numero.desc(), Proposal.id.desc())
        .all()
    )
    if requested_number is not None:
        proposals = [proposal for proposal in proposals if proposal.numero == requested_number]

    registered_documents = 0
    readable_documents = 0
    unreadable_documents = 0
    evidence: list[DocumentEvidence] = []
    for proposal in proposals:
        for relative_path, suffix in ((proposal.pdf_path, ".pdf"), (proposal.docx_path, ".docx")):
            if not relative_path:
                continue
            registered_documents += 1
            path = _resolve_registered_file(relative_path, output_dir, suffix)
            if path is None:
                unreadable_documents += 1
                continue
            try:
                payload = path.read_bytes()
                if suffix == ".pdf":
                    pages = pdf_import_service.extract_pdf_pages(payload)
                    if not any(pages):
                        raise pdf_import_service.PDFNoTextError("PDF sem texto extraível.")
                    readable_documents += 1
                    for page_number, page_text in enumerate(pages, start=1):
                        evidence.extend(
                            _search_document(
                                path=path,
                                proposal=proposal,
                                query_terms=query_terms,
                                page=page_number,
                                section=None,
                                text=page_text,
                            )
                        )
                else:
                    sections = proposal_file_service.extract_docx_sections(payload)
                    readable_documents += 1
                    for section, section_text in sections:
                        evidence.extend(
                            _search_document(
                                path=path,
                                proposal=proposal,
                                query_terms=query_terms,
                                page=None,
                                section=section,
                                text=section_text,
                            )
                        )
            except Exception:
                # The reply reports incompleteness without logging document contents or parser details.
                unreadable_documents += 1

    evidence.sort(key=lambda item: (-item.score, -item.proposal_number, item.document_name, item.page or 0))
    return DocumentSearchResult(
        evidence=tuple(evidence[: max(1, min(limit, MAX_RESULTS))]),
        registered_documents=registered_documents,
        readable_documents=readable_documents,
        unreadable_documents=unreadable_documents,
    )
