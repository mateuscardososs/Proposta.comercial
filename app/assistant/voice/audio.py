from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.assistant.voice.provider import InvalidAudioError


class AudioMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    duration_seconds: float = Field(gt=0)
    sample_rate: int = Field(gt=0)
    channels: int = Field(gt=0)
    container_format: str = Field(min_length=1, max_length=80)


def inspect_audio(
    path: Path,
    *,
    min_duration_seconds: float,
    max_duration_seconds: float,
) -> AudioMetadata:
    try:
        import av

        container = av.open(str(path), mode="r")
    except (ImportError, OSError, ValueError) as exc:
        raise InvalidAudioError("O arquivo enviado nao contem um audio valido.") from exc
    except Exception as exc:
        raise InvalidAudioError("O arquivo enviado nao contem um audio valido.") from exc

    try:
        streams = [stream for stream in container.streams if stream.type == "audio"]
        if len(streams) != 1:
            raise InvalidAudioError("O arquivo deve conter exatamente uma faixa de audio.")
        stream = streams[0]
        duration_seconds = 0.0
        sample_rate = int(stream.codec_context.sample_rate or 0)
        channels = int(stream.codec_context.channels or 0)
        decoded_frames = 0

        for frame in container.decode(stream):
            decoded_frames += 1
            frame_rate = int(frame.sample_rate or sample_rate)
            if frame_rate <= 0:
                raise InvalidAudioError("Nao foi possivel identificar a taxa do audio.")
            sample_rate = frame_rate
            channels = len(frame.layout.channels) if frame.layout else channels
            duration_seconds += frame.samples / frame_rate
            if duration_seconds > max_duration_seconds:
                limit = _duration_label(max_duration_seconds)
                raise InvalidAudioError(f"A fala deve ter no maximo {limit}.")

        if decoded_frames == 0 or sample_rate <= 0 or channels <= 0:
            raise InvalidAudioError("O arquivo enviado nao contem audio decodificavel.")
        if duration_seconds < min_duration_seconds:
            raise InvalidAudioError("O trecho de audio e curto demais para transcrever.")

        format_name = (container.format.name or "desconhecido").split(",", 1)[0]
        return AudioMetadata(
            duration_seconds=duration_seconds,
            sample_rate=sample_rate,
            channels=channels,
            container_format=format_name,
        )
    except InvalidAudioError:
        raise
    except Exception as exc:
        raise InvalidAudioError("O arquivo enviado nao contem um audio valido.") from exc
    finally:
        container.close()


def _duration_label(seconds: float) -> str:
    rounded = int(seconds) if seconds.is_integer() else seconds
    unit = "segundo" if rounded == 1 else "segundos"
    return f"{rounded:g} {unit}" if isinstance(rounded, float) else f"{rounded} {unit}"
