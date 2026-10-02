from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]
VOICE_MODEL_DIR = BASE_DIR / ".models" / "assistant_voice"


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
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""
    ollama_connect_timeout: float = 3.0
    ollama_read_timeout: float = 60.0
    ollama_max_output_tokens: int = 180
    assistant_timezone: str = "America/Recife"
    assistant_context_messages: int = 12
    assistant_request_lease_seconds: int = 120
    assistant_max_tool_rounds: int = 2
    email_provider: str = "disabled"
    email_imap_host: str = "imap.mail.yahoo.com"
    email_imap_port: int = 993
    email_imap_username: str = ""
    email_imap_app_password: SecretStr = SecretStr("")
    email_imap_timeout_seconds: float = 10.0
    email_max_messages: int = 30
    email_cache_retention_days: int = 14
    email_body_preview_chars: int = 4000
    voice_enabled: bool = True
    voice_model_dir: Path = VOICE_MODEL_DIR
    voice_whisper_model: str = "small"
    voice_whisper_device: str = "cpu"
    voice_whisper_compute_type: str = "int8"
    voice_language: str = "pt"
    voice_whisper_initial_prompt: str = (
        "Crie uma tarefa. Pode criar. Sim, confirmo. Nao, cancela."
    )
    voice_piper_model_path: Path = VOICE_MODEL_DIR / "pt_BR-faber-medium.onnx"
    voice_piper_noise_scale: float | None = None
    voice_piper_noise_w_scale: float | None = None
    voice_max_upload_bytes: int = 8 * 1024 * 1024
    voice_min_duration_seconds: float = 0.25
    voice_max_duration_seconds: float = 30.0
    voice_transcription_timeout_seconds: float = 60.0
    voice_synthesis_timeout_seconds: float = 30.0
    voice_silence_ms: int = 1800
    voice_idle_timeout_seconds: int = 120


@lru_cache
def get_settings() -> Settings:
    env_file = os.getenv("APP_ENV_FILE", ".env") or ".env"
    return Settings(_env_file=env_file)
