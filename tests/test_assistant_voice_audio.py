from __future__ import annotations

import math
import struct
import wave

import pytest

from app.assistant.voice.provider import InvalidAudioError


def _write_wav(path, *, duration_seconds: float, sample_rate: int = 16000) -> None:
    frame_count = int(duration_seconds * sample_rate)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            sample = int(5000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        wav_file.writeframes(bytes(frames))


def test_inspect_audio_decodes_real_duration(tmp_path):
    from app.assistant.voice.audio import inspect_audio

    audio_path = tmp_path / "speech.wav"
    _write_wav(audio_path, duration_seconds=1.0)

    metadata = inspect_audio(
        audio_path,
        min_duration_seconds=0.25,
        max_duration_seconds=30,
    )

    assert metadata.duration_seconds == pytest.approx(1.0, abs=0.02)
    assert metadata.sample_rate == 16000
    assert metadata.channels == 1


def test_inspect_audio_rejects_invalid_container(tmp_path):
    from app.assistant.voice.audio import inspect_audio

    path = tmp_path / "fake.webm"
    path.write_bytes(b"not an audio file")

    with pytest.raises(InvalidAudioError, match="audio valido"):
        inspect_audio(path, min_duration_seconds=0.25, max_duration_seconds=30)


def test_inspect_audio_rejects_too_short_audio(tmp_path):
    from app.assistant.voice.audio import inspect_audio

    audio_path = tmp_path / "short.wav"
    _write_wav(audio_path, duration_seconds=0.1)

    with pytest.raises(InvalidAudioError, match="curto"):
        inspect_audio(audio_path, min_duration_seconds=0.25, max_duration_seconds=30)


def test_inspect_audio_stops_when_decoded_duration_exceeds_limit(tmp_path):
    from app.assistant.voice.audio import inspect_audio

    audio_path = tmp_path / "long.wav"
    _write_wav(audio_path, duration_seconds=1.2)

    with pytest.raises(InvalidAudioError, match="1 segundo"):
        inspect_audio(audio_path, min_duration_seconds=0.25, max_duration_seconds=1)
