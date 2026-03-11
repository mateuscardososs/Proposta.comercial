from __future__ import annotations

import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.schemas import ProposalCreate, ProposalItemCreate, ScheduleItemCreate

logger = logging.getLogger(__name__)


class PDFImportError(RuntimeError):
    pass


@dataclass
class ParsedProposalItem:
    descricao: str
    unidade: str = "UN"
    qtd: Decimal = Decimal("1.00")
    valor_unit: Decimal = Decimal("0.00")

    def as_preview(self) -> dict[str, str]:
        return {
            "descricao": self.descricao,
            "unidade": self.unidade,
            "qtd": str(self.qtd),
            "valor_unit": str(self.valor_unit),
        }

    def to_schema(self) -> ProposalItemCreate:
        return ProposalItemCreate(
            descricao=self.descricao,
            unidade=self.unidade,
            qtd=self.qtd,
            valor_unit=self.valor_unit,
        )


@dataclass
class ParsedScheduleRow:
    dia_label: str
    descricao: str
    horas_servico: str = ""

    def as_preview(self) -> dict[str, str]:
        return {
            "dia_label": self.dia_label,
            "descricao": self.descricao,
            "horas_servico": self.horas_servico,
        }

    def to_schema(self) -> ScheduleItemCreate:
        return ScheduleItemCreate(
            dia_label=self.dia_label,
            descricao=self.descricao,
            horas_servico=self.horas_servico,
        )


