from __future__ import annotations

from datetime import date
from pathlib import Path

from app.utils.dates import format_file_date
from app.utils.formatters import safe_name


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_output_dir(base_output: Path, proposal_date: date, client_name: str) -> Path:
    year = proposal_date.strftime("%Y")
    month = proposal_date.strftime("%m")
    client_folder = safe_name(client_name)
    return ensure_directory(base_output / year / month / client_folder)


def build_base_filename(numero: int, revisao: str, client_name: str, proposal_date: date) -> str:
    safe_client = safe_name(client_name)
    date_token = format_file_date(proposal_date)
    return f"PROPOSTA_COMERCIAL_N_{numero}_REV.{revisao}_{safe_client}_{date_token}"


def build_document_paths(
    base_output: Path,
    proposal_date: date,
    client_name: str,
    numero: int,
    revisao: str,
) -> tuple[Path, Path]:
    output_dir = build_output_dir(base_output=base_output, proposal_date=proposal_date, client_name=client_name)
    file_base = build_base_filename(
        numero=numero,
        revisao=revisao,
        client_name=client_name,
        proposal_date=proposal_date,
    )
    return output_dir / f"{file_base}.docx", output_dir / f"{file_base}.pdf"


def to_output_relative(path: Path, output_root: Path) -> str:
    return str(path.relative_to(output_root)).replace("\\", "/")


def upload_to_drive_placeholder(*_: object, **__: object) -> None:
    # Future integration point for Google Drive.
    return None
