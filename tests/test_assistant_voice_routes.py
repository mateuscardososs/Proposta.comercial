from __future__ import annotations

from io import BytesIO
import math
import struct
import wave

from fastapi.testclient import TestClient

from app.assistant.voice.provider import (
    SynthesizedAudio,
    TranscriptionResult,
    VoiceUnavailableError,
)
from app.main import app


class FakeTranscriber:
    def __init__(self, result: TranscriptionResult | None = None) -> None:
        self.result = result or TranscriptionResult(
            text="Crie uma tarefa para revisar o relatorio amanha.",
            language="pt",
            language_probability=0.98,
            no_speech_probability=0.03,
            average_log_probability=-0.2,
            transcription_seconds=0.12,
        )
        self.calls = 0

    def transcribe(self, path):
        self.calls += 1
        assert path.is_file()
        return self.result


class FakeSynthesizer:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def synthesize(self, text):
        self.texts.append(text)
        return SynthesizedAudio(
            data=_wav_bytes(duration_seconds=0.2),
            media_type="audio/wav",
            synthesis_seconds=0.04,
        )


def _wav_bytes(*, duration_seconds: float = 0.5, sample_rate: int = 16000) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for index in range(int(duration_seconds * sample_rate)):
            sample = int(5000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        wav_file.writeframes(bytes(frames))
    return buffer.getvalue()


def test_voice_status_keeps_text_available_when_components_are_missing():
    with TestClient(app) as client:
        response = client.get("/api/assistant/voice/status")

    assert response.status_code == 200
    assert response.json()["text_available"] is True
    assert "transcription_available" in response.json()
    assert "synthesis_available" in response.json()


def test_transcription_route_validates_audio_and_returns_safe_text():
    from app.routers.assistant import get_voice_transcriber

    transcriber = FakeTranscriber()
    app.dependency_overrides[get_voice_transcriber] = lambda: transcriber
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/assistant/voice/transcriptions",
                files={"audio": ("speech.wav", _wav_bytes(), "audio/wav")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["text"].startswith("Crie uma tarefa")
    assert response.json()["audio_duration_seconds"] == 0.5
    assert response.json()["transcription_seconds"] == 0.12
    assert transcriber.calls == 1


def test_transcription_route_rejects_invalid_audio_before_model():
    from app.routers.assistant import get_voice_transcriber

    transcriber = FakeTranscriber()
    app.dependency_overrides[get_voice_transcriber] = lambda: transcriber
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/assistant/voice/transcriptions",
                files={"audio": ("fake.webm", b"not audio", "audio/webm")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert transcriber.calls == 0
    assert "audio valido" in response.json()["detail"]


def test_transcription_route_rejects_oversized_upload_before_model():
    from app.routers.assistant import get_voice_transcriber

    transcriber = FakeTranscriber()
    app.dependency_overrides[get_voice_transcriber] = lambda: transcriber
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/assistant/voice/transcriptions",
                files={"audio": ("large.wav", b"0" * (8 * 1024 * 1024 + 1), "audio/wav")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 413
    assert transcriber.calls == 0


def test_transcription_route_removes_raw_temporary_audio(tmp_path, monkeypatch):
    import app.routers.assistant as assistant_router

    transcriber = FakeTranscriber()
    monkeypatch.setattr(assistant_router.tempfile, "tempdir", str(tmp_path))
    app.dependency_overrides[assistant_router.get_voice_transcriber] = lambda: transcriber
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/assistant/voice/transcriptions",
                files={"audio": ("speech.wav", _wav_bytes(), "audio/wav")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert list(tmp_path.iterdir()) == []


def test_transcription_route_reports_local_model_failure():
    from app.routers.assistant import get_voice_transcriber

    class FailingTranscriber:
        def transcribe(self, _path):
            raise VoiceUnavailableError("O modelo local de transcricao falhou.")

    app.dependency_overrides[get_voice_transcriber] = FailingTranscriber
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/assistant/voice/transcriptions",
                files={"audio": ("speech.wav", _wav_bytes(), "audio/wav")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "modelo local" in response.json()["detail"]


def test_speech_route_returns_wav_without_interpreting_again():
    from app.routers.assistant import get_voice_synthesizer

    synthesizer = FakeSynthesizer()
    app.dependency_overrides[get_voice_synthesizer] = lambda: synthesizer
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/assistant/voice/speech",
                json={
                    "text": "Tarefa #5 criada com sucesso no quadro.",
                    "kind": "success",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content.startswith(b"RIFF")
    assert synthesizer.texts == ["Tarefa #5 criada com sucesso no quadro."]
    assert float(response.headers["x-synthesis-seconds"]) == 0.04
