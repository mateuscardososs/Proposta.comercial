from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree

from app.services.document_errors import ProposalFileValidationError

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": WORD_NS}
TAG_ATTRIBUTE = f"{{{WORD_NS}}}val"


def _xml_text(xml_bytes: bytes) -> str:
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as exc:
        raise ProposalFileValidationError("O DOCX contém XML inválido.") from exc
    return "\n".join(
        text
        for node in root.findall(".//w:t", NS)
        if (text := (node.text or "").strip())
    )


def extract_validated_docx_text(payload: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = ["word/document.xml"]
        names.extend(sorted(name for name in archive.namelist() if re.fullmatch(r"word/header\d+\.xml", name)))
        names.extend(sorted(name for name in archive.namelist() if re.fullmatch(r"word/footer\d+\.xml", name)))
        return "\n".join(_xml_text(archive.read(name)) for name in names).strip()


def extract_validated_docx_sections(payload: bytes) -> list[tuple[str, str]]:
    """Extract paragraph groups with their heading when the DOCX provides one."""
    sections: list[tuple[str, str]] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = ["word/document.xml"]
        names.extend(sorted(name for name in archive.namelist() if re.fullmatch(r"word/header\d+\.xml", name)))
        names.extend(sorted(name for name in archive.namelist() if re.fullmatch(r"word/footer\d+\.xml", name)))
        current_heading = ""
        current_paragraphs: list[str] = []
        paragraph_number = 0

        def flush() -> None:
            if current_paragraphs:
                label = current_heading or f"Parágrafo {paragraph_number}"
                sections.append((label, "\n".join(current_paragraphs)))

        for name in names:
            try:
                root = ElementTree.fromstring(archive.read(name))
            except ElementTree.ParseError as exc:
                raise ProposalFileValidationError("O DOCX contém XML inválido.") from exc
            if name.startswith("word/header"):
                prefix = "Cabeçalho"
            elif name.startswith("word/footer"):
                prefix = "Rodapé"
            else:
                prefix = ""

            for paragraph in root.findall(".//w:p", NS):
                text = "".join((node.text or "") for node in paragraph.findall(".//w:t", NS)).strip()
                if not text:
                    continue
                paragraph_number += 1
                style = paragraph.find("./w:pPr/w:pStyle", NS)
                style_name = (style.get(TAG_ATTRIBUTE, "") if style is not None else "").casefold()
                is_heading = bool(re.search(r"(?:heading|titulo|título|title)\s*\d*", style_name))
                if is_heading:
                    flush()
                    current_paragraphs.clear()
                    current_heading = text
                    continue
                if prefix:
                    sections.append((f"{prefix} {paragraph_number}", text))
                else:
                    current_paragraphs.append(text)
        flush()
    return sections


