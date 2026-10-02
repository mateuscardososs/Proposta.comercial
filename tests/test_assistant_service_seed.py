from __future__ import annotations

import pytest

from scripts.seed_assistant_service_validation import ALLOWED_DB, validate_seed_target


def test_synthetic_seed_requires_explicit_opt_in_and_exact_isolated_database():
    url = f"sqlite:////{ALLOWED_DB.as_posix().lstrip('/')}"
    assert validate_seed_target(url, "1") == ALLOWED_DB.resolve(strict=False)
    with pytest.raises(RuntimeError, match="autorizar"):
        validate_seed_target(url, "")
    with pytest.raises(RuntimeError, match="isolado"):
        validate_seed_target("sqlite:////tmp/operational.sqlite3", "1")
    with pytest.raises(RuntimeError, match="SQLite"):
        validate_seed_target("postgresql://example", "1")
