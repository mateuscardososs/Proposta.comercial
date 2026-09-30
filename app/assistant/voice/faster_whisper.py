from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import threading
from time import monotonic
from typing import Any

from app.assistant.voice.provider import TranscriptionResult, VoiceUnavailableError


ModelLoader = Callable[..., Any]


class FasterWhisperTranscriber:
    def __init__(
        self,
        *,
        model_name: str,
        cache_dir: Path,
        device: str,
        compute_type: str,
        language: str,
        initial_prompt: str = "",
        model_loader: ModelLoader | None = None,
    ) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.initial_prompt = initial_prompt.strip()
        self.model_loader = model_loader or _load_whisper_model
        self._model: Any | None = None
        self._lock = threading.Lock()

    def transcribe(self, path: Path) -> TranscriptionResult:
        started = monotonic()
        with self._lock:
            model = self._get_model()
            try:
                segments_iterator, info = model.transcribe(
                    str(path),
                    language=self.language,
                    beam_size=1,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 500},
                    condition_on_previous_text=False,
                    initial_prompt=self.initial_prompt or None,
                )
                segments = list(segments_iterator)
            except VoiceUnavailableError:
                raise
            except Exception as exc:
                raise VoiceUnavailableError(
                    "A transcricao local falhou ao processar o audio."
                ) from exc

        if segments:
            text = "".join(str(segment.text) for segment in segments).strip()
            no_speech_probability = sum(
                float(segment.no_speech_prob) for segment in segments
            ) / len(segments)
            average_log_probability = sum(
                float(segment.avg_logprob) for segment in segments
            ) / len(segments)
        else:
            text = ""
            no_speech_probability = 1.0
            average_log_probability = -20.0

        return TranscriptionResult(
            text=text,
            language=str(getattr(info, "language", "")),
            language_probability=float(getattr(info, "language_probability", 0)),
            no_speech_probability=no_speech_probability,
            average_log_probability=average_log_probability,
            transcription_seconds=monotonic() - started,
        )

    def _get_model(self) -> Any:
        if self._model is None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            try:
                self._model = self.model_loader(
                    model_name=self.model_name,
                    cache_dir=self.cache_dir,
                    device=self.device,
                    compute_type=self.compute_type,
                )
            except Exception as exc:
                raise VoiceUnavailableError(
                    "O modelo local de transcricao nao esta disponivel."
                ) from exc
        return self._model


def _load_whisper_model(
    *,
    model_name: str,
    cache_dir: Path,
    device: str,
    compute_type: str,
) -> Any:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise VoiceUnavailableError(
            "Instale as dependencias opcionais de voz para usar a transcricao."
        ) from exc
    return WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        download_root=str(cache_dir),
        local_files_only=True,
    )
