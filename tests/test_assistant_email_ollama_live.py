from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.assistant.capabilities import CapabilityRegistry
from app.assistant.email.synthetic import SyntheticEmailReader, synthetic_messages
from app.assistant.ollama import OllamaProvider
from app.assistant.service import AssistantService
from app.models import AssistantMessage, Task


RUN_LIVE = os.getenv("RUN_OLLAMA_INTEGRATION") == "1"
MODEL = os.getenv("OLLAMA_MODEL", "").strip()
NOW = datetime(2026, 10, 1, 10, 0, tzinfo=ZoneInfo("America/Recife"))

pytestmark = pytest.mark.skipif(
    not RUN_LIVE or not MODEL,
    reason="requer RUN_OLLAMA_INTEGRATION=1 e OLLAMA_MODEL ja instalado",
)


def test_real_ollama_summarizes_synthetic_email_only_after_tool_evidence(db):
    capabilities = CapabilityRegistry(email_provider="synthetic")
    provider = OllamaProvider(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        model=MODEL,
        connect_timeout=3,
        read_timeout=90,
        capabilities=capabilities.provider_context(),
    )
    service = AssistantService(
        db,
        provider,
        now=lambda: NOW,
        email_reader=SyntheticEmailReader(messages=synthetic_messages(NOW)),
        capabilities=capabilities,
    )

    reply = service.handle_message(
        message="Quais e-mails chegaram hoje e qual precisa de atenção primeiro?",
        request_id="email-live-ollama-1",
    )

    assert reply.kind == "text"
    assert reply.consulted_interval == "01/10/2026 00:00 a 01/10/2026 10:00"
    assert reply.email_items[0]["reference"] == "syn-in-001"
    assert {item["reference"] for item in reply.email_items}.issubset(
        {"syn-in-001", "syn-in-003"}
    )
    assert "Alfa" in reply.message
    stored = db.query(AssistantMessage).filter_by(reply_to_request_id="email-live-ollama-1").one()
    assert stored.details_json["executed_tools"] == ["consultar_emails"]
    assert db.query(Task).count() == 0


def test_real_ollama_routes_indirect_pending_reply_question_to_email_tool(db):
    capabilities = CapabilityRegistry(email_provider="synthetic")
    provider = OllamaProvider(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        model=MODEL,
        connect_timeout=3,
        read_timeout=90,
        capabilities=capabilities.provider_context(),
    )
    service = AssistantService(
        db,
        provider,
        now=lambda: NOW,
        email_reader=SyntheticEmailReader(messages=synthetic_messages(NOW)),
        capabilities=capabilities,
    )

    reply = service.handle_message(
        message="Ficou alguém esperando meu retorno?",
        request_id="email-live-ollama-indirect-reply",
    )

    assert reply.kind == "text"
    assert reply.consulted_interval == "28/09/2026 00:00 a 01/10/2026 10:00"
    assert reply.email_items
    assert all(item["awaiting_reply"] == "yes" for item in reply.email_items)
    stored = (
        db.query(AssistantMessage)
        .filter_by(reply_to_request_id="email-live-ollama-indirect-reply")
        .one()
    )
    assert stored.details_json["executed_tools"] == ["consultar_emails"]
    assert db.query(Task).count() == 0
