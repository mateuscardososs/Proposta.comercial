"""Opt-in conversational smoke test against a real local Ollama instance."""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.assistant.ollama import OllamaProvider
from app.assistant.service import AssistantService
from app.db import Base, ensure_service_history_guards_for_engine
from app.models import Client, ServiceCall, ServiceEvent


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_OLLAMA_LIVE") != "1" or not os.getenv("OLLAMA_MODEL"),
    reason="Defina RUN_OLLAMA_LIVE=1 e OLLAMA_MODEL para usar o Ollama real local.",
)


def test_real_ollama_routes_synthetic_inspection_through_confirmed_service_flow(tmp_path):
    db_path = tmp_path / "assistant-service-live.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    ensure_service_history_guards_for_engine(engine)
    with Session(engine) as db:
        db.add(Client(razao_social="Alfa Serviços Sintética"))
        db.commit()
        provider = OllamaProvider(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            model=os.environ["OLLAMA_MODEL"], connect_timeout=3,
            read_timeout=float(os.getenv("OLLAMA_READ_TIMEOUT", "90")),
        )
        assistant = AssistantService(
            db, provider,
            now=lambda: datetime(2026, 10, 2, 9, tzinfo=ZoneInfo("America/Recife")),
        )
        draft = assistant.handle_message(
            message="Registre minha visita à Alfa Serviços Sintética: fiz só uma inspeção da balança, sem reparo.",
            request_id="ollama-live-service-inspection",
        )
        assert draft.kind == "confirmation", draft.message
        assert draft.fields.get("evento") == "Inspeção"
        assert db.query(ServiceCall).count() == 0
        assert db.query(ServiceEvent).count() == 0
        saved = assistant.confirm_action(draft.action_id, draft.confirmation_token)
        assert saved.kind == "success"
        event = db.query(ServiceEvent).one()
        assert event.event_type == "inspection"
        assert db.query(ServiceCall).one().execution_status == "not_started"
    engine.dispose()
