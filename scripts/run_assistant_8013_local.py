from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

from scripts.assistant_8013_runtime import (
    DATABASE_URL_FILE,
    DEFAULT_OLLAMA_MODEL,
    PROJECT_ROOT,
    installed_ollama_models,
    prepare_database_url_from_container,
    prepare_runtime_settings_from_container,
    read_private_database_url,
    read_private_runtime_settings,
    runtime_environment,
    verify_database,
)


def _load_local_configuration() -> dict[str, str]:
    base_values = dotenv_values(PROJECT_ROOT / ".env")
    for key, value in base_values.items():
        if value is not None:
            os.environ.setdefault(key, value)

    os.environ.update(read_private_runtime_settings())

    yahoo_file = PROJECT_ROOT / ".env.yahoo.local"
    if not yahoo_file.is_file():
        raise RuntimeError("Arquivo local .env.yahoo.local nao encontrado.")
    yahoo_values = dotenv_values(yahoo_file)
    for key in (
        "EMAIL_PROVIDER",
        "EMAIL_IMAP_USERNAME",
        "EMAIL_IMAP_APP_PASSWORD",
    ):
        value = yahoo_values.get(key)
        if value is not None:
            os.environ[key] = value
    return {key: value for key, value in base_values.items() if value is not None}


def _select_installed_model(base_values: dict[str, str]) -> str:
    configured = os.getenv("OLLAMA_MODEL") or base_values.get("OLLAMA_MODEL", "")
    installed = installed_ollama_models()
    if configured:
        if configured not in installed:
            raise RuntimeError(
                "O modelo configurado nao esta instalado no Ollama local."
            )
        return configured
    if DEFAULT_OLLAMA_MODEL in installed:
        return DEFAULT_OLLAMA_MODEL
    if len(installed) == 1:
        return next(iter(installed))
    raise RuntimeError(
        "Defina OLLAMA_MODEL para um modelo instalado localmente antes de iniciar."
    )


def _verify_voice_assets(environment: dict[str, str]) -> None:
    missing: list[str] = []
    for module in ("faster_whisper", "piper"):
        if importlib.util.find_spec(module) is None:
            missing.append(module)
    if not Path(environment["VOICE_PIPER_MODEL_PATH"]).is_file():
        missing.append("Piper pt-BR model")
    if not Path(environment["VOICE_MODEL_DIR"]).is_dir():
        missing.append("Whisper model cache")
    if missing:
        raise RuntimeError("Componentes de voz ausentes: " + ", ".join(missing))


def run() -> None:
    base_values = _load_local_configuration()
    database_url = read_private_database_url(DATABASE_URL_FILE)
    model = _select_installed_model(base_values)
    environment = runtime_environment(
        database_url,
        repository_root=PROJECT_ROOT,
        ollama_model=model,
    )
    _verify_voice_assets(environment)
    os.environ.update(environment)
    os.environ["APP_ENV_FILE"] = str(PROJECT_ROOT / ".env")

    from app.config import get_settings

    settings = get_settings()
    if not settings.voice_enabled:
        raise RuntimeError("VOICE_ENABLED nao foi aplicado a configuracao local.")
    if settings.email_provider != "imap_yahoo":
        raise RuntimeError("A configuracao Yahoo nao esta ativa na instancia 8013.")
    if not settings.email_sync_enabled or settings.email_sync_interval_seconds != 900:
        raise RuntimeError("A sincronizacao Yahoo nao preserva o intervalo de 900 s.")
    if not settings.email_auto_task_creation_enabled:
        raise RuntimeError("A criacao automatica existente esta desativada na configuracao.")

    verify_database(settings.database_url)
    print("8013 local: voz habilitada; PostgreSQL propostas_db validado em loopback.")
    print("Ollama local e modelo instalado validados; sem fallback externo.")

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8013,
        reload=False,
        access_log=False,
    )


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--prepare-database-url":
        try:
            prepare_database_url_from_container()
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
        print("Configuracao privada da 8013 preparada com permissao restrita.")
    elif len(sys.argv) == 2 and sys.argv[1] == "--prepare-runtime-settings":
        try:
            prepare_runtime_settings_from_container()
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
        print("Configuracoes locais nao secretas da 8013 preservadas.")
    elif len(sys.argv) == 1:
        try:
            run()
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
    else:
        print(
            "Uso: python scripts/run_assistant_8013_local.py "
            "[--prepare-database-url|--prepare-runtime-settings]",
            file=sys.stderr,
        )
        raise SystemExit(2)
