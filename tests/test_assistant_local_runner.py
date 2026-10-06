from __future__ import annotations

from datetime import date

import pytest

from app.models import Client, Task, User
from scripts import run_assistant_8013_local
from scripts.validate_assistant_local import SYNTHETIC_CASES, seed_synthetic_data


def test_validation_runner_defines_all_requested_synthetic_cases():
    assert [case.number for case in SYNTHETIC_CASES] == list(range(1, 21))
    assert SYNTHETIC_CASES[0].message == "O que tenho para fazer hoje?"
    assert SYNTHETIC_CASES[-1].conversation == "full-flow"


def test_validation_seed_uses_only_fictitious_isolated_records(db):
    seed_synthetic_data(db, today=date(2026, 9, 30))

    assert {client.razao_social for client in db.query(Client).all()} == {
        "Alfa Industria",
        "Alfa Servicos",
        "Empresa Beta",
    }
    assert {user.nome for user in db.query(User).all()} == {"Ana", "Carlos"}
    assert db.query(Task).count() >= 4
    assert any(task.prazo == date(2026, 9, 29) for task in db.query(Task).all())


def test_gemini_runtime_does_not_require_a_running_ollama(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    def ollama_must_not_be_checked():
        pytest.fail("O runtime Gemini não deve consultar o Ollama.")

    monkeypatch.setattr(
        run_assistant_8013_local,
        "installed_ollama_models",
        ollama_must_not_be_checked,
    )

    selected = run_assistant_8013_local._select_installed_model(
        {"LLM_PROVIDER": "gemini"}
    )

    assert selected == run_assistant_8013_local.DEFAULT_OLLAMA_MODEL
