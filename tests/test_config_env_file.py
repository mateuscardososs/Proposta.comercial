from __future__ import annotations

from app.config import get_settings


def test_get_settings_can_load_an_explicit_local_environment_file(tmp_path, monkeypatch):
    local_env = tmp_path / ".env.yahoo.local"
    local_env.write_text(
        "EMAIL_PROVIDER=imap_yahoo\n"
        "EMAIL_IMAP_USERNAME=conta@example.com\n"
        "EMAIL_IMAP_APP_PASSWORD=fake-app-password\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_ENV_FILE", str(local_env))
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    monkeypatch.delenv("EMAIL_IMAP_USERNAME", raising=False)
    monkeypatch.delenv("EMAIL_IMAP_APP_PASSWORD", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.email_provider == "imap_yahoo"
    assert settings.email_imap_username == "conta@example.com"
    assert settings.email_imap_app_password.get_secret_value() == "fake-app-password"

    get_settings.cache_clear()
