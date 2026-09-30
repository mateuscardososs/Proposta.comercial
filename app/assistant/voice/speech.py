from __future__ import annotations


DETAILS_SUFFIX = "Os detalhes estao na tela."


def spoken_text(text: str, kind: str, *, max_characters: int = 300) -> str:
    clean_text = " ".join(text.strip().split())
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
