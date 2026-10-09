from __future__ import annotations

import io
import json
import platform
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path

OCR_TIMEOUT_SECONDS = 90
TESSERACT_PAGE_TIMEOUT_SECONDS = 30
TESSERACT_MAX_PAGES = 500
TESSERACT_DPI = 200
OCR_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ocr_pdf_vision.swift"


class LocalOCRUnavailable(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def local_vision_ocr(pdf_path: Path) -> list[str] | None:
    """Run Apple Vision OCR locally. Returns one string per PDF page, or None if unavailable."""
    swift = shutil.which("swift")
    if platform.system() != "Darwin" or swift is None or not OCR_SCRIPT.is_file():
        return None
    try:
        completed = subprocess.run(
            [swift, str(OCR_SCRIPT), str(pdf_path)],
            check=False,
            capture_output=True,
            timeout=OCR_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            return None
        payload = json.loads(completed.stdout.decode("utf-8"))
        pages = payload.get("pages")
        if not isinstance(pages, list):
            return None
        result = [""] * len(pages)
        for item in pages:
            if not isinstance(item, dict):
                continue
            page = item.get("page")
            text = item.get("text")
            if isinstance(page, int) and 1 <= page <= len(result) and isinstance(text, str):
                result[page - 1] = text.strip()
        return result
    except (OSError, subprocess.TimeoutExpired, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        # OCR input/output and subprocess diagnostics intentionally never reach application logs.
        return None


def _render_pdf_pages(pdf_path: Path) -> Iterator[bytes]:
    """Render a registered PDF to in-memory PNG pages using optional local PDFium."""
    try:
        import pypdfium2 as pdfium  # type: ignore[import-not-found]
    except ImportError as exc:
        raise LocalOCRUnavailable("ocr_converter_missing") from exc
    try:
        with pdfium.PdfDocument(str(pdf_path)) as document:
            if len(document) > TESSERACT_MAX_PAGES:
                raise LocalOCRUnavailable("ocr_page_limit")
            for page_number in range(len(document)):
                with document.get_page(page_number) as page:
                    bitmap = page.render(scale=TESSERACT_DPI / 72, rev_byteorder=True)
                    try:
                        image = bitmap.to_pil().copy()
                        with io.BytesIO() as buffer:
                            image.save(buffer, format="PNG")
                            image_payload = buffer.getvalue()
                        yield image_payload
                    finally:
                        bitmap.close()
    except LocalOCRUnavailable:
        raise
    except Exception as exc:
        raise LocalOCRUnavailable("ocr_render_failed") from exc


_SETTINGS_UNSET = object()


def local_tesseract_ocr(
    pdf_path: Path,
    *,
    executable: str | None | object = _SETTINGS_UNSET,
    data_dir: str | None | object = _SETTINGS_UNSET,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    renderer: Callable[[Path], Iterator[bytes] | list[bytes]] = _render_pdf_pages,
    temporary_directory: Callable[..., tempfile.TemporaryDirectory] = tempfile.TemporaryDirectory,
) -> list[str]:
    """OCR PDF pages locally with Portuguese traineddata; never installs tools."""
    from app.config import get_settings

    settings = get_settings()
    configured_executable = settings.tesseract_cmd if executable is _SETTINGS_UNSET else executable
    configured_data_dir = settings.tesseract_data_dir if data_dir is _SETTINGS_UNSET else data_dir
    if configured_executable is None:
        raise LocalOCRUnavailable("ocr_tesseract_missing")
    tesseract = which(str(configured_executable or "tesseract"))
    if tesseract is None:
        raise LocalOCRUnavailable("ocr_tesseract_missing")

    language_args = ["--list-langs"]
    if configured_data_dir:
        language_args.extend(["--tessdata-dir", str(configured_data_dir)])
    try:
        language_result = runner(
            [tesseract, *language_args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LocalOCRUnavailable("ocr_tesseract_failed") from exc
    if language_result.returncode != 0:
        raise LocalOCRUnavailable("ocr_tesseract_failed")
    language_output = language_result.stdout or ""
    if isinstance(language_output, bytes):
        language_output = language_output.decode("utf-8", errors="replace")
    if "por" not in {line.strip() for line in language_output.splitlines()}:
        raise LocalOCRUnavailable("ocr_language_missing")

    recognized: list[str] = []
    deadline = time.monotonic() + OCR_TIMEOUT_SECONDS
    try:
        with temporary_directory(prefix="adbalancas-ocr-") as temp_name:
            temp_root = Path(temp_name)
            page_images = iter(renderer(pdf_path))
            try:
                for page_number, image_bytes in enumerate(page_images, start=1):
                    if page_number > TESSERACT_MAX_PAGES:
                        raise LocalOCRUnavailable("ocr_page_limit")
                    image_path = temp_root / f"page-{page_number:04d}.png"
                    image_path.write_bytes(image_bytes)
                    command = [tesseract, str(image_path), "stdout", "-l", "por", "--psm", "3"]
                    if configured_data_dir:
                        command.extend(["--tessdata-dir", str(configured_data_dir)])
                    remaining = min(TESSERACT_PAGE_TIMEOUT_SECONDS, deadline - time.monotonic())
                    if remaining <= 0:
                        raise LocalOCRUnavailable("ocr_tesseract_timeout")
                    completed = runner(
                        command,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=remaining,
                        check=False,
                        shell=False,
                    )
                    if completed.returncode != 0:
                        raise LocalOCRUnavailable("ocr_tesseract_failed")
                    text = completed.stdout or ""
                    if isinstance(text, bytes):
                        text = text.decode("utf-8", errors="replace")
                    recognized.append(text.strip())
            finally:
                close = getattr(page_images, "close", None)
                if callable(close):
                    close()
    except LocalOCRUnavailable:
        raise
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LocalOCRUnavailable("ocr_tesseract_failed") from exc
    except Exception as exc:
        raise LocalOCRUnavailable("ocr_render_failed") from exc
    return recognized

