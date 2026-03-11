from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings


def _wait_for_database() -> int:
    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        print("[wait-for-db] SQLite detected, skipping wait.")
        return 0

    timeout = int(os.getenv("DB_WAIT_TIMEOUT", "90"))
    interval = float(os.getenv("DB_WAIT_INTERVAL", "2"))
    deadline = time.time() + timeout
    last_error: str | None = None

    while time.time() < deadline:
        try:
            engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("[wait-for-db] Database is ready.")
            return 0
        except Exception as exc:  # pragma: no cover - runtime infra check
            last_error = f"{type(exc).__name__}: {exc}"
            print(f"[wait-for-db] Waiting for database... ({last_error})")
            time.sleep(interval)

    print(f"[wait-for-db] Timeout after {timeout}s. Last error: {last_error}")
    return 1


if __name__ == "__main__":
    sys.exit(_wait_for_database())
