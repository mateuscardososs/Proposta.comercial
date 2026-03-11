from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]


def _default_libreoffice_cmd() -> str:
    linux_soffice = Path("/usr/bin/soffice")
    if linux_soffice.exists():
        return str(linux_soffice)
    return "soffice"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AD Balancas e Engenharia - Propostas"
    database_url: str = Field(
        default_factory=lambda: f"sqlite:///{(BASE_DIR / 'propostas.db').as_posix()}"
    )
    template_doc_path: Path = BASE_DIR / "doc_templates" / "proposta_template.docx"
    output_dir: Path = BASE_DIR / "output"
    libreoffice_cmd: str = Field(default_factory=_default_libreoffice_cmd)
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_reload: bool = True
    default_km_value: float = 2.95


@lru_cache
def get_settings() -> Settings:
    return Settings()
