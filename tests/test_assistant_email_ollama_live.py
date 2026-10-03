from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.assistant.capabilities import CapabilityRegistry
from app.assistant.email.contracts import EmailMessageRecord
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


@pytest.mark.parametrize(
    ("prompt", "category", "period"),
    [
        ("Me diga quais emails têm solicitação de orçamento", "customer_quote_request", "week"),
        ("Tem algum e-mail sobre conta a pagar?", "accounts_payable", "week"),
        ("Quais e-mails pedem emissão de nota fiscal?", "invoice_request", "week"),
        ("O que chegou hoje?", None, "today"),
        ("O que chegou nesta semana?", None, "week"),
    ],
)
def test_real_ollama_routes_email_categories_and_periods_to_synthetic_reader(
    db, prompt: str, category: str | None, period: str
):
    capabilities = CapabilityRegistry(email_provider="synthetic")
    provider = OllamaProvider(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        model=MODEL,
        connect_timeout=3,
        read_timeout=90,
        capabilities=capabilities.provider_context(),
    )
    synthetic = [
        EmailMessageRecord(
            reference="synthetic-quote-today",
            thread_reference="synthetic-quote-thread",
            folder_role="inbox",
            sender="Cliente de teste <cliente@example.invalid>",
            recipients=("ad@example.invalid",),
            subject="Solicitação de orçamento de teste",
            received_at=NOW.replace(hour=8),
            seen=False,
            text="Solicitamos orçamento para inspeção. Mensagem sintética para teste.",
        ),
        EmailMessageRecord(
            reference="synthetic-ap-today",
            thread_reference="synthetic-ap-thread",
            folder_role="inbox",
            sender="Fornecedor de teste <financeiro@example.invalid>",
            recipients=("ad@example.invalid",),
            subject="Conta a pagar de teste",
            received_at=NOW.replace(hour=9),
            seen=True,
            text="Fatura sintética para validação da categoria conta a pagar.",
        ),
        EmailMessageRecord(
            reference="synthetic-invoice-week",
            thread_reference="synthetic-invoice-thread",
            folder_role="inbox",
            sender="Cliente de teste <cliente@example.invalid>",
            recipients=("ad@example.invalid",),
            subject="Solicitação de emissão de nota fiscal",
            received_at=NOW - timedelta(days=1),
            seen=False,
            text="Solicitamos emissão da nota fiscal referente ao serviço. Conteúdo sintético.",
        ),
    ]
    service = AssistantService(
        db,
        provider,
        now=lambda: NOW,
        email_reader=SyntheticEmailReader(messages=synthetic),
        capabilities=capabilities,
    )

    reply = service.handle_message(message=prompt, request_id=f"email-live-{category or period}")

    assert reply.kind == "text", reply.message
    assert reply.email_items, "A consulta real deveria apresentar evidência do leitor sintético."
    assert all(item["category"] == category for item in reply.email_items) if category else True
    if category == "customer_quote_request":
        assert {item["reference"] for item in reply.email_items} == {"synthetic-quote-today"}
    elif category == "accounts_payable":
        assert {item["reference"] for item in reply.email_items} == {"synthetic-ap-today"}
    elif category == "invoice_request":
        assert {item["reference"] for item in reply.email_items} == {"synthetic-invoice-week"}
    else:
        assert reply.consulted_interval is not None
