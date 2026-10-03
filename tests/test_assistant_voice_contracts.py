from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_transcription_result_rejects_impossible_probabilities():
    from app.assistant.voice.provider import TranscriptionResult

    with pytest.raises(ValidationError):
        TranscriptionResult(
            text="sim",
            language="pt",
            language_probability=1.5,
            no_speech_probability=0.1,
            average_log_probability=-0.2,
        )


def test_voice_settings_have_cpu_safe_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    settings = Settings(_env_file=None)

    assert settings.voice_enabled is True
    assert settings.voice_whisper_model == "small"
    assert settings.voice_whisper_device == "cpu"
    assert settings.voice_whisper_compute_type == "int8"
    assert settings.voice_max_upload_bytes == 8 * 1024 * 1024
    assert settings.voice_max_duration_seconds == 30
    assert settings.voice_silence_ms == 1800
    assert settings.voice_min_duration_seconds == 0.25
    assert isinstance(settings.voice_model_dir, Path)


def test_synthesized_audio_requires_nonempty_wav_bytes():
    from app.assistant.voice.provider import SynthesizedAudio

    with pytest.raises(ValidationError):
        SynthesizedAudio(data=b"", media_type="audio/wav", synthesis_seconds=0.1)
