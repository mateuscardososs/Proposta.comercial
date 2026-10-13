from __future__ import annotations

import json
import os

import pytest

from scripts.bootstrap_first_admin import docker_bootstrap_environment


def test_docker_bootstrap_loads_existing_runtime_secrets_without_logging_them(tmp_path, capsys):
    secret_dir = tmp_path / "secrets"
    config_dir = tmp_path / "config"
    secret_dir.mkdir()
    config_dir.mkdir()
    secret_values = {
        "database-url": "postgresql+psycopg://user:synthetic@127.0.0.1:5433/propostas_db",
        "auth-session-secret": "synthetic-session-secret-value-012345678901",
        "runtime-settings.json": json.dumps(
            {"EMAIL_SYNC_ENABLED": True, "EMAIL_SYNC_INTERVAL_SECONDS": 900}
        ),
    }
    for name, value in secret_values.items():
        path = secret_dir / name
        path.write_text(value, encoding="utf-8")
        path.chmod(0o600)
    (config_dir / ".env").write_text("LLM_PROVIDER=gemini\n", encoding="utf-8")
    (config_dir / ".env.yahoo.local").write_text(
        "EMAIL_PROVIDER=imap_yahoo\nEMAIL_IMAP_USERNAME=synthetic@example.test\n",
        encoding="utf-8",
    )

    environment = docker_bootstrap_environment(
        os.environ,
        secret_dir=secret_dir,
        config_dir=config_dir,
    )

    assert environment["AUTH_ENABLED"] == "true"
    assert environment["LLM_PROVIDER"] == "gemini"
    assert environment["EMAIL_PROVIDER"] == "imap_yahoo"
    assert environment["EMAIL_SYNC_ENABLED"] == "true"
    assert environment["EMAIL_SYNC_INTERVAL_SECONDS"] == "900"
    assert environment["AUTH_SESSION_SECRET"] == secret_values["auth-session-secret"]
    assert environment["DATABASE_URL"].endswith("@db:5432/propostas_db")
    assert secret_values["auth-session-secret"] not in capsys.readouterr().out


def test_docker_bootstrap_rejects_session_secret_with_permissive_permissions(tmp_path):
    secret_dir = tmp_path / "secrets"
    config_dir = tmp_path / "config"
    secret_dir.mkdir()
    config_dir.mkdir()
    (secret_dir / "database-url").write_text(
        "postgresql+psycopg://user:synthetic@127.0.0.1:5433/propostas_db",
        encoding="utf-8",
    )
    secret_path = secret_dir / "auth-session-secret"
    secret_path.write_text("synthetic-session-secret-value-012345678901", encoding="utf-8")
    secret_path.chmod(0o644)
    (secret_dir / "runtime-settings.json").write_text("{}", encoding="utf-8")
    (config_dir / ".env").write_text("", encoding="utf-8")
    (config_dir / ".env.yahoo.local").write_text("", encoding="utf-8")

    with pytest.raises(RuntimeError, match="permissão 0600"):
        docker_bootstrap_environment({}, secret_dir=secret_dir, config_dir=config_dir)
