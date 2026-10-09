from __future__ import annotations

import io
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath
from typing import Literal, Sequence
from xml.etree import ElementTree

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.models import Client, Proposal, User
from app.services import docx_text as _docx_text
from app.services.docx_text import (
    NS,
    TAG_ATTRIBUTE,
    extract_validated_docx_sections,
    extract_validated_docx_text,
)
from app.services.document_errors import ProposalFileValidationError
from app.services import numbering_service, pdf_import_service, pdf_service, proposal_service, storage_service
from app.utils.currency import quantize_2
from app.utils.formatters import decimal_from_str


MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DOCX_MAX_ENTRIES = 500
DOCX_MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
DOCX_TOTAL_TAG = "AD_VALOR_TOTAL"

WORD_NS = _docx_text.WORD_NS
_xml_text = _docx_text._xml_text

class ProposalFileConflictError(ProposalFileValidationError):
    pass


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    suffix: Literal[".docx", ".pdf"]
    payload: bytes


@dataclass(frozen=True)
class WordAnalysis:
    filename: str
    valor_total: Decimal | None
    marker_found: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ClientSuggestion:
    client_id: int
    client_name: str
    confidence: float


@dataclass(frozen=True)
class ExternalAnalysis:
    filename: str
    file_type: Literal["docx", "pdf"]
    suggested_client: ClientSuggestion | None
    suggested_valor_total: Decimal | None
    warnings: tuple[str, ...]


