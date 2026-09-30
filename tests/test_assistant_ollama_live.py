from __future__ import annotations

import os
from datetime import date

import pytest

from app.assistant.contracts import TaskQueryCommand
from app.assistant.ollama import OllamaProvider
from app.assistant.provider import ProviderMessage


RUN_LIVE = os.getenv("RUN_OLLAMA_INTEGRATION") == "1"
MODEL = os.getenv("OLLAMA_MODEL", "").strip()

pytestmark = pytest.mark.skipif(
    not RUN_LIVE or not MODEL,
    reason="requer RUN_OLLAMA_INTEGRATION=1 e OLLAMA_MODEL ja instalado",
)


def test_real_ollama_classifies_read_only_task_query():
    provider = OllamaProvider(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        model=MODEL,
        connect_timeout=3,
        read_timeout=90,
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Quais tarefas e prazos eu tenho?")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert isinstance(command, TaskQueryCommand)
