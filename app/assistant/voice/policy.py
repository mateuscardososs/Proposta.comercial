from __future__ import annotations

import re

from app.assistant.dates import normalize_text
from app.assistant.voice.provider import (
    NoSpeechError,
    SuspiciousTranscriptionError,
    TranscriptionResult,
)


SHORT_CONTROL_PHRASES = {
    "sim",
    "confirmo",
    "pode criar",
    "pode confirmar",
    "sim pode criar",
    "cancela",
    "cancelar",
    "nao cancela",
}


def validate_transcription(result: TranscriptionResult) -> str:
    text = result.text.strip()
    if not text or not re.search(r"[\w\d]", text, flags=re.UNICODE):
        raise NoSpeechError("Nao detectei uma fala compreensivel. Tente novamente.")
    if result.no_speech_probability >= 0.60:
        raise NoSpeechError("O trecho parece conter apenas silencio ou ruido.")

    normalized = " ".join(normalize_text(text).split())
    normalized = re.sub(r"[^a-z0-9 ]+", "", normalized).strip()
    if normalized in SHORT_CONTROL_PHRASES and (
        result.language not in {"pt", "pt-BR", "pt_BR"}
        or result.language_probability < 0.75
        or result.no_speech_probability > 0.25
        or result.average_log_probability < -0.80
    ):
        raise SuspiciousTranscriptionError(
            "Nao consegui confirmar essa resposta curta com seguranca. Fale novamente ou use os botoes."
        )
    return text
