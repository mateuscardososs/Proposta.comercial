from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from pathlib import Path
import threading
from time import monotonic
from typing import Any
import wave

from app.assistant.voice.provider import SynthesizedAudio, VoiceUnavailableError


VoiceLoader = Callable[[Path, Path], Any]


class PiperSpeechSynthesizer:
    def __init__(
        self,
        *,
        model_path: Path,
        voice_loader: VoiceLoader | None = None,
    ) -> None:
        self.model_path = model_path
        self.config_path = Path(f"{model_path}.json")
        self.voice_loader = voice_loader or _load_piper_voice
        self._voice: Any | None = None
        self._lock = threading.Lock()

    def synthesize(self, text: str) -> SynthesizedAudio:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("O texto da fala nao pode ficar vazio.")
        started = monotonic()
        with self._lock:
            voice = self._get_voice()
            buffer = BytesIO()
            try:
                with wave.open(buffer, "wb") as wav_file:
                    voice.synthesize_wav(clean_text, wav_file)
            except Exception as exc:
                raise VoiceUnavailableError(
                    "A sintese de voz local falhou."
                ) from exc
        return SynthesizedAudio(
            data=buffer.getvalue(),
            media_type="audio/wav",
            synthesis_seconds=monotonic() - started,
        )

    def _get_voice(self) -> Any:
        if self._voice is None:
            if not self.model_path.is_file() or not self.config_path.is_file():
                raise VoiceUnavailableError(
                    "A voz pt-BR configurada nao esta instalada."
                )
            try:
                self._voice = self.voice_loader(self.model_path, self.config_path)
            except Exception as exc:
                raise VoiceUnavailableError(
                    "A voz pt-BR configurada nao pode ser carregada."
                ) from exc
        return self._voice


def _load_piper_voice(model_path: Path, config_path: Path) -> Any:
    try:
        from piper import PiperVoice
    except ImportError as exc:
        raise VoiceUnavailableError(
            "Instale as dependencias opcionais de voz para usar a sintese."
        ) from exc
    return PiperVoice.load(str(model_path), config_path=str(config_path), use_cuda=False)
