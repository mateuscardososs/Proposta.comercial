from __future__ import annotations

import re


DETAILS_SUFFIX = "Os detalhes estao na tela."
ERROR_SPEECH = "Nao consegui concluir a resposta. Veja os detalhes na tela."


def _remove_visual_markup(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"[`*_~]", "", text)
    text = re.sub(r"(?<!\w)#\d+\b", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return " ".join(text.strip().split())


def spoken_text(text: str, kind: str, *, max_characters: int = 300) -> str:
    if kind == "error" and re.search(
        r"\b(ollama|http|timeout|traceback|exception|ollama_model|modelo configurado)\b",
        text,
        flags=re.IGNORECASE,
    ):
        return ERROR_SPEECH
    clean_text = _remove_visual_markup(text)
    original_lines = [line.strip() for line in text.splitlines() if line.strip()]
    task_lines = [line for line in original_lines if line.startswith("-")]
    if task_lines:
        count = len(task_lines)
        noun = "tarefa" if count == 1 else "tarefas"
        return f"Encontrei {count} {noun}. {DETAILS_SUFFIX}"
    if len(clean_text) <= max_characters:
        return clean_text

    first_sentence = clean_text.split(".", 1)[0].strip()
    prefix_limit = max_characters - len(DETAILS_SUFFIX) - 1
    prefix = first_sentence[:prefix_limit].rstrip(" ,;:-")
    if prefix:
        return f"{prefix}. {DETAILS_SUFFIX}"[:max_characters]
    return DETAILS_SUFFIX[:max_characters]
