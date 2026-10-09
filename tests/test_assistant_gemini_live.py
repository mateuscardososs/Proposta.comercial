"""Opt-in live smoke test. Never runs as part of the normal suite."""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.assistant.contracts import ConversationCommand
from app.assistant.gemini import GeminiProvider
from app.assistant.provider import ProviderMessage
from app.config import get_settings

_HAS_OPT_IN = os.getenv("RUN_GEMINI_SMOKE_TEST") == "1"
_SETTINGS = get_settings() if _HAS_OPT_IN else None
_HAS_KEY = bool(
    _SETTINGS and _SETTINGS.gemini_api_key.get_secret_value().strip()
)
pytestmark = pytest.mark.skipif(
    not (_HAS_OPT_IN and _HAS_KEY),
    reason="requires RUN_GEMINI_SMOKE_TEST=1 and GEMINI_API_KEY",
)


def test_gemini_live_synthetic_text_smoke():
    provider = GeminiProvider(
        api_key=_SETTINGS.gemini_api_key.get_secret_value(),
        model=_SETTINGS.gemini_model,
        connect_timeout=_SETTINGS.gemini_connect_timeout,
        read_timeout=_SETTINGS.gemini_read_timeout,
    )

    result = provider.interpret(
        [ProviderMessage(role="user", content="Responda em português apenas: teste local confirmado.")],
        today=datetime.now(ZoneInfo("America/Recife")).date(),
        timezone="America/Recife",
        allowed_tools={"responder_conversa"},
    )

    assert isinstance(result, ConversationCommand)
    assert result.message.strip()
