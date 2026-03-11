from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _candidate_commands(libreoffice_cmd: str) -> list[str]:
    normalized = libreoffice_cmd.strip() if libreoffice_cmd else ""
    candidates: list[str] = [normalized] if normalized else []
    for fallback in ("/usr/bin/soffice", "soffice"):
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def convert_docx_to_pdf(docx_path: Path, pdf_path: Path, libreoffice_cmd: str = "soffice") -> Path:
    docx_path = docx_path.resolve()
    pdf_path = pdf_path.resolve()
    outdir = pdf_path.parent
    outdir.mkdir(parents=True, exist_ok=True)

    command_used: str | None = None
    for candidate in _candidate_commands(libreoffice_cmd):
        command = [
            candidate,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(outdir),
            str(docx_path),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            command_used = candidate
            break
        except FileNotFoundError:
            continue
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else "No stderr captured."
            raise RuntimeError(f"PDF conversion failed using '{candidate}': {stderr}") from exc

    if not command_used:
        tried = ", ".join(_candidate_commands(libreoffice_cmd))
        raise RuntimeError(
            "LibreOffice command not found. "
            f"Tried: {tried}. Install LibreOffice or set LIBREOFFICE_CMD."
        )

    generated_pdf = outdir / f"{docx_path.stem}.pdf"
    if not generated_pdf.exists():
        raise RuntimeError("LibreOffice did not generate the expected PDF file.")

    if generated_pdf != pdf_path:
        if pdf_path.exists():
            pdf_path.unlink()
        shutil.move(str(generated_pdf), str(pdf_path))

    return pdf_path
