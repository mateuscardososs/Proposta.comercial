from __future__ import annotations

import hashlib
import secrets
from urllib.parse import urlsplit

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.models import User
from app.security.auth import LoginRateLimiter, new_csrf_token
from app.security.passwords import hash_password, is_argon2id_hash, verify_password

router = APIRouter(tags=["authentication"])
_DUMMY_HASH = hash_password("not-a-real-user-password")


def _limiter(request: Request) -> LoginRateLimiter:
    return request.app.state.login_rate_limiter


def _attempt_key(request: Request, email: str) -> str:
    client = request.client.host if request.client else "unknown"
    return hashlib.sha256(client.encode()).hexdigest()


def _safe_next(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme
        or parsed.netloc
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or "\r" in value
        or "\n" in value
    ):
        return "/"
    return value


@router.get("/login", name="login")
def login_page(request: Request, next: str = "/"):
    if "csrf_token" not in request.session:
        request.session["csrf_token"] = new_csrf_token()
    return request.app.state.templates.TemplateResponse(
        "login.html",
        {"request": request, "csrf_token": request.session["csrf_token"], "next": _safe_next(next), "error": ""},
    )


@router.post("/login", name="login_submit")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    next: str = Form("/"),
):
    limiter = _limiter(request)
    key = _attempt_key(request, email)
    if limiter.is_limited(key):
        return HTMLResponse(
            "<main><h1>Muitas tentativas</h1><p>Aguarde antes de tentar novamente.</p><a href='/login'>Voltar</a></main>",
            status_code=429,
            headers={"Retry-After": str(request.app.state.auth_login_window_seconds)},
        )
    expected = request.session.get("csrf_token", "")
    if not expected or not secrets.compare_digest(str(expected), csrf_token):
        return HTMLResponse("Solicitação inválida. Atualize a página e tente novamente.", status_code=403)

    with request.app.state.auth_session_factory() as db:
        user = db.query(User).filter(User.email == email.strip()).first()
        has_valid_account = bool(user and user.ativo and is_argon2id_hash(user.senha_hash))
        encoded = user.senha_hash if has_valid_account else _DUMMY_HASH
        password_matches = verify_password(password, encoded)
        if not has_valid_account or not password_matches:
            limiter.record_failure(key)
            return request.app.state.templates.TemplateResponse(
                "login.html",
                {"request": request, "csrf_token": expected, "next": _safe_next(next), "error": "E-mail ou senha inválidos."},
                status_code=401,
            )
        user_id = user.id

    limiter.clear(key)
    request.session.clear()
    request.session["auth_user_id"] = user_id
    request.session["csrf_token"] = new_csrf_token()
    return RedirectResponse(_safe_next(next), status_code=303)


@router.post("/logout", name="logout")
def logout(request: Request, csrf_token: str = Form(...)):
    expected = request.session.get("csrf_token", "")
    if not expected or not secrets.compare_digest(str(expected), csrf_token):
        return HTMLResponse("Solicitação inválida. Atualize a página e tente novamente.", status_code=403)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
