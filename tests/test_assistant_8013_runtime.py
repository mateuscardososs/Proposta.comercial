from pathlib import Path

from sqlalchemy.engine import make_url


def test_8013_runtime_uses_loopback_database_and_voice_components():
    from scripts.assistant_8013_runtime import runtime_environment

    environment = runtime_environment(
        "postgresql+psycopg://operator:secret@db:5432/propostas_db",
        repository_root=Path("/project"),
        ollama_model="qwen3:4b-instruct-2507-q4_K_M",
    )

    database = make_url(environment["DATABASE_URL"])
    assert database.host == "127.0.0.1"
    assert database.port == 5433
    assert database.database == "propostas_db"
    assert environment["APP_HOST"] == "127.0.0.1"
    assert environment["APP_PORT"] == "8013"
    assert environment["VOICE_ENABLED"] == "true"
    assert environment["OLLAMA_BASE_URL"] == "http://127.0.0.1:11434"
    assert environment["OLLAMA_MODEL"] == "qwen3:4b-instruct-2507-q4_K_M"


def test_8013_runtime_rejects_non_project_database_url():
    import pytest

    from scripts.assistant_8013_runtime import runtime_environment

    with pytest.raises(ValueError, match="propostas_db"):
        runtime_environment(
            "postgresql+psycopg://operator:secret@db:5432/other_db",
            repository_root=Path("/project"),
            ollama_model="qwen3:4b-instruct-2507-q4_K_M",
        )


def test_runtime_settings_copy_only_non_secret_email_options():
    from scripts.assistant_8013_runtime import safe_container_runtime_settings

    settings = safe_container_runtime_settings(
        {
            "EMAIL_PROVIDER": "imap_yahoo",
            "EMAIL_SYNC_ENABLED": "true",
            "EMAIL_SYNC_INTERVAL_SECONDS": "900",
            "EMAIL_AUTO_TASK_CREATION_ENABLED": "true",
            "EMAIL_SYNC_MAILBOX_KEY": "adbalancas-piloto-20261002",
            "EMAIL_IMAP_USERNAME": "private-user",
            "EMAIL_IMAP_APP_PASSWORD": "private-password",
        }
    )

    assert settings["EMAIL_SYNC_ENABLED"] == "true"
    assert settings["EMAIL_SYNC_INTERVAL_SECONDS"] == "900"
    assert settings["EMAIL_SYNC_MAILBOX_KEY"] == "adbalancas-piloto-20261002"
    assert "EMAIL_IMAP_USERNAME" not in settings
    assert "EMAIL_IMAP_APP_PASSWORD" not in settings
