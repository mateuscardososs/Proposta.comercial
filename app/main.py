from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.assistant.email.worker import email_sync_loop
from app.config import get_settings
from app.db import Base, SessionLocal, engine, ensure_schema_compatibility
from app.models import User
from app.routers import (
    agenda,
    assistant,
    board,
    clients,
    email_review,
    financeiro,
    imports,
    pages,
    proposal_files,
    proposals,
    services,
    users,
)
from app.services.email_review_service import backfill_existing_email_drafts
from app.services.finance_archive_worker import finance_archive_loop
from app.services.storage_service import ensure_directory

settings = get_settings()
ensure_directory(settings.output_dir)
ensure_directory(settings.template_doc_path.parent)
ensure_directory(settings.technical_report_template_path.parent)

app = FastAPI(title=settings.app_name)
_email_sync_task: asyncio.Task[None] | None = None
_finance_archive_task: asyncio.Task[None] | None = None


@app.get("/healthz", tags=["health"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
async def on_startup() -> None:
    global _email_sync_task, _finance_archive_task
    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility()
    with SessionLocal() as db:
        backfill_existing_email_drafts(db)
    ensure_directory(settings.output_dir)
    ensure_directory(settings.template_doc_path.parent)
    ensure_directory(settings.technical_report_template_path.parent)
    _ensure_default_user()
    if _finance_archive_task is None:
        _finance_archive_task = asyncio.create_task(finance_archive_loop())
    if settings.email_sync_enabled and _email_sync_task is None:
        _email_sync_task = asyncio.create_task(email_sync_loop(settings, assistant.get_email_reader))


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global _email_sync_task, _finance_archive_task
    if _finance_archive_task is not None:
        _finance_archive_task.cancel()
        try:
            await _finance_archive_task
        except asyncio.CancelledError:
            pass
        _finance_archive_task = None
    if _email_sync_task is not None:
        _email_sync_task.cancel()
        try:
            await _email_sync_task
        except asyncio.CancelledError:
            pass
        _email_sync_task = None


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
static_dir = Path(__file__).resolve().parent / "static"
app.state.templates = Jinja2Templates(directory=str(templates_dir))

app.mount("/assets", StaticFiles(directory=str(static_dir)), name="assets")
app.mount("/output", StaticFiles(directory=str(settings.output_dir)), name="output")

app.include_router(proposal_files.router)
app.include_router(pages.router)
app.include_router(agenda.router)
app.include_router(clients.router)
app.include_router(users.router)
app.include_router(proposals.router)
app.include_router(imports.router)
app.include_router(board.router)
app.include_router(services.router)
app.include_router(financeiro.router)
app.include_router(email_review.router)
app.include_router(assistant.router)