def _safe_zip_path(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ProposalFileValidationError("O DOCX contém um caminho interno inseguro.")
    return path


def _validate_docx_package(payload: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            if len(entries) > DOCX_MAX_ENTRIES:
                raise ProposalFileValidationError("O DOCX excede o limite de entradas internas.")
            if sum(entry.file_size for entry in entries) > DOCX_MAX_UNCOMPRESSED_BYTES:
                raise ProposalFileValidationError("O DOCX excede o limite descompactado.")

            names: set[str] = set()
            for entry in entries:
                path = _safe_zip_path(entry.filename)
                normalized_name = path.as_posix()
                names.add(normalized_name)
                if entry.flag_bits & 0x1:
                    raise ProposalFileValidationError("DOCX criptografado não é permitido.")
                if normalized_name.lower().endswith("vbaproject.bin"):
                    raise ProposalFileValidationError("DOCX com macro não é permitido.")

            required = {"[Content_Types].xml", "word/document.xml"}
            if not required.issubset(names):
                raise ProposalFileValidationError("O arquivo não contém um pacote OOXML válido.")

            content_types = archive.read("[Content_Types].xml").lower()
            if b"macroenabled" in content_types or b"vbaproject" in content_types:
                raise ProposalFileValidationError("DOCX com macro não é permitido.")
            archive.read("word/document.xml")
    except ProposalFileValidationError:
        raise
    except (zipfile.BadZipFile, KeyError, RuntimeError, OSError) as exc:
        raise ProposalFileValidationError("O arquivo enviado não é um DOCX válido.") from exc


def validate_upload(
    filename: str,
    payload: bytes,
    allowed_suffixes: frozenset[str],
) -> ValidatedUpload:
    safe_filename = Path(filename or "").name
    suffix = Path(safe_filename).suffix.lower()
    if suffix not in allowed_suffixes:
        raise ProposalFileValidationError("Formato de arquivo não permitido.")
    if not payload:
        raise ProposalFileValidationError("O arquivo está vazio.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ProposalFileValidationError("O arquivo excede o limite de 20 MB.")
    if suffix == ".pdf" and not payload.startswith(b"%PDF-"):
        raise ProposalFileValidationError("O arquivo enviado não é um PDF válido.")
    if suffix == ".docx":
        _validate_docx_package(payload)
    return ValidatedUpload(safe_filename, suffix, payload)  # type: ignore[arg-type]


def extract_docx_text(payload: bytes) -> str:
    _validate_docx_package(payload)
    return extract_validated_docx_text(payload)


def extract_docx_sections(payload: bytes) -> list[tuple[str, str]]:
    """Extract paragraph groups with their heading when the DOCX provides one."""
    _validate_docx_package(payload)
    return extract_validated_docx_sections(payload)


def _parse_marker_total(raw_value: str) -> Decimal:
    cleaned = re.sub(r"(?i)^\s*R\$\s*", "", raw_value).strip()
    if not re.fullmatch(r"-?\d+(?:\.\d{3})*(?:,\d{1,2})?", cleaned):
        raise ValueError("invalid BRL value")
    return quantize_2(decimal_from_str(cleaned))


def analyze_word_reupload(filename: str, payload: bytes) -> WordAnalysis:
    upload = validate_upload(filename, payload, frozenset({".docx"}))
    with zipfile.ZipFile(io.BytesIO(upload.payload)) as archive:
        try:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        except ElementTree.ParseError as exc:
            raise ProposalFileValidationError("O DOCX contém XML inválido.") from exc

    markers = [
        content_control
        for content_control in root.findall(".//w:sdt", NS)
        if any(
            tag.get(TAG_ATTRIBUTE) == DOCX_TOTAL_TAG
            for tag in content_control.findall("./w:sdtPr/w:tag", NS)
        )
    ]
    warning = "Marcador do total ausente ou inválido. Informe o valor total manualmente."
    if len(markers) != 1:
        return WordAnalysis(upload.filename, None, False, (warning,))

    raw_value = "".join(
        node.text or ""
        for node in markers[0].findall(".//w:t", NS)
    ).strip()
    try:
        total = _parse_marker_total(raw_value)
    except ValueError:
        return WordAnalysis(upload.filename, None, False, (warning,))
    return WordAnalysis(upload.filename, total, True, ())


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    without_punctuation = re.sub(r"[^a-zA-Z0-9]+", " ", without_accents.lower())
    return re.sub(r"\s+", " ", without_punctuation).strip()


def suggest_client(text: str, clients: Sequence[Client]) -> ClientSuggestion | None:
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return None

    exact_matches = [
        client
        for client in clients
        if (name := _normalize_text(client.razao_social)) and name in normalized_text
    ]
    if len(exact_matches) == 1:
        client = exact_matches[0]
        return ClientSuggestion(client.id, client.razao_social, 1.0)
    if len(exact_matches) > 1:
        return None

    lines = [
        normalized_line
        for line in text.splitlines()
        if (normalized_line := _normalize_text(line))
    ]
    for line in lines:
        line_tokens = set(line.split())
        if len(line_tokens) < 2:
            continue
        prefix_matches = [
            client
            for client in clients
            if line_tokens < set(_normalize_text(client.razao_social).split())
        ]
        if len(prefix_matches) > 1:
            return None

    ranked: list[tuple[float, Client]] = []
    for client in clients:
        client_name = _normalize_text(client.razao_social)
        if not client_name:
            continue
        best_score = max(
            (SequenceMatcher(None, client_name, line).ratio() for line in lines),
            default=0.0,
        )
        ranked.append((best_score, client))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked or ranked[0][0] < 0.82:
        return None
    second_score = ranked[1][0] if len(ranked) > 1 else None
    if second_score is not None and ranked[0][0] - second_score < 0.08:
        return None
    best_score, best_client = ranked[0]
    return ClientSuggestion(
        best_client.id,
        best_client.razao_social,
        round(best_score, 4),
    )


TOTAL_LABELS = (
    "valor total",
    "total geral",
    "total da proposta",
    "investimento total",
)
MONEY_PATTERN = re.compile(r"R\$\s*(-?\d+(?:\.\d{3})*(?:,\d{1,2})?)", re.IGNORECASE)


def suggest_total(text: str) -> Decimal | None:
    lines = text.splitlines()
    candidates: list[tuple[int, Decimal]] = []
    for index, line in enumerate(lines):
        normalized_line = _normalize_text(line)
        if not any(label in normalized_line for label in TOTAL_LABELS):
            continue
        same_line = MONEY_PATTERN.findall(line)
        if same_line:
            candidates.extend((0, _parse_marker_total(value)) for value in same_line)
            continue
        if index + 1 < len(lines):
            next_line = MONEY_PATTERN.findall(lines[index + 1])
            candidates.extend((1, _parse_marker_total(value)) for value in next_line)

    if not candidates:
        return None
    best_priority = min(priority for priority, _ in candidates)
    best_values = {
        value
        for priority, value in candidates
        if priority == best_priority
    }
    if len(best_values) != 1:
        return None
    return next(iter(best_values))


def analyze_external_upload(
    db: Session,
    filename: str,
    payload: bytes,
) -> ExternalAnalysis:
    upload = validate_upload(filename, payload, frozenset({".docx", ".pdf"}))
    warnings: list[str] = []
    if upload.suffix == ".docx":
        text = extract_docx_text(upload.payload)
    else:
        try:
            text = pdf_import_service.extract_text_from_pdf(upload.payload)
        except pdf_import_service.PDFNoTextError:
            text = ""
            warnings.append(
                "Este PDF parece escaneado. Não foi possível extrair cliente "
                "e valor automaticamente."
            )
        except pdf_import_service.PDFImportError as exc:
            raise ProposalFileValidationError(
                "Não foi possível ler o PDF enviado. Verifique o arquivo e tente novamente."
            ) from exc
    clients = db.query(Client).order_by(Client.id.asc()).all()
    return ExternalAnalysis(
        filename=upload.filename,
        file_type=upload.suffix.removeprefix("."),  # type: ignore[arg-type]
        suggested_client=suggest_client(text, clients),
        suggested_valor_total=suggest_total(text),
        warnings=tuple(warnings),
    )


def _confirmed_total(value: Decimal) -> Decimal:
    try:
        total = quantize_2(value)
    except Exception as exc:
        raise ProposalFileValidationError("Valor total inválido.") from exc
    if total < 0:
        raise ProposalFileValidationError("O valor total não pode ser negativo.")
    return total


def _new_documental_proposal(
    *,
    numero: int,
    revisao: str,
    proposal_date: date,
    client_id: int,
    user_id: int,
    origem: str,
    valor_total: Decimal,
) -> Proposal:
    return Proposal(
        numero=numero,
        revisao=revisao,
        data_geracao=proposal_date,
        client_id=client_id,
        user_id=user_id,
        origem=origem,
        objeto_tipo="outro",
        objeto_texto="Proposta documental — consulte o arquivo oficial",
        valor_total=valor_total,
    )


def _copy_exclusive(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    created_destination = False
    try:
        with source.open("rb") as src:
            with destination.open("xb") as dst:
                created_destination = True
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
    except FileExistsError as exc:
        raise ProposalFileConflictError(
            "Já existe um arquivo para esta proposta ou revisão."
        ) from exc
    except Exception:
        if created_destination:
            destination.unlink(missing_ok=True)
        raise


def _remove_created_files(paths: list[Path]) -> None:
    for path in reversed(paths):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _store_official_files(
    upload: ValidatedUpload,
    proposal: Proposal,
    settings: Settings,
) -> tuple[str, str, list[Path]]:
    docx_path, pdf_path = storage_service.build_document_paths(
        base_output=settings.output_dir,
        proposal_date=proposal.data_geracao,
        client_name=proposal.client.razao_social,
        numero=proposal.numero,
        revisao=proposal.revisao,
    )
    promoted: list[Path] = []
    try:
        with tempfile.TemporaryDirectory(prefix="proposal-files-", dir=docx_path.parent) as temp_dir:
            temp_root = Path(temp_dir)
            if upload.suffix == ".docx":
                temp_docx = temp_root / docx_path.name
                temp_pdf = temp_root / pdf_path.name
                temp_docx.write_bytes(upload.payload)
                pdf_service.convert_docx_to_pdf(
                    docx_path=temp_docx,
                    pdf_path=temp_pdf,
                    libreoffice_cmd=settings.libreoffice_cmd,
                )
                _copy_exclusive(temp_docx, docx_path)
                promoted.append(docx_path)
                _copy_exclusive(temp_pdf, pdf_path)
                promoted.append(pdf_path)
                return (
                    storage_service.to_output_relative(docx_path, settings.output_dir),
                    storage_service.to_output_relative(pdf_path, settings.output_dir),
                    promoted,
                )

            temp_pdf = temp_root / pdf_path.name
            temp_pdf.write_bytes(upload.payload)
            _copy_exclusive(temp_pdf, pdf_path)
            promoted.append(pdf_path)
            return (
                "",
                storage_service.to_output_relative(pdf_path, settings.output_dir),
                promoted,
            )
    except Exception:
        _remove_created_files(promoted)
        raise


def _persist_documental_proposal(
    db: Session,
    proposal: Proposal,
    upload: ValidatedUpload,
    settings: Settings,
) -> Proposal:
    promoted: list[Path] = []
    try:
        db.add(proposal)
        db.flush()
        db.refresh(proposal, attribute_names=["client"])
        docx_path, pdf_path, promoted = _store_official_files(
            upload,
            proposal,
            settings,
        )
        proposal.docx_path = docx_path
        proposal.pdf_path = pdf_path
        db.add(proposal)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _remove_created_files(promoted)
        raise ProposalFileConflictError(
            "Outra proposta ou revisão foi criada ao mesmo tempo. "
            "Recarregue e tente novamente."
        ) from exc
    except Exception:
        db.rollback()
        _remove_created_files(promoted)
        raise

    created = proposal_service.get_proposal_with_details(db, proposal.id)
    if not created:
        raise ProposalFileValidationError("Não foi possível recarregar a proposta criada.")
    return created


def _resolve_source_docx(source: Proposal, settings: Settings) -> Path:
    if not source.docx_path:
        raise ProposalFileValidationError("A proposta de origem não possui arquivo Word.")
    output_root = settings.output_dir.resolve()
    candidate = (output_root / source.docx_path).resolve()
    if not candidate.is_relative_to(output_root) or not candidate.is_file():
        raise ProposalFileValidationError("O arquivo Word da proposta de origem não foi encontrado.")
    return candidate


def create_word_revision(
    db: Session,
    source_id: int,
    filename: str,
    payload: bytes,
    confirmed_total: Decimal,
    settings: Settings,
) -> Proposal:
    source = proposal_service.get_proposal_with_details(db, source_id)
    if not source:
        raise ProposalFileValidationError("Proposta de origem não encontrada.")
    _resolve_source_docx(source, settings)
    upload = validate_upload(filename, payload, frozenset({".docx"}))
    proposal = _new_documental_proposal(
        numero=source.numero,
        revisao=numbering_service.get_next_revision_for_number(db, source.numero),
        proposal_date=date.today(),
        client_id=source.client_id,
        user_id=source.user_id,
        origem="reupload_editado",
        valor_total=_confirmed_total(confirmed_total),
    )
    return _persist_documental_proposal(db, proposal, upload, settings)


def create_external_proposal(
    db: Session,
    filename: str,
    payload: bytes,
    client_id: int,
    user_id: int,
    proposal_date: date,
    confirmed_total: Decimal,
    settings: Settings,
) -> Proposal:
    client_exists = db.query(Client.id).filter(Client.id == client_id).first()
    if not client_exists:
        raise ProposalFileValidationError("Cliente não encontrado.")
    user_exists = db.query(User.id).filter(User.id == user_id, User.ativo.is_(True)).first()
    if not user_exists:
        raise ProposalFileValidationError("Responsável ativo não encontrado.")
    upload = validate_upload(filename, payload, frozenset({".docx", ".pdf"}))
    proposal = _new_documental_proposal(
        numero=numbering_service.get_next_proposal_number(db),
        revisao="00",
        proposal_date=proposal_date,
        client_id=client_id,
        user_id=user_id,
        origem="upload_externo",
        valor_total=_confirmed_total(confirmed_total),
    )
    return _persist_documental_proposal(db, proposal, upload, settings)
