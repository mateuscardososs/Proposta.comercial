from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import sessionmaker
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Match

from app.models import User
from app.security.passwords import is_argon2id_hash


class LoginRateLimiter:
    """Process-local throttle. Keys are hashed and never logged."""

    def __init__(self, *, max_attempts: int = 5, window_seconds: int = 900):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def is_limited(self, key: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            attempts = self._attempts[key]
            self._prune(attempts, current)
            return len(attempts) >= self.max_attempts

    def record_failure(self, key: str, *, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        with self._lock:
            attempts = self._attempts[key]
            self._prune(attempts, current)
            attempts.append(current)

    def clear(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def _prune(self, attempts: deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()


def _same_origin(request: Request) -> bool:
    candidate_value = request.headers.get("origin") or request.headers.get("referer")
    if not candidate_value:
        return False
    candidate = urlsplit(candidate_value)
    return candidate.scheme == request.url.scheme and candidate.netloc == request.url.netloc


class AuthenticationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, session_factory: sessionmaker, rate_limiter: LoginRateLimiter):
        super().__init__(app)
        self.session_factory = session_factory

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        path = request.url.path
        if path == "/healthz" and request.method in {"GET", "HEAD"}:
            return await call_next(request)
        if path == "/login" and request.method in {"GET", "HEAD", "POST"}:
            if request.method == "POST" and not self._csrf_valid(request, require_header=False):
                return JSONResponse({"detail": "Falha na validação de segurança da solicitação."}, status_code=403)
            return await call_next(request)

        if not any(route.matches(request.scope)[0] is not Match.NONE for route in request.app.router.routes):
            return await call_next(request)

        if (
            request.method not in {"GET", "HEAD", "OPTIONS", "TRACE"}
            and not self._csrf_valid(request, require_header=path.startswith("/api/"))
        ):
            return JSONResponse({"detail": "Falha na validação de segurança da solicitação."}, status_code=403)

        user_id = request.session.get("auth_user_id")
        if not isinstance(user_id, int):
            return self._unauthorized(request)
        if "csrf_token" not in request.session:
            request.session["csrf_token"] = secrets.token_urlsafe(32)

        with self.session_factory() as db:
            user = db.query(User).filter(User.id == user_id, User.ativo.is_(True)).first()
            if user is None or not is_argon2id_hash(user.senha_hash):
                request.session.clear()
                return self._unauthorized(request)
            request.state.user = user
            return await call_next(request)

    @staticmethod
    def _csrf_valid(request: Request, *, require_header: bool) -> bool:
        if not _same_origin(request):
            return False
        expected = request.session.get("csrf_token")
        supplied = request.headers.get("x-csrf-token")
        if not supplied and not require_header:
            # Form writes use strict Origin/Referer validation and SameSite=Lax.
            return True
        return bool(expected and supplied and hmac.compare_digest(str(expected), supplied))

    @staticmethod
    def _unauthorized(request: Request):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Autenticação necessária."}, status_code=401)
        return RedirectResponse(url=f"/login?next={request.url.path}", status_code=302)


def configure_authentication(
    app: FastAPI,
    settings,
    *,
    session_factory: sessionmaker,
    rate_limiter: LoginRateLimiter | None = None,
) -> LoginRateLimiter | None:
    if not settings.auth_enabled:
        return None
    secret = settings.auth_session_secret.get_secret_value()
    if len(secret) < 32:
        raise RuntimeError("AUTH_SESSION_SECRET precisa ter pelo menos 32 caracteres.")
    limiter = rate_limiter or LoginRateLimiter(
        max_attempts=settings.auth_login_attempts,
        window_seconds=settings.auth_login_window_seconds,
    )
    app.add_middleware(AuthenticationMiddleware, session_factory=session_factory, rate_limiter=limiter)
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie="adbalancas_session",
        max_age=settings.auth_session_max_age_seconds,
        same_site="lax",
        https_only=False,
        path="/",
    )
    return limiter


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def assert_auth_ready(session_factory: sessionmaker) -> None:
    with session_factory() as db:
        ready = db.query(User.id).filter(User.ativo.is_(True), User.senha_hash.like("$argon2id$%")).first()
    if ready is None:
        raise RuntimeError(
            "Nenhum administrador ativo com senha Argon2id foi provisionado; execute o bootstrap interativo antes de iniciar a aplicação."
        )
