from __future__ import annotations

import getpass
import os
import re
import secrets
import stat

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from scripts.assistant_8013_runtime import (
    AUTH_SESSION_SECRET_FILE,
    PROJECT_ROOT,
    read_private_auth_session_secret,
    read_private_database_url,
    save_private_auth_session_secret,
    verify_database,
)


def _prompt_user() -> tuple[str, str, str]:
    name = input("Nome do administrador inicial: ").strip()
    email = input("E-mail de acesso: ").strip()
    if not name or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise RuntimeError("Nome ou e-mail inválido; nenhum cadastro foi criado.")
    password = getpass.getpass("Senha (mínimo 12 caracteres; entrada oculta): ")
    confirmation = getpass.getpass("Confirme a senha: ")
    if password != confirmation:
        raise RuntimeError("As senhas não coincidem; nenhum cadastro foi criado.")
    if len(password) < 12:
        raise RuntimeError("A senha precisa ter pelo menos 12 caracteres.")
    return name, email, password


def _ensure_secret_file() -> str:
    if AUTH_SESSION_SECRET_FILE.exists():
        return read_private_auth_session_secret()
    secret = secrets.token_urlsafe(48)
    save_private_auth_session_secret(secret)
    return secret


def _validate_auth_flow(session_factory, secret: str, email: str, password: str) -> None:
    from app.config import Settings
    from app.security.auth import LoginRateLimiter, configure_authentication
    from app.security.routes import router as auth_router

    test_app = FastAPI()
    test_app.state.templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates_web"))
    test_app.state.auth_session_factory = session_factory
    test_app.state.auth_login_window_seconds = 900
    test_app.state.login_rate_limiter = LoginRateLimiter()
    configure_authentication(
        test_app,
        Settings(
            auth_enabled=True,
            auth_session_secret=secret,
            auth_session_max_age_seconds=3600,
        ),
        session_factory=session_factory,
        rate_limiter=test_app.state.login_rate_limiter,
    )
    test_app.include_router(auth_router)

    @test_app.get("/auth-check")
    def auth_check():
        return {"authenticated": True}

    with TestClient(test_app) as client:
        login_page = client.get("/login")
        match = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text)
        if login_page.status_code != 200 or not match:
            raise RuntimeError("A página de login não passou na validação local.")
        response = client.post(
            "/login",
            data={"email": email, "password": password, "csrf_token": match.group(1), "next": "/auth-check"},
            headers={"Origin": str(client.base_url).rstrip("/")},
            follow_redirects=True,
        )
        if response.status_code != 200 or response.json() != {"authenticated": True}:
            raise RuntimeError("O teste local de login não foi aprovado; não inicie a 8013.")


def main() -> int:
    database_url = read_private_database_url()
    verify_database(database_url)
    os.environ["DATABASE_URL"] = database_url
    os.environ["AUTH_ENABLED"] = "true"
    os.environ["APP_ENV_FILE"] = str(PROJECT_ROOT / ".env")

    from app.db import SessionLocal, engine
    from app.models import User
    from app.security.auth import assert_auth_ready
    from app.security.passwords import hash_password

    if not engine.dialect.name == "postgresql":
        raise RuntimeError("O bootstrap da 8013 exige PostgreSQL; nenhuma conta foi criada.")
    name, email, password = _prompt_user()
    secret = _ensure_secret_file()

    with SessionLocal() as db:
        active_argon_user = db.query(User.id).filter(User.ativo.is_(True), User.senha_hash.like("$argon2id$%")).first()
        if active_argon_user:
            raise RuntimeError("Já existe uma conta ativa compatível; bootstrap encerrado sem alterações.")
        if db.query(User.id).filter(User.email == email).first():
            raise RuntimeError("Esse e-mail já existe no cadastro; use outro e-mail, sem alteração de conta existente.")
        user = User(
            nome=name,
            cargo="Administrador inicial",
            email=email,
            senha_hash=hash_password(password),
            ativo=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

    assert_auth_ready(SessionLocal)
    _validate_auth_flow(SessionLocal, secret, email, password)
    del password

    metadata = AUTH_SESSION_SECRET_FILE.stat()
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise RuntimeError("A chave de sessão não tem permissões privadas; não inicie a aplicação.")
    print(f"Administrador inicial cadastrado e fluxo local de login validado (registro {user_id}).")
    print("A chave de sessão foi guardada fora do Git com permissão 0600; nenhum segredo foi exibido.")
    print("Agora a instância 8013 pode ser iniciada pelo launcher local.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1) from None
