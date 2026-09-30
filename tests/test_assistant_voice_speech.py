from __future__ import annotations

def test_spoken_text_summarizes_task_lists():
    from app.assistant.voice.speech import spoken_text

    assert spoken_text(
        "Encontrei estas tarefas:\n- Preparar relatorio\n- Ligar para cliente",
        "text",
    ) == "Encontrei 2 tarefas. Os detalhes estao na tela."


def test_spoken_text_preserves_short_success():
    from app.assistant.voice.speech import spoken_text

    assert spoken_text("Tarefa #12 criada com sucesso no quadro.", "success") == (
        "Tarefa #12 criada com sucesso no quadro."
    )


def test_spoken_text_truncates_long_detail_safely():
    from app.assistant.voice.speech import spoken_text

    long_text = "Resultado detalhado. " + ("Informacao adicional. " * 30)

    result = spoken_text(long_text, "text", max_characters=180)

    assert len(result) <= 180
    assert result.endswith("Os detalhes estao na tela.")
