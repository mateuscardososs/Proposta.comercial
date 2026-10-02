from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from app.assistant.email.provider import EmailReader
from app.assistant.email.sync import EmailSyncService
from app.config import Settings
from app.db import SessionLocal


def run_sync_in_worker(
    settings: Settings, reader_factory: Callable[[], EmailReader | None]
) -> None:
    """One bounded sync in a worker thread; never blocks FastAPI's event loop."""
    db = SessionLocal()
    try:
        reader = reader_factory()
        if reader is None:
            # No mailbox credentials or provider configuration. Nothing was queried.
            return
        EmailSyncService(
            db,
            reader,
            mailbox_key=settings.email_sync_mailbox_key,
            timezone=settings.assistant_timezone,
            lookback_days=settings.email_sync_lookback_days,
            batch_size=settings.email_sync_batch_size,
            provider_name=settings.email_provider,
            auto_task_creation_enabled=settings.email_auto_task_creation_enabled,
        ).sync_once(now=datetime.now(ZoneInfo(settings.assistant_timezone)))
    finally:
        db.close()


async def email_sync_loop(
    settings: Settings,
    reader_factory: Callable[[], EmailReader | None],
) -> None:
    """Periodic, single-flight, bounded sync. Waits before the first run."""
    while True:
        await asyncio.sleep(settings.email_sync_interval_seconds)
        await asyncio.to_thread(run_sync_in_worker, settings, reader_factory)