@dataclass
class ParsedProposalData:
    filename: str
    client_name: str
    atencao: str = ""
    objeto_texto: str = ""
    condicao_pagamento_dias: int = 0
    imposto_percentual: Decimal = Decimal("0.00")
    schedule_rows: list[ParsedScheduleRow] = field(default_factory=list)
    items: list[ParsedProposalItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_preview(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "client_name": self.client_name,
            "atencao": self.atencao,
            "objeto_texto": self.objeto_texto,
            "condicao_pagamento_dias": self.condicao_pagamento_dias,
            "imposto_percentual": str(self.imposto_percentual),
            "schedule_rows": [row.as_preview() for row in self.schedule_rows],
            "items": [item.as_preview() for item in self.items],
            "warnings": self.warnings,
        }

    def to_proposal_payload(self, client_id: int, user_id: int) -> ProposalCreate:
        return ProposalCreate(
            client_id=client_id,
            user_id=user_id,
            atencao=self.atencao,
            objeto_texto=self.objeto_texto,
            contato_nome=self.atencao,
            condicao_pagamento_dias=max(self.condicao_pagamento_dias, 0),
            imposto_percentual=self.imposto_percentual,
            itens=[item.to_schema() for item in self.items],
            schedule_items=[row.to_schema() for row in self.schedule_rows],
        )


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return without_accents.lower().strip()


def _parse_decimal(raw: str, default: str = "0.00") -> Decimal:
    value = (raw or "").strip()
    if not value:
        return Decimal(default)
    value = re.sub(r"[^0-9,.\-]", "", value)
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")
    try:
        return Decimal(value)
    except Exception:
        return Decimal(default)


def _extract_text_pdfplumber(file_bytes: bytes) -> str:
    import pdfplumber  # type: ignore[import-not-found]

    chunks: list[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            chunks.append(page.extract_text() or "")
    return "\n".join(chunks).strip()


def _extract_text_pymupdf(file_bytes: bytes) -> str:
    import fitz  # type: ignore[import-not-found]

    chunks: list[str] = []
    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        for page in doc:
            chunks.append(page.get_text() or "")
    return "\n".join(chunks).strip()


def extract_text_from_pdf(file_bytes: bytes) -> str:
    errors: list[str] = []
    try:
        text = _extract_text_pdfplumber(file_bytes)
        if text:
            return text
        errors.append("pdfplumber returned empty text")
    except Exception as exc:
        errors.append(f"pdfplumber error: {exc}")

    try:
        text = _extract_text_pymupdf(file_bytes)
        if text:
            return text
        errors.append("pymupdf returned empty text")
    except Exception as exc:
        errors.append(f"pymupdf error: {exc}")

    raise PDFImportError("Failed to extract text from PDF: " + " | ".join(errors))


def _find_label_value(lines: list[str], labels: list[str]) -> str:
    labels_norm = [_normalize_text(label) for label in labels]
    for index, line in enumerate(lines):
        line_norm = _normalize_text(line)
        for label in labels_norm:
            if line_norm == label and index + 1 < len(lines):
                return lines[index + 1].strip()
            if line_norm.startswith(label + ":"):
                return line.split(":", 1)[1].strip()
            if line_norm.startswith(label + " -"):
                return line.split("-", 1)[1].strip()
            if label in line_norm and ":" in line:
                left, right = line.split(":", 1)
                if label in _normalize_text(left):
                    return right.strip()
    return ""


def _find_first_candidate_client(lines: list[str]) -> str:
    blocked_terms = {
        "proposta",
        "orcamento",
        "comercial",
        "numero",
        "revisao",
        "data",
        "cliente",
    }
    for line in lines[:20]:
        clean = line.strip()
        if len(clean) < 5:
            continue
        words = [word for word in re.split(r"\s+", _normalize_text(clean)) if word]
        if len(words) < 2:
            continue
        if any(word in blocked_terms for word in words[:2]):
            continue
        return clean
    return ""


def _extract_section(lines: list[str], start_keys: list[str], stop_keys: list[str]) -> list[str]:
    start_norm = [_normalize_text(key) for key in start_keys]
    stop_norm = [_normalize_text(key) for key in stop_keys]
    collecting = False
    section: list[str] = []
    for line in lines:
        line_norm = _normalize_text(line)
        if not collecting:
            if any(key in line_norm for key in start_norm):
                collecting = True
            continue
        if re.match(r"^\d+(?:\.\d+)?\.\s", line.strip()):
            break
        if any(key in line_norm for key in stop_norm):
            break
        section.append(line.strip())
    return [line for line in section if line]


def _parse_schedule_rows(lines: list[str]) -> list[ParsedScheduleRow]:
    rows: list[ParsedScheduleRow] = []
    pending_description: list[str] = []
    for line in lines:
        raw = line.strip()
        if not raw:
            continue
        if raw.startswith("•"):
            pending_description.append(raw.lstrip("•").strip())
            continue

        day_hour_match = re.search(
            r"(?P<dia>\d+\s*dias?)\s+(?P<horas>\d+[.,]?\d*\s*(?:h|hora|horas).*)$",
            raw,
            re.IGNORECASE,
        )
        if day_hour_match:
            description = "; ".join(pending_description).strip()
            rows.append(
                ParsedScheduleRow(
                    dia_label=day_hour_match.group("dia").strip(),
                    descricao=description,
                    horas_servico=day_hour_match.group("horas").strip(),
                )
            )
            pending_description = []
            continue

        if "|" in raw:
            parts = [part.strip() for part in raw.split("|") if part.strip()]
        elif ";" in raw:
            parts = [part.strip() for part in raw.split(";") if part.strip()]
        else:
            parts = re.split(r"\s{2,}", raw)
            parts = [part.strip() for part in parts if part.strip()]

        if len(parts) >= 3:
            rows.append(ParsedScheduleRow(dia_label=parts[0], descricao=parts[1], horas_servico=parts[2]))
            continue
        if len(parts) == 2:
            rows.append(ParsedScheduleRow(dia_label=parts[0], descricao=parts[1], horas_servico=""))
            continue

        match = re.match(r"^(?P<dia>[^:]+):\s*(?P<desc>.+)$", raw)
        if match:
            dia_label = match.group("dia").strip()
            description = match.group("desc").strip()
            horas = ""
            horas_match = re.search(r"(\d+[.,]?\d*\s*(?:h|hora|horas).*)$", description, re.IGNORECASE)
            if horas_match:
                horas = horas_match.group(1).strip()
                description = description[: horas_match.start()].strip(" -")
            rows.append(ParsedScheduleRow(dia_label=dia_label, descricao=description, horas_servico=horas))
    return rows


def _parse_item_rows(lines: list[str]) -> list[ParsedProposalItem]:
    items: list[ParsedProposalItem] = []
    bullet_blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in lines:
        raw = line.strip()
        if not raw:
            continue
        if _normalize_text(raw).startswith("valor total"):
            break
        if raw.startswith("•"):
            if current_block:
                bullet_blocks.append(current_block)
            current_block = [raw.lstrip("•").strip()]
            continue
        if current_block:
            current_block.append(raw)
    if current_block:
        bullet_blocks.append(current_block)

    for block in bullet_blocks:
        candidate = " ".join(block).strip()
        if candidate.count("R$") > 2:
            candidate = re.sub(r"R\$\s*[\d\.,]+\s*[A-Za-z]{0,4}\s+", "", candidate, count=1)
        money_matches = list(re.finditer(r"R\$\s*([\d\.,]+)", candidate, re.IGNORECASE))
        if len(money_matches) < 2:
            continue
        unit_money = money_matches[-2].group(1)
        first_money_start = money_matches[-2].start()
        prefix = candidate[:first_money_start].strip()
        qty_matches = list(re.finditer(r"(\d+(?:[.,]\d+)?)", prefix))
        if not qty_matches:
            continue
        qty_match = qty_matches[-1]
        description = prefix[: qty_match.start()].strip(" -;:")
        if not description:
            continue
        trailing = prefix[qty_match.end() :].strip(" -;:")
        unidade = "UN"
        if trailing:
            last_token = trailing.split()[-1].strip(";:,.")
            if re.match(r"^[A-Za-z]{1,6}$", last_token):
                unidade = last_token
        items.append(
            ParsedProposalItem(
                descricao=description,
                unidade=unidade[:30] or "UN",
                qtd=_parse_decimal(qty_match.group(1), default="1.00"),
                valor_unit=_parse_decimal(unit_money, default="0.00"),
            )
        )

    if items:
        return items

    for line in lines:
        raw = line.strip()
        if not raw:
            continue
        if "|" in raw:
            parts = [part.strip() for part in raw.split("|") if part.strip()]
        elif ";" in raw:
            parts = [part.strip() for part in raw.split(";") if part.strip()]
        else:
            parts = re.split(r"\s{2,}", raw)
            parts = [part.strip() for part in parts if part.strip()]

        if len(parts) >= 4:
            qtd = _parse_decimal(parts[-3], default="1.00")
            valor = _parse_decimal(parts[-2], default="0.00")
            descricao = parts[1] if len(parts) >= 5 else parts[0]
            unidade = parts[-4] if len(parts) >= 5 else "UN"
            if descricao:
                items.append(
                    ParsedProposalItem(
                        descricao=descricao,
                        unidade=(unidade or "UN")[:30],
                        qtd=qtd,
                        valor_unit=valor,
                    )
                )

    if not items:
        for line in lines:
            raw = line.strip()
            bullet = re.match(r"^[-*]\s*(.+)$", raw)
            if bullet:
                description = bullet.group(1).strip()
                if description:
                    items.append(ParsedProposalItem(descricao=description))

    return items


def _extract_payment_days(lines: list[str]) -> int:
    candidate_lines: list[str] = []
    labels = ["condicao de pagamento", "prazo de pagamento", "forma de pagamento", "pagamento"]
    labels_norm = [_normalize_text(label) for label in labels]
    for index, line in enumerate(lines):
        line_norm = _normalize_text(line)
        if any(label in line_norm for label in labels_norm):
            candidate_lines.append(line)
            if index + 1 < len(lines):
                candidate_lines.append(lines[index + 1])

    for candidate in candidate_lines:
        match = re.search(r"(\d{1,3})\s*dias?", _normalize_text(candidate))
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return 0


def _extract_tax_percent(lines: list[str]) -> Decimal:
    labels = ["imposto", "aliquota", "iss", "tribut"]
    labels_norm = [_normalize_text(label) for label in labels]
    for index, line in enumerate(lines):
        line_norm = _normalize_text(line)
        if any(label in line_norm for label in labels_norm):
            for candidate in (line, lines[index + 1] if index + 1 < len(lines) else ""):
                match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", candidate)
                if match:
                    return _parse_decimal(match.group(1), default="0.00")
    return Decimal("0.00")


def parse_pdf_text(text: str, filename: str = "") -> ParsedProposalData:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise PDFImportError("PDF text is empty.")

    client_name = _find_label_value(lines, ["cliente", "razao social"])
    if not client_name:
        client_name = _find_first_candidate_client(lines)
    if not client_name:
        raise PDFImportError("Could not extract client name.")

    atencao = _find_label_value(lines, ["atencao", "a/c", "contato"])
    ref_contact = _find_label_value(lines, ["ref. cliente/projeto", "ref cliente/projeto"])
    if ref_contact:
        if not atencao or _normalize_text(atencao) == _normalize_text(client_name):
            atencao = ref_contact
    objeto = _find_label_value(lines, ["objeto", "objeto da proposta", "objeto de fornecimento"])

    schedule_section = _extract_section(
        lines,
        start_keys=["cronograma", "cronograma de obra", "planejamento"],
        stop_keys=[
            "itens",
            "condicao de pagamento",
            "investimento",
            "valor total",
            "observacoes",
            "nota",
            "responsabilidades",
            "desvios",
        ],
    )
    item_section = _extract_section(
        lines,
        start_keys=["itens", "item", "escopo"],
        stop_keys=["cronograma", "condicao de pagamento", "investimento", "valor total", "observacoes"],
    )

    schedule_rows = _parse_schedule_rows(schedule_section)
    items = _parse_item_rows(item_section)
    payment_days = _extract_payment_days(lines)
    tax_percent = _extract_tax_percent(lines)

    warnings: list[str] = []
    if not objeto:
        warnings.append("Could not confidently extract proposal object.")
    if not items:
        warnings.append("No proposal items parsed from PDF.")
    if not schedule_rows:
        warnings.append("No schedule rows parsed from PDF.")

    return ParsedProposalData(
        filename=filename,
        client_name=client_name,
        atencao=atencao,
        objeto_texto=objeto,
        condicao_pagamento_dias=payment_days,
        imposto_percentual=tax_percent,
        schedule_rows=schedule_rows,
        items=items,
        warnings=warnings,
    )


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
