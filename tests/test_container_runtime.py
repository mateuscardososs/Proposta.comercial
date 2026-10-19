from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy.engine import URL

from scripts.container_runtime import (
    build_runtime_environment,
    container_database_url,
    filtered_runtime_settings,
)


def test_database_url_is_retargeted_to_existing_compose_service():
    result = container_database_url(
        "postgresql+psycopg://user:private-value@127.0.0.1:5433/propostas_db"
    )

    assert isinstance(result, URL)
    assert result.host == "db"
    assert result.port == 5432
    assert result.database == "propostas_db"
    assert result.username == "user"
    assert result.password == "private-value"


@pytest.mark.parametrize(
    "value",
    [
        "sqlite:////tmp/other.sqlite3",
        "postgresql+psycopg://user:pass@remote.invalid:5432/propostas_db",
        "postgresql+psycopg://user:pass@127.0.0.1:5433/other_db",
    ],
)
def test_database_url_rejects_non_local_or_wrong_database(value):
    with pytest.raises(ValueError):
        container_database_url(value)


def test_runtime_settings_allowlist_does_not_pass_secrets():
    result = filtered_runtime_settings(
        '{"EMAIL_SYNC_ENABLED": true, "EMAIL_SYNC_INTERVAL_SECONDS": 900, '
        '"EMAIL_IMAP_APP_PASSWORD": "secret", "GEMINI_API_KEY": "secret", '
        '"DATABASE_URL": "private"}'
    )

    assert result == {"EMAIL_SYNC_ENABLED": "true", "EMAIL_SYNC_INTERVAL_SECONDS": "900"}


def test_runtime_environment_preserves_provider_credentials_and_runtime_sync_settings():
    result = build_runtime_environment(
        {"GEMINI_API_KEY": "synthetic-secret", "GEMINI_MODEL": "configured-model"},
        database_url="postgresql+psycopg://user:private-value@127.0.0.1:5433/propostas_db",
        auth_secret="s" * 48,
        runtime_json='{"EMAIL_SYNC_ENABLED": true, "EMAIL_SYNC_INTERVAL_SECONDS": 900}',
        base_config="GEMINI_MODEL=synthetic-model\nEMAIL_PROVIDER=disabled\n",
        yahoo_config=(
            "EMAIL_PROVIDER=imap_yahoo\n"
            "EMAIL_IMAP_USERNAME=synthetic@example.test\n"
            "EMAIL_IMAP_APP_PASSWORD=synthetic-app-password\n"
        ),
    )

    assert result["LLM_PROVIDER"] == "gemini"
    assert result["GEMINI_API_KEY"] == "synthetic-secret"
    assert result["GEMINI_MODEL"] == "synthetic-model"
    assert result["EMAIL_PROVIDER"] == "imap_yahoo"
    assert result["EMAIL_IMAP_APP_PASSWORD"] == "synthetic-app-password"
    assert result["EMAIL_SYNC_ENABLED"] == "true"
    assert result["EMAIL_SYNC_INTERVAL_SECONDS"] == "900"
    assert result["AUTH_ENABLED"] == "true"
    assert result["DATABASE_URL"].endswith("@db:5432/propostas_db")
    assert result["VOICE_ENABLED"] == "true"
    assert result["TESSERACT_CMD"] == "/usr/bin/tesseract"


def test_runtime_environment_rejects_missing_session_secret():
    with pytest.raises(ValueError, match="chave privada de sessão"):
        build_runtime_environment(
            {}, database_url="postgresql://user:pass@db:5432/propostas_db",
            auth_secret="short", runtime_json="{}",
        )


def test_build_context_excludes_local_data_and_secrets():
    patterns = set(Path(".dockerignore").read_text(encoding="utf-8").splitlines())

    assert ".env" in patterns
    assert ".env.*" in patterns
    assert "local-data/" in patterns
    assert ".models/" in patterns
    assert "*.db" in patterns
    assert "*.dump" in patterns


def test_compose_reuses_the_existing_application_output_directory():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "- ./output:/app/data/output" in compose


def test_gitignore_covers_operational_databases_and_generated_documents():
    paths = (
        "propostas.db",
        "propostas_app/audit_tmp/audit.db",
        "propostas_app/audit_tmp/new-runtime.sqlite3",
        "output/generated-report.pdf",
        "output/generated-proposal.docx",
    )

    for path in paths:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", "--", path],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f"Runtime artifact is not ignored: {path}"


def _docker_compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


@pytest.mark.skipif(not _docker_compose_available(), reason="Docker Compose CLI indisponível")
def test_compose_requires_postgres_password_without_revealing_it(tmp_path):
    source = Path("docker-compose.yml").read_text(encoding="utf-8")
    match = re.search(r"(?m)^\s*POSTGRES_PASSWORD:\s*(\$\{[^}]+\})\s*$", source)
    assert match is not None

    compose_file = tmp_path / "compose.yml"
    compose_file.write_text(
        "services:\n  db:\n    image: postgres:16-alpine\n"
        f"    environment:\n      POSTGRES_PASSWORD: {match.group(1)}\n",
        encoding="utf-8",
    )
    env_file = tmp_path / "empty.env"
    env_file.write_text("", encoding="utf-8")
    command = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(compose_file),
        "config",
        "-q",
    ]

    without_password = dict(os.environ)
    without_password.pop("POSTGRES_PASSWORD", None)
    missing = subprocess.run(
        command,
        cwd=tmp_path,
        env=without_password,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert missing.returncode != 0
    assert "POSTGRES_PASSWORD" in missing.stderr

    with_password = dict(without_password, POSTGRES_PASSWORD="synthetic-compose-test-value")
    configured = subprocess.run(
        command,
        cwd=tmp_path,
        env=with_password,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert configured.returncode == 0, "Compose rejeitou uma senha sintética configurada."
    assert "synthetic-compose-test-value" not in configured.stdout + configured.stderr
