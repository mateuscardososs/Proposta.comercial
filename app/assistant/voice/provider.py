from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class VoiceError(RuntimeError):
    """Base class for user-safe voice processing failures."""


class VoiceUnavailableError(VoiceError):
    pass


class InvalidAudioError(VoiceError):
    pass


class NoSpeechError(VoiceError):
    pass


class SuspiciousTranscriptionError(VoiceError):
    pass


class VoiceBusyError(VoiceError):
    pass


class VoiceTimeoutError(VoiceError):
    pass


class TranscriptionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(max_length=4000)
    language: str = Field(default="", max_length=20)
    language_probability: float = Field(default=0, ge=0, le=1)
    no_speech_probability: float = Field(default=0, ge=0, le=1)
    average_log_probability: float = Field(default=0, ge=-20, le=0)
    transcription_seconds: float = Field(default=0, ge=0)


class SynthesizedAudio(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data: bytes = Field(min_length=1)
    media_type: Literal["audio/wav"] = "audio/wav"
    synthesis_seconds: float = Field(ge=0)


class AudioTranscriber(Protocol):
    def transcribe(self, path: Path) -> TranscriptionResult: ...


class SpeechSynthesizer(Protocol):
    def synthesize(self, text: str) -> SynthesizedAudio: ...
