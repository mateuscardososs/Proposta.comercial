from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    technical_report_template_path: Path = BASE_DIR / "doc_templates" / "relatorio_tecnico_template.docx"
    technical_report_pdf_converter_image: str = ""
    output_dir: Path = BASE_DIR / "output"
    tesseract_cmd: str = ""
    tesseract_data_dir: str = ""
    libreoffice_cmd: str = Field(default_factory=_default_libreoffice_cmd)
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_reload: bool = True
    auth_enabled: bool = True
    auth_session_secret: SecretStr = SecretStr("")
    auth_session_max_age_seconds: int = Field(default=8 * 60 * 60, ge=1, le=7 * 24 * 60 * 60)
    auth_login_attempts: int = Field(default=5, ge=1, le=20)
    auth_login_window_seconds: int = Field(default=900, ge=60, le=86400)
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
    email_sync_enabled: bool = False
    email_auto_task_creation_enabled: bool = False
    email_sync_interval_seconds: int = Field(default=900, ge=60, le=86400)
    email_sync_lookback_days: int = Field(default=30, ge=1, le=90)
    email_sync_batch_size: int = Field(default=30, ge=1, le=100)
    email_sync_mailbox_key: str = "primary"
    today_lookahead_days: int = Field(default=7, ge=1, le=31)
    llm_provider: Literal["ollama", "gemini"] = "gemini"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_image_model: str = "gemini-nano-banana-2.1"
    gemini_connect_timeout: float = 3.0
    gemini_read_timeout: float = 60.0
    promotion_max_reference_image_bytes: int = Field(default=8 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)
    promotion_smtp_host: str = ""
    promotion_smtp_port: int = Field(default=587, ge=1, le=65535)
    promotion_smtp_username: str = ""
    promotion_smtp_password: SecretStr = SecretStr("")
    promotion_smtp_from_email: str = ""
    promotion_smtp_from_name: str = "AD Balanças"
    promotion_smtp_starttls: bool = True
    promotion_smtp_use_ssl: bool = False
    promotion_smtp_timeout_seconds: float = Field(default=15.0, ge=1, le=120)
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
