from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.db import Base, SessionLocal, engine, ensure_schema_compatibility
from app.models import User
from app.routers import clients, imports, pages, proposals, users
from app.services.storage_service import ensure_directory

settings = get_settings()
ensure_directory(settings.output_dir)
ensure_directory(settings.template_doc_path.parent)

app = FastAPI(title=settings.app_name)


@app.get("/healthz", tags=["health"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility()
    ensure_directory(settings.output_dir)
    ensure_directory(settings.template_doc_path.parent)
    _ensure_default_user()


def _ensure_default_user() -> None:
    with SessionLocal() as db:
        exists = db.query(User).first()
        if exists:
            return
        default_user = User(
            nome="Usuario Padrao",
            cargo="Comercial",
            email="comercial@adbalancas.local",
            senha_hash=hashlib.sha256("123456".encode("utf-8")).hexdigest(),
            ativo=True,
        )
        db.add(default_user)
        db.commit()


templates_dir = Path(__file__).resolve().parent / "templates_web"
app.state.templates = Jinja2Templates(directory=str(templates_dir))

app.mount("/output", StaticFiles(directory=str(settings.output_dir)), name="output")

app.include_router(pages.router)
app.include_router(clients.router)
app.include_router(users.router)
app.include_router(proposals.router)
app.include_router(imports.router)
