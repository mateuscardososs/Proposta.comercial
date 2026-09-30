from __future__ import annotations

import pytest

from app.assistant.voice.provider import (
    NoSpeechError,
    SuspiciousTranscriptionError,
    TranscriptionResult,
)


def _result(text: str, **changes) -> TranscriptionResult:
    values = {
        "text": text,
        "language": "pt",
        "language_probability": 0.95,
        "no_speech_probability": 0.05,
        "average_log_probability": -0.2,
    }
    values.update(changes)
    return TranscriptionResult(**values)


@pytest.mark.parametrize("text", ["", "   ", "...", "!? -"])
def test_validate_transcription_rejects_empty_or_punctuation(text):
    from app.assistant.voice.policy import validate_transcription

    with pytest.raises(NoSpeechError):
        validate_transcription(_result(text))


def test_validate_transcription_rejects_high_no_speech_probability():
    from app.assistant.voice.policy import validate_transcription

    with pytest.raises(NoSpeechError):
        validate_transcription(_result("crie uma tarefa", no_speech_probability=0.75))


@pytest.mark.parametrize("text", ["sim", "pode criar", "confirmo", "cancela"])
def test_short_controls_require_strong_portuguese_evidence(text):
    from app.assistant.voice.policy import validate_transcription

    with pytest.raises(SuspiciousTranscriptionError):
        validate_transcription(_result(text, language_probability=0.40))


def test_validate_transcription_returns_trimmed_safe_text():
    from app.assistant.voice.policy import validate_transcription

    assert validate_transcription(_result("  Na verdade, depois de amanha.  ")) == (
        "Na verdade, depois de amanha."
    )
