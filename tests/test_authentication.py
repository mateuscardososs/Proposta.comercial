from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import User
from app.routers import assistant, clients, pages, users
from app.security.auth import LoginRateLimiter, configure_authentication
from app.security.passwords import hash_password, verify_password
from app.security.routes import router as auth_router

_PASSWORD = "Synthetic-Password-Only-42!"
_EMAIL = "auth-user@example.test"


def _make_app(tmp_path, *, max_age=3600, max_attempts=5):
    from app.config import Settings

    for folder in ("output", "assets"):
        (tmp_path / folder).mkdir()
    (tmp_path / "output" / "private-report.txt").write_text("synthetic private file")
    (tmp_path / "assets" / "private.css").write_text("synthetic protected asset")
    app = FastAPI()
    app.state.templates = Jinja2Templates(
        directory=str(Path(__file__).parents[1] / "app" / "templates_web")
    )
    configure_authentication(
        app,
        Settings(
            auth_enabled=True,
            auth_session_secret="synthetic-session-key-that-is-long-enough-for-tests",
            auth_session_max_age_seconds=max_age,
            auth_login_attempts=max_attempts,
            auth_login_window_seconds=60,
        ),
        session_factory=SessionLocal,
        rate_limiter=LoginRateLimiter(),
    )
    app.state.auth_session_factory = SessionLocal
    app.state.auth_login_window_seconds = 60
    app.state.login_rate_limiter = LoginRateLimiter(max_attempts=max_attempts, window_seconds=60)
    app.include_router(auth_router)
    app.include_router(pages.router)
    app.include_router(clients.router)
    app.include_router(users.router)
    app.include_router(assistant.router)
    app.mount("/output", StaticFiles(directory=tmp_path / "output"), name="output")
    app.mount("/assets", StaticFiles(directory=tmp_path / "assets"), name="assets")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


def _create_user(db, *, email=_EMAIL, password=_PASSWORD, active=True):
    user = User(
        nome="Operador Sintético",
        cargo="Operação",
        email=email,
        senha_hash=hash_password(password),
        ativo=active,
    )
    db.add(user)
    db.commit()
    return user


def _csrf_token(response):
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match, "Login form must render a CSRF token"
    return match.group(1)


def _login(client, *, email=_EMAIL, password=_PASSWORD):
    page = client.get("/login")
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": _csrf_token(page)},
        headers={"Origin": str(client.base_url).rstrip("/")},
        follow_redirects=False,
    )


def test_passwords_are_argon2id_and_verify_only_the_matching_value():
    encoded = hash_password(_PASSWORD)

    assert encoded.startswith("$argon2id$")
    assert encoded != _PASSWORD
    assert verify_password(_PASSWORD, encoded)
    assert not verify_password("wrong password", encoded)


def test_short_password_is_rejected_before_hashing():
    from pydantic import ValidationError

    from app.schemas import UserCreate

    with pytest.raises(ValidationError):
        UserCreate(nome="Operador", email="short@example.test", senha="short")


def test_login_success_sets_httponly_lax_expiring_cookie_and_allows_existing_flows(db, tmp_path):
    _create_user(db)
    app = _make_app(tmp_path)
    client = TestClient(app)

    response = _login(client)
    cookie_header = response.headers["set-cookie"].casefold()

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "adbalancas_session=" in cookie_header
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header
    assert "max-age=3600" in cookie_header
    assert client.get("/web/assistente").status_code == 200
    assert client.get("/api/assistant/voice/status").status_code == 200
    assert client.get("/web/clients").status_code == 200
    assert client.get("/api/clients/").status_code == 200


def test_anonymous_access_is_limited_to_login_and_health(db, tmp_path):
    app = _make_app(tmp_path)
    client = TestClient(app)

    assert client.get("/login").status_code == 200
    assert client.get("/healthz").status_code == 200
    assert client.get("/web/clients", follow_redirects=False).status_code == 302
    assert client.get("/api/clients/").status_code == 401
    assert client.get("/api/assistant/capabilities").status_code == 401
    assert client.get("/api/assistant/voice/status").status_code == 401
    assert client.post("/api/assistant/voice/speech").status_code == 403
    assert client.get("/assets/private.css", follow_redirects=False).status_code == 302
    assert client.get("/output/private-report.txt", follow_redirects=False).status_code == 302
    assert client.get("/openapi.json", follow_redirects=False).status_code == 302


