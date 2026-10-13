"""Prepare private container configuration and start the app after DB readiness."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping
from io import StringIO
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

DATABASE_URL_FILE = Path("/run/secrets/database-url")
AUTH_SECRET_FILE = Path("/run/secrets/auth-session-secret")
RUNTIME_SETTINGS_FILE = Path("/run/secrets/runtime-settings.json")
BASE_CONFIG_FILE = Path("/run/local-config/.env")
YAHOO_CONFIG_FILE = Path("/run/local-config/.env.yahoo.local")
SAFE_RUNTIME_KEYS = frozenset(
    {
        "ASSISTANT_TIMEZONE",
        "EMAIL_SYNC_ENABLED",
        "EMAIL_AUTO_TASK_CREATION_ENABLED",
        "EMAIL_SYNC_INTERVAL_SECONDS",
        "EMAIL_SYNC_LOOKBACK_DAYS",
        "EMAIL_SYNC_BATCH_SIZE",
        "EMAIL_SYNC_MAILBOX_KEY",
        "EMAIL_MAX_MESSAGES",
        "EMAIL_CACHE_RETENTION_DAYS",
        "EMAIL_BODY_PREVIEW_CHARS",
        "EMAIL_IMAP_TIMEOUT_SECONDS",
        "EMAIL_IMAP_HOST",
        "EMAIL_IMAP_PORT",
    }
)


def container_database_url(value: str) -> URL:
    try:
        parsed = make_url(value)
    except Exception as exc:
        raise ValueError("A conexão privada ao PostgreSQL não tem formato válido.") from exc
    if not parsed.drivername.startswith("postgresql") or parsed.database != "propostas_db":
        raise ValueError("A aplicação exige a conexão PostgreSQL local propostas_db.")
    if parsed.host not in {"127.0.0.1", "localhost", "db"} or parsed.port not in {5432, 5433}:
        raise ValueError("A conexão PostgreSQL não pertence ao serviço local.")
    return parsed.set(host="db", port=5432)


def filtered_runtime_settings(raw: str) -> dict[str, str]:
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise ValueError("As configurações locais não têm formato válido.") from exc
    if not isinstance(value, dict):
        raise TypeError("As configurações locais não têm formato válido.")
    return {
        key: str(item).lower() if isinstance(item, bool) else str(item)
        for key, item in value.items()
        if key in SAFE_RUNTIME_KEYS and isinstance(item, (str, int, float, bool))
    }


def _dotenv_environment(raw: str) -> dict[str, str]:
    try:
        value = dotenv_values(stream=StringIO(raw))
    except (ValueError, OSError) as exc:
        raise ValueError("A configuração local não pode ser carregada.") from exc
    return {key: item for key, item in value.items() if item is not None}


def build_runtime_environment(
    current: Mapping[str, str], *, database_url: str, auth_secret: str,
    runtime_json: str, base_config: str = "", yahoo_config: str = "",
) -> dict[str, str]:
    if len(auth_secret) < 32:
        raise ValueError("A chave privada de sessão não está configurada corretamente.")
    parsed = container_database_url(database_url)
    result = dict(current)
    result.update(_dotenv_environment(base_config))
    yahoo = _dotenv_environment(yahoo_config)
    for key in ("EMAIL_PROVIDER", "EMAIL_IMAP_USERNAME", "EMAIL_IMAP_APP_PASSWORD"):
        if key in yahoo:
            result[key] = yahoo[key]
    result.update(filtered_runtime_settings(runtime_json))
    result.update(
        {
            "DATABASE_URL": parsed.render_as_string(hide_password=False),
            "AUTH_SESSION_SECRET": auth_secret,
            "AUTH_ENABLED": "true",
            "APP_ENV_FILE": "/dev/null",
            "APP_HOST": "0.0.0.0",
            "APP_PORT": "8000",
            "APP_RELOAD": "false",
            "LLM_PROVIDER": "gemini",
            "VOICE_ENABLED": "true",
            "VOICE_MODEL_DIR": "/app/.models/assistant_voice",
            "VOICE_WHISPER_DEVICE": "cpu",
            "VOICE_WHISPER_COMPUTE_TYPE": "int8",
            "VOICE_LANGUAGE": "pt",
            "VOICE_PIPER_MODEL_PATH": "/app/.models/assistant_voice/pt_BR-faber-medium.onnx",
            "HF_HUB_OFFLINE": "1",
            "TESSERACT_CMD": "/usr/bin/tesseract",
            "TESSERACT_DATA_DIR": "/usr/share/tesseract-ocr/5/tessdata",
            "OUTPUT_DIR": "/app/data/output",
            "TEMPLATE_DOC_PATH": "/app/data/doc_templates/proposta_template.docx",
            "TECHNICAL_REPORT_TEMPLATE_PATH": "/app/doc_templates/relatorio_tecnico_template.docx",
        }
    )
    return result


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"Arquivo privado de runtime indisponível: {path.name}.") from exc


def _wait_for_database(database_url: str, *, timeout: int, interval: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        engine = None
        try:
            engine = create_engine(database_url, pool_pre_ping=True)
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            print("[container] PostgreSQL local está disponível.", flush=True)
            return True
        except Exception as exc:  # noqa: BLE001 - never print the connection URL.
            print(f"[container] aguardando PostgreSQL ({type(exc).__name__}).", flush=True)
            time.sleep(interval)
        finally:
            if engine is not None:
                engine.dispose()
    return False


def main() -> int:
    try:
        environment = build_runtime_environment(
            os.environ,
            database_url=_read(DATABASE_URL_FILE),
            auth_secret=_read(AUTH_SECRET_FILE),
            runtime_json=_read(RUNTIME_SETTINGS_FILE),
            base_config=_read(BASE_CONFIG_FILE),
            yahoo_config=_read(YAHOO_CONFIG_FILE),
        )
    except (RuntimeError, ValueError) as exc:
        print(f"[container] configuração inválida: {exc}", file=sys.stderr)
        return 2

    timeout = int(environment.get("DB_WAIT_TIMEOUT", "90"))
    interval = float(environment.get("DB_WAIT_INTERVAL", "2"))
    if not _wait_for_database(environment["DATABASE_URL"], timeout=timeout, interval=interval):
        print("[container] PostgreSQL não ficou disponível no prazo configurado.", file=sys.stderr)
        return 1
    os.execve(sys.executable, [sys.executable, "/app/run.py"], environment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
