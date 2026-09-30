from pathlib import Path


def test_voice_validation_environment_is_fully_isolated(tmp_path):
    from scripts.validate_assistant_voice_local import isolation_environment

    repository = Path(__file__).resolve().parents[1]
    environment = isolation_environment(
        root=tmp_path,
        model_dir=repository / ".models" / "assistant_voice",
        ollama_model="test-model",
    )

    assert environment["DATABASE_URL"] == f"sqlite:///{tmp_path / 'validation.sqlite3'}"
    assert Path(environment["OUTPUT_DIR"]).is_relative_to(tmp_path)
    assert Path(environment["TEMPLATE_DOC_PATH"]).is_relative_to(tmp_path)
    assert Path(environment["VOICE_MODEL_DIR"]).is_relative_to(repository)
    assert environment["OLLAMA_BASE_URL"] == "http://127.0.0.1:11434"
    assert environment["APP_HOST"] == "127.0.0.1"
    assert "propostas.db" not in " ".join(environment.values())