def test_application_startup_does_not_create_a_default_user(db, monkeypatch):
    from app.main import app
    from app.main import settings as app_settings

    monkeypatch.setattr(app_settings, "email_sync_enabled", False)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
    assert db.query(User).count() == 0


def test_invalid_credentials_are_generic_and_do_not_create_a_session(db, tmp_path):
    _create_user(db)
    client = TestClient(_make_app(tmp_path))
    response = _login(client, password="incorrect password")

    assert response.status_code == 401
    assert "e-mail ou senha" in response.text.casefold()
    assert "active" not in response.text.casefold()
    assert client.get("/web/clients", follow_redirects=False).status_code == 302


def test_repeated_invalid_login_attempts_are_rate_limited(db, tmp_path):
    _create_user(db)
    client = TestClient(_make_app(tmp_path, max_attempts=2))
    assert _login(client, password="incorrect password").status_code == 401
    assert _login(client, password="incorrect password").status_code == 401
    assert _login(client, password="incorrect password").status_code == 429


def test_inactive_user_cannot_login(db, tmp_path):
    _create_user(db, active=False)
    client = TestClient(_make_app(tmp_path))

    response = _login(client)

    assert response.status_code == 401
    assert client.get("/api/clients/").status_code == 401


def test_logout_clears_session_and_returns_to_login(db, tmp_path):
    _create_user(db)
    client = TestClient(_make_app(tmp_path))
    assert _login(client).status_code == 303
    page = client.get("/login")

    response = client.post(
        "/logout",
        data={"csrf_token": _csrf_token(page)},
        headers={"Origin": str(client.base_url).rstrip("/")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert client.get("/web/clients", follow_redirects=False).status_code == 302


def test_expired_session_is_rejected(db, tmp_path):
    _create_user(db)
    client = TestClient(_make_app(tmp_path, max_age=1))
    assert _login(client).status_code == 303
    time.sleep(1.1)

    response = client.get("/web/clients", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("/login")


def test_disabled_user_session_is_invalidated_on_next_request(db, tmp_path):
    user = _create_user(db)
    client = TestClient(_make_app(tmp_path))
    assert _login(client).status_code == 303
    user.ativo = False
    db.commit()

    response = client.get("/api/clients/")

    assert response.status_code == 401


def test_unsafe_requests_require_same_origin_and_api_csrf_token(db, tmp_path):
    _create_user(db)
    client = TestClient(_make_app(tmp_path))
    assert _login(client).status_code == 303
    page = client.get("/login")
    token = _csrf_token(page)

    cross_origin = client.post(
        "/api/clients/",
        json={"razao_social": "Cliente sintético"},
        headers={"Origin": "https://attacker.invalid", "X-CSRF-Token": token},
    )
    no_api_token = client.post(
        "/api/clients/",
        json={"razao_social": "Cliente sintético"},
        headers={"Origin": str(client.base_url).rstrip("/")},
    )
    valid = client.post(
        "/api/clients/",
        json={"razao_social": "Cliente sintético"},
        headers={"Origin": str(client.base_url).rstrip("/"), "X-CSRF-Token": token},
    )

    assert cross_origin.status_code == 403
    assert no_api_token.status_code == 403
    assert valid.status_code == 201


def test_direct_document_and_asset_downloads_require_a_valid_session(db, tmp_path):
    _create_user(db)
    client = TestClient(_make_app(tmp_path))
    assert client.get("/output/private-report.txt", follow_redirects=False).status_code == 302
    assert _login(client).status_code == 303

    assert client.get("/output/private-report.txt").text == "synthetic private file"
    assert client.get("/assets/private.css").text == "synthetic protected asset"
