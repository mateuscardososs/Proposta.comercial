"""Opt-in live smoke test. Never runs as part of the normal suite."""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.assistant.contracts import ConversationCommand
from app.assistant.gemini import GeminiProvider
from app.assistant.provider import ProviderMessage

_HAS_OPT_IN = os.getenv("RUN_GEMINI_SMOKE_TEST") == "1"
_HAS_KEY = bool(os.getenv("GEMINI_API_KEY", "").strip())
pytestmark = pytest.mark.skipif(
    not (_HAS_OPT_IN and _HAS_KEY),
    reason="requires RUN_GEMINI_SMOKE_TEST=1 and GEMINI_API_KEY",
)


def test_gemini_live_synthetic_text_smoke():
    provider = GeminiProvider(
        api_key=os.environ["GEMINI_API_KEY"],
        model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        connect_timeout=3,
        read_timeout=60,
    )

    result = provider.interpret(
        [ProviderMessage(role="user", content="Responda em português apenas: teste local confirmado.")],
        today=datetime.now(ZoneInfo("America/Recife")).date(),
        timezone="America/Recife",
        allowed_tools={"responder_conversa"},
    )

    assert isinstance(result, ConversationCommand)
    assert result.message.strip()
