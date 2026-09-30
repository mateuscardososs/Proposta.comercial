from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import threading
from typing import TypeVar

from app.assistant.voice.provider import VoiceBusyError, VoiceTimeoutError


ResultT = TypeVar("ResultT")


class BoundedVoiceExecutor:
    """Run one heavy voice job at a time with a small, explicit backlog."""

    def __init__(self, *, name: str, max_pending: int = 1) -> None:
        if max_pending < 0:
            raise ValueError("max_pending must be non-negative")
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)
        self._capacity = threading.BoundedSemaphore(1 + max_pending)

    async def submit(self, function: Callable[[], ResultT], *, timeout: float) -> ResultT:
        if not self._capacity.acquire(blocking=False):
            raise VoiceBusyError("O processamento de voz esta ocupado. Aguarde e tente novamente.")

        try:
            future = self._executor.submit(function)
        except Exception:
            self._capacity.release()
            raise

        # A timeout stops waiting, not the native worker. Capacity is therefore
        # released only when the worker has actually finished.
        future.add_done_callback(lambda _future: self._capacity.release())
        wrapped = asyncio.wrap_future(future)
        try:
            return await asyncio.wait_for(asyncio.shield(wrapped), timeout=timeout)
        except TimeoutError as exc:
            raise VoiceTimeoutError(
                "O processamento de voz excedeu o tempo limite. Tente novamente."
            ) from exc

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
