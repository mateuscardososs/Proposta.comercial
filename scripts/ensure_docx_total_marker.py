from __future__ import annotations

import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": WORD_NS}
TAG_ATTRIBUTE = f"{{{WORD_NS}}}val"
TOTAL_TAG = "AD_VALOR_TOTAL"
TOTAL_PLACEHOLDER = "{{VALOR_TOTAL}}"


def _parse_preserving_namespaces(xml_bytes: bytes) -> ElementTree.Element:
    for _, namespace in ElementTree.iterparse(io.BytesIO(xml_bytes), events=("start-ns",)):
        prefix, uri = namespace
        if prefix != "xml":
            ElementTree.register_namespace(prefix, uri)
    return ElementTree.fromstring(xml_bytes)


def _tag_count(root: ElementTree.Element) -> int:
    return sum(
        1
        for tag in root.findall(".//w:sdt/w:sdtPr/w:tag", NS)
        if tag.get(TAG_ATTRIBUTE) == TOTAL_TAG
    )


def _marked_document_xml(xml_bytes: bytes) -> bytes | None:
    root = _parse_preserving_namespaces(xml_bytes)
    tag_count = _tag_count(root)
    if tag_count == 1:
        return None
    if tag_count > 1:
        raise ValueError("O template contém mais de um marcador AD_VALOR_TOTAL.")

    placeholder_nodes = [
        node
        for node in root.findall(".//w:t", NS)
        if TOTAL_PLACEHOLDER in (node.text or "")
    ]
    if len(placeholder_nodes) != 1:
        raise ValueError(
            "O template deve conter exatamente um placeholder {{VALOR_TOTAL}}."
        )

    parent_by_child = {
        child: parent
        for parent in root.iter()
        for child in parent
    }
    run = parent_by_child.get(placeholder_nodes[0])
    if run is None or run.tag != f"{{{WORD_NS}}}r":
        raise ValueError("O placeholder VALOR_TOTAL não está dentro de um run Word.")
    run_parent = parent_by_child.get(run)
    if run_parent is None:
        raise ValueError("Não foi possível localizar o contêiner do valor total.")

    run_index = list(run_parent).index(run)
    run_parent.remove(run)
    content_control = ElementTree.Element(f"{{{WORD_NS}}}sdt")
    properties = ElementTree.SubElement(content_control, f"{{{WORD_NS}}}sdtPr")
    alias = ElementTree.SubElement(properties, f"{{{WORD_NS}}}alias")
    alias.set(TAG_ATTRIBUTE, "Valor total AD")
    tag = ElementTree.SubElement(properties, f"{{{WORD_NS}}}tag")
    tag.set(TAG_ATTRIBUTE, TOTAL_TAG)
    content = ElementTree.SubElement(content_control, f"{{{WORD_NS}}}sdtContent")
    content.append(run)
    run_parent.insert(run_index, content_control)

    rendered = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    validation_root = _parse_preserving_namespaces(rendered)
    if _tag_count(validation_root) != 1:
        raise ValueError("O marcador não foi inserido corretamente.")
    return rendered


def ensure_total_marker(path: Path) -> bool:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Template não encontrado: {path}")

    try:
        with zipfile.ZipFile(path, "r") as source:
            entries = source.infolist()
            document_xml = source.read("word/document.xml")
            marked_xml = _marked_document_xml(document_xml)
            if marked_xml is None:
                return False

            with tempfile.NamedTemporaryFile(
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
            try:
                with zipfile.ZipFile(temporary_path, "w") as target:
                    for entry in entries:
                        payload = marked_xml if entry.filename == "word/document.xml" else source.read(entry.filename)
                        target.writestr(entry, payload)
                with temporary_path.open("rb") as handle:
                    os.fsync(handle.fileno())
                with zipfile.ZipFile(temporary_path, "r") as validation:
                    validation.testzip()
                    validated_root = _parse_preserving_namespaces(
                        validation.read("word/document.xml")
                    )
                    if _tag_count(validated_root) != 1:
                        raise ValueError("O DOCX final não contém exatamente um marcador.")
                os.replace(temporary_path, path)
            finally:
                temporary_path.unlink(missing_ok=True)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValueError("O arquivo informado não é um template DOCX válido.") from exc
    return True


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Uso: python3 scripts/ensure_docx_total_marker.py CAMINHO.docx")
        return 2
    path = Path(argv[1])
    changed = ensure_total_marker(path)
    print("marcador inserido" if changed else "marcador já presente")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
