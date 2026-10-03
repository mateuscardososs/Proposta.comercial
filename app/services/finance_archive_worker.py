from __future__ import annotations

import asyncio
import logging

from app.db import SessionLocal
from app.services.lancamento_service import archive_expired_lancamentos

logger = logging.getLogger(__name__)


def archive_in_worker() -> int:
    db = SessionLocal()
    try:
        return archive_expired_lancamentos(db)
    finally:
        db.close()


async def finance_archive_loop() -> None:
    """Apply eligible 30-day archival at startup and once per day."""
    while True:
        try:
            await asyncio.to_thread(archive_in_worker)
        except Exception as exc:  # Keep running; exception details may expose DB data.
            logger.warning("Financial archive sweep failed (%s)", type(exc).__name__)
        await asyncio.sleep(24 * 60 * 60)
