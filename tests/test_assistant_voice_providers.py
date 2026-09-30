from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from io import BytesIO
import wave

import pytest


def test_installed_faster_whisper_can_decode_valid_wav(tmp_path):
    pytest.importorskip("faster_whisper")
    from faster_whisper.audio import decode_audio

    audio_path = tmp_path / "compatibility.wav"
    with wave.open(str(audio_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\x00\x00" * 8000)

    samples = decode_audio(str(audio_path))

    assert samples.shape == (8000,)


class FakeWhisperModel:
    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, path, **options):
        self.calls += 1
        assert Path(path).name == "speech.wav"
        assert options["language"] == "pt"
        assert options["beam_size"] == 1
        assert options["vad_filter"] is True
        assert options["initial_prompt"] == (
            "Crie uma tarefa. Pode criar. Sim, confirmo. Nao, cancela."
        )
        segments = [
            SimpleNamespace(text=" Pode", no_speech_prob=0.05, avg_logprob=-0.2),
            SimpleNamespace(text=" criar.", no_speech_prob=0.15, avg_logprob=-0.4),
        ]
        info = SimpleNamespace(language="pt", language_probability=0.96)
        return iter(segments), info


def test_faster_whisper_loads_once_and_returns_evidence(tmp_path):
    from app.assistant.voice.faster_whisper import FasterWhisperTranscriber

    loaded = []
    fake_model = FakeWhisperModel()

    def loader(**options):
        loaded.append(options)
        return fake_model

    transcriber = FasterWhisperTranscriber(
        model_name="small",
        cache_dir=tmp_path / "models",
        device="cpu",
        compute_type="int8",
        language="pt",
        initial_prompt="Crie uma tarefa. Pode criar. Sim, confirmo. Nao, cancela.",
        model_loader=loader,
    )
    audio_path = tmp_path / "speech.wav"
    audio_path.touch()

    first = transcriber.transcribe(audio_path)
    second = transcriber.transcribe(audio_path)

    assert len(loaded) == 1
    assert loaded[0]["device"] == "cpu"
    assert loaded[0]["compute_type"] == "int8"
    assert first.text == "Pode criar."
    assert first.language_probability == 0.96
    assert first.no_speech_probability == 0.1
    assert first.average_log_probability == pytest.approx(-0.3)
    assert first.transcription_seconds >= 0
    assert second.text == first.text


class FakePiperVoice:
    def synthesize_wav(self, text, wav_file, syn_config=None):
        assert text == "Tarefa criada com sucesso."
        assert syn_config == {"noise_scale": 0.0, "noise_w_scale": 0.0}
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 2205)


def test_piper_loads_once_and_returns_wav(tmp_path):
    from app.assistant.voice.piper import PiperSpeechSynthesizer

    model_path = tmp_path / "pt_BR-faber-medium.onnx"
    config_path = tmp_path / "pt_BR-faber-medium.onnx.json"
    model_path.touch()
    config_path.write_text("{}", encoding="utf-8")
    loads = []

    def loader(path, config_path):
        loads.append((path, config_path))
        return FakePiperVoice()

    synthesizer = PiperSpeechSynthesizer(
        model_path=model_path,
        voice_loader=loader,
        noise_scale=0.0,
        noise_w_scale=0.0,
        synthesis_config_factory=lambda **options: options,
    )

    first = synthesizer.synthesize("Tarefa criada com sucesso.")
    second = synthesizer.synthesize("Tarefa criada com sucesso.")

    assert len(loads) == 1
    assert first.data.startswith(b"RIFF")
    assert first.media_type == "audio/wav"
    assert first.synthesis_seconds >= 0
    with wave.open(__import__("io").BytesIO(second.data), "rb") as wav_file:
        assert wav_file.getframerate() == 22050
