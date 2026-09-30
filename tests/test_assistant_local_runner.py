from __future__ import annotations

from datetime import date

from app.models import Client, Task, User
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
