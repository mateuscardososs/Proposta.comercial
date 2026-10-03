from __future__ import annotations

import asyncio
import threading

import pytest

from app.assistant.voice.provider import VoiceBusyError, VoiceTimeoutError


def test_executor_keeps_event_loop_responsive_and_rejects_third_job():
    from app.assistant.voice.runtime import BoundedVoiceExecutor

    async def scenario():
        executor = BoundedVoiceExecutor(name="test-voice", max_pending=1)
        started = threading.Event()
        release = threading.Event()

        def blocking(value):
            started.set()
            release.wait(timeout=2)
            return value

        first = asyncio.create_task(executor.submit(lambda: blocking("first"), timeout=2))
        await asyncio.to_thread(started.wait, 1)
        second = asyncio.create_task(executor.submit(lambda: "second", timeout=2))
        await asyncio.sleep(0)

        heartbeat = asyncio.create_task(asyncio.sleep(0.01, result="alive"))
        assert await heartbeat == "alive"
        with pytest.raises(VoiceBusyError):
            await executor.submit(lambda: "third", timeout=2)

        release.set()
        assert await first == "first"
        assert await second == "second"
        executor.shutdown()

    asyncio.run(scenario())


def test_timeout_does_not_free_capacity_while_worker_is_still_running():
    from app.assistant.voice.runtime import BoundedVoiceExecutor

    async def scenario():
        executor = BoundedVoiceExecutor(name="test-timeout", max_pending=0)
        started = threading.Event()
        release = threading.Event()

        def blocking():
            started.set()
            release.wait(timeout=2)
            return "late"

        timed_out = asyncio.create_task(executor.submit(blocking, timeout=0.01))
        await asyncio.to_thread(started.wait, 1)
        with pytest.raises(VoiceTimeoutError):
            await timed_out
        with pytest.raises(VoiceBusyError):
            await executor.submit(lambda: "overlap", timeout=1)

        release.set()
        for _ in range(100):
            await asyncio.sleep(0.01)
            try:
                result = await executor.submit(lambda: "after", timeout=1)
            except VoiceBusyError:
                continue
            assert result == "after"
            break
        else:
            pytest.fail("executor did not release capacity after worker completion")
        executor.shutdown()

    asyncio.run(scenario())
