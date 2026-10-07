from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DATA = PROJECT_ROOT.parent / "local-data" / "adbalancas-8013"
PRIVATE_RUNTIME_DIR = LOCAL_DATA / "private"
DATABASE_URL_FILE = PRIVATE_RUNTIME_DIR / "database-url"
AUTH_SESSION_SECRET_FILE = PRIVATE_RUNTIME_DIR / "auth-session-secret"
RUNTIME_SETTINGS_FILE = PRIVATE_RUNTIME_DIR / "settings.json"
OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
DATABASE_HOST_PORT = 5433
CONTAINER_NAME = "adbalancas-app-8013"
SAFE_CONTAINER_SETTING_KEYS = frozenset(
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


def database_url_for_loopback(database_url: str, *, host_port: int = DATABASE_HOST_PORT) -> URL:
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise ValueError("8013 exige uma conexao PostgreSQL.")
    if url.database != "propostas_db":
        raise ValueError("A configuracao precisa apontar para propostas_db.")
    if url.host not in {"db", "localhost", "127.0.0.1"}:
        raise ValueError("O host atual do banco nao pertence a instancia local.")
    return url.set(host="127.0.0.1", port=host_port)


def runtime_environment(
    database_url: str,
    *,
    repository_root: Path = PROJECT_ROOT,
    ollama_model: str,
) -> dict[str, str]:
    local_data = repository_root.parent / "local-data" / "adbalancas-8013"
    voice_models = repository_root / ".models" / "assistant_voice"
    local_database_url = database_url_for_loopback(database_url).render_as_string(
        hide_password=False
    )
    return {
        "DATABASE_URL": local_database_url,
        "APP_ENV_FILE": str(repository_root / ".env"),
        "APP_HOST": "127.0.0.1",
        "APP_PORT": "8013",
        "APP_RELOAD": "false",
        "OUTPUT_DIR": str(local_data / "output"),
        "TEMPLATE_DOC_PATH": str(
            local_data / "doc_templates" / "proposta_template.docx"
        ),
        "OLLAMA_BASE_URL": OLLAMA_URL,
        "OLLAMA_MODEL": ollama_model,
        "VOICE_ENABLED": "true",
        "VOICE_MODEL_DIR": str(voice_models),
        "VOICE_WHISPER_MODEL": "small",
        "VOICE_WHISPER_DEVICE": "cpu",
        "VOICE_WHISPER_COMPUTE_TYPE": "int8",
        "VOICE_PIPER_MODEL_PATH": str(voice_models / "pt_BR-faber-medium.onnx"),
    }


def save_private_database_url(database_url: str, *, path: Path = DATABASE_URL_FILE) -> None:
    normalized = database_url_for_loopback(database_url).render_as_string(
        hide_password=False
    )
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as database_file:
            database_file.write(normalized)
            database_file.flush()
            os.fsync(database_file.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def safe_container_runtime_settings(environment: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in environment.items()
        if key in SAFE_CONTAINER_SETTING_KEYS
    }


def save_private_runtime_settings(
    settings: dict[str, str], *, path: Path = RUNTIME_SETTINGS_FILE
) -> None:
    safe_settings = safe_container_runtime_settings(settings)
    if not safe_settings.get("EMAIL_SYNC_MAILBOX_KEY"):
        raise RuntimeError("A chave de sincronizacao da caixa nao foi encontrada.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as settings_file:
            json.dump(safe_settings, settings_file)
            settings_file.flush()
            os.fsync(settings_file.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def read_private_runtime_settings(path: Path = RUNTIME_SETTINGS_FILE) -> dict[str, str]:
    metadata = path.stat()
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise RuntimeError("O arquivo privado de configuracao precisa ter permissao 0600.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("A configuracao privada local nao pode ser lida.") from exc
    settings = safe_container_runtime_settings(payload)
    if not settings.get("EMAIL_SYNC_MAILBOX_KEY"):
        raise RuntimeError("A chave de sincronizacao da caixa nao foi preservada.")
    return settings


def read_private_database_url(path: Path = DATABASE_URL_FILE) -> str:
    metadata = path.stat()
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise RuntimeError("O arquivo privado de conexao precisa ter permissao 0600.")
    value = path.read_text(encoding="utf-8").strip()
    parsed = make_url(value)
    if parsed.host != "127.0.0.1" or parsed.port != DATABASE_HOST_PORT:
        raise RuntimeError("A conexao privada nao esta restrita ao loopback local.")
    if parsed.database != "propostas_db":
        raise RuntimeError("A conexao privada nao aponta para propostas_db.")
    return value


def save_private_auth_session_secret(secret: str, *, path: Path = AUTH_SESSION_SECRET_FILE) -> None:
    if len(secret) < 32:
        raise ValueError("A chave de sessão precisa ter pelo menos 32 caracteres.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as secret_file:
            secret_file.write(secret)
            secret_file.flush()
            os.fsync(secret_file.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def read_private_auth_session_secret(path: Path = AUTH_SESSION_SECRET_FILE) -> str:
    metadata = path.stat()
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise RuntimeError("O arquivo privado da sessão precisa ter permissão 0600.")
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 32:
        raise RuntimeError("A chave privada de sessão não está configurada corretamente.")
    return value


def prepare_database_url_from_container() -> None:
    if DATABASE_URL_FILE.exists():
        raise RuntimeError("A configuracao privada ja existe; preservada sem sobrescrita.")
    code = (
        "from app.config import get_settings; "
        "print(get_settings().database_url, end='')"
    )
    try:
        result = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "python", "-c", code],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "Nao foi possivel obter a configuracao ativa do container 8013."
        ) from exc
    save_private_database_url(result.stdout)


def prepare_runtime_settings_from_container() -> None:
    if RUNTIME_SETTINGS_FILE.exists():
        raise RuntimeError("As configuracoes privadas ja existem; preservadas sem sobrescrita.")
    try:
        result = subprocess.run(
            ["docker", "inspect", CONTAINER_NAME],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        container = json.loads(result.stdout)[0]
        environment = {
            item.split("=", 1)[0]: item.split("=", 1)[1]
            for item in container["Config"]["Env"]
            if "=" in item
        }
    except (OSError, subprocess.SubprocessError, IndexError, KeyError, ValueError) as exc:
        raise RuntimeError(
            "Nao foi possivel ler a configuracao ativa nao secreta do container 8013."
        ) from exc
    save_private_runtime_settings(environment)


def installed_ollama_models() -> set[str]:
    try:
        with urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as response:
            payload = json.load(response)
    except (OSError, URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError("O Ollama local nao respondeu em 127.0.0.1:11434.") from exc
    return {str(model.get("name", "")) for model in payload.get("models", [])}


def verify_database(database_url: str) -> None:
    engine = create_engine(database_url, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            if connection.scalar(text("select current_database()")) != "propostas_db":
                raise RuntimeError("A conexao nao chegou ao banco propostas_db.")
    except Exception as exc:
        raise RuntimeError(
            "Nao foi possivel validar propostas_db em 127.0.0.1:5433."
        ) from exc
    finally:
        engine.dispose()
