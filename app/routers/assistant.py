from __future__ import annotations

from functools import lru_cache
import importlib.util
import os
from pathlib import Path
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.assistant.contracts import (
    AssistantConfirmationRequest,
    AssistantHistory,
    AssistantMessageRequest,
    AssistantReply,
    VoiceSpeechRequest,
    VoiceStatus,
    VoiceTranscriptionResponse,
)
from app.assistant.ollama import OllamaProvider
from app.assistant.provider import AssistantProvider
from app.assistant.service import AssistantService
from app.assistant.voice.audio import inspect_audio
from app.assistant.voice.faster_whisper import FasterWhisperTranscriber
from app.assistant.voice.piper import PiperSpeechSynthesizer
from app.assistant.voice.policy import validate_transcription
from app.assistant.voice.provider import (
    AudioTranscriber,
    InvalidAudioError,
    NoSpeechError,
    SpeechSynthesizer,
    SuspiciousTranscriptionError,
    VoiceBusyError,
    VoiceTimeoutError,
    VoiceUnavailableError,
)
from app.assistant.voice.runtime import BoundedVoiceExecutor
from app.assistant.voice.speech import spoken_text
from app.config import get_settings
from app.db import get_db
from app.routers.pages import render_template


router = APIRouter(tags=["assistant"])
_transcription_executor = BoundedVoiceExecutor(name="voice-stt", max_pending=1)
_synthesis_executor = BoundedVoiceExecutor(name="voice-tts", max_pending=1)


def get_assistant_provider() -> AssistantProvider:
    settings = get_settings()
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        connect_timeout=settings.ollama_connect_timeout,
        read_timeout=settings.ollama_read_timeout,
    )


@lru_cache
def _configured_voice_transcriber() -> AudioTranscriber:
    settings = get_settings()
    return FasterWhisperTranscriber(
        model_name=settings.voice_whisper_model,
        cache_dir=settings.voice_model_dir,
        device=settings.voice_whisper_device,
        compute_type=settings.voice_whisper_compute_type,
        language=settings.voice_language,
        initial_prompt=settings.voice_whisper_initial_prompt,
    )


@lru_cache
def _configured_voice_synthesizer() -> SpeechSynthesizer:
    settings = get_settings()
    return PiperSpeechSynthesizer(
        model_path=settings.voice_piper_model_path,
        noise_scale=settings.voice_piper_noise_scale,
        noise_w_scale=settings.voice_piper_noise_w_scale,
    )


def get_voice_transcriber() -> AudioTranscriber:
    return _configured_voice_transcriber()


def get_voice_synthesizer() -> SpeechSynthesizer:
    return _configured_voice_synthesizer()


def _service(db: Session, provider: AssistantProvider | None = None) -> AssistantService:
    settings = get_settings()
    return AssistantService(
        db,
        provider,
        timezone=settings.assistant_timezone,
        context_messages=settings.assistant_context_messages,
        request_lease_seconds=settings.assistant_request_lease_seconds,
    )


@router.get("/web/assistente", name="web_assistant")
def assistant_page(request: Request) -> object:
    return render_template(
        request,
        "assistant.html",
        {"title": "Assistente operacional", "full_width": True},
    )


@router.get("/api/assistant/voice/status", response_model=VoiceStatus)
def assistant_voice_status() -> VoiceStatus:
    settings = get_settings()
    whisper_available = settings.voice_enabled and _whisper_is_available(settings)
    piper_available = settings.voice_enabled and _piper_is_available(settings)
    if not settings.voice_enabled:
        message = "A voz esta desativada. O assistente por texto continua disponivel."
    elif whisper_available and piper_available:
        message = "Transcricao e sintese locais disponiveis."
    else:
        missing = []
        if not whisper_available:
            missing.append("transcricao")
        if not piper_available:
            missing.append("sintese")
        message = (
            f"Componentes locais de {' e '.join(missing)} indisponiveis. "
            "O assistente por texto continua disponivel."
        )
    return VoiceStatus(
        enabled=settings.voice_enabled,
        transcription_available=whisper_available,
        synthesis_available=piper_available,
        message=message,
        max_duration_seconds=settings.voice_max_duration_seconds,
        max_upload_bytes=settings.voice_max_upload_bytes,
        silence_ms=settings.voice_silence_ms,
        idle_timeout_seconds=settings.voice_idle_timeout_seconds,
    )


@router.post(
    "/api/assistant/voice/transcriptions",
    response_model=VoiceTranscriptionResponse,
)
async def assistant_voice_transcription(
    audio: UploadFile = File(...),
    transcriber: AudioTranscriber = Depends(get_voice_transcriber),
) -> VoiceTranscriptionResponse:
    settings = get_settings()
    if not settings.voice_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="A voz esta desativada.")

    path = await _store_temporary_audio(audio, settings.voice_max_upload_bytes)

    def process() -> VoiceTranscriptionResponse:
        try:
            metadata = inspect_audio(
                path,
                min_duration_seconds=settings.voice_min_duration_seconds,
                max_duration_seconds=settings.voice_max_duration_seconds,
            )
            result = transcriber.transcribe(path)
            safe_text = validate_transcription(result)
            return VoiceTranscriptionResponse(
                text=safe_text,
                language=result.language,
                language_probability=result.language_probability,
                audio_duration_seconds=metadata.duration_seconds,
                transcription_seconds=result.transcription_seconds,
            )
        finally:
            path.unlink(missing_ok=True)

    try:
        return await _transcription_executor.submit(
            process,
            timeout=settings.voice_transcription_timeout_seconds,
        )
    except VoiceBusyError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except (InvalidAudioError, NoSpeechError, SuspiciousTranscriptionError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except VoiceTimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc
    except VoiceUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/api/assistant/voice/speech")
async def assistant_voice_speech(
    payload: VoiceSpeechRequest,
    synthesizer: SpeechSynthesizer = Depends(get_voice_synthesizer),
) -> Response:
    settings = get_settings()
    if not settings.voice_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="A voz esta desativada.")
    text = spoken_text(payload.text, payload.kind)
    try:
        result = await _synthesis_executor.submit(
            lambda: synthesizer.synthesize(text),
            timeout=settings.voice_synthesis_timeout_seconds,
        )
    except VoiceBusyError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except VoiceTimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc
    except VoiceUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return Response(
        content=result.data,
        media_type=result.media_type,
        headers={"X-Synthesis-Seconds": f"{result.synthesis_seconds:g}"},
    )


@router.post("/api/assistant/messages", response_model=AssistantReply)
def assistant_message(
    payload: AssistantMessageRequest,
    db: Session = Depends(get_db),
    provider: AssistantProvider = Depends(get_assistant_provider),
) -> AssistantReply:
    try:
        return _service(db, provider).handle_message(
            message=payload.message,
            request_id=payload.request_id,
            conversation_id=payload.conversation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/api/assistant/conversations/{conversation_id}",
    response_model=AssistantHistory,
)
def assistant_history(
    conversation_id: int,
    db: Session = Depends(get_db),
) -> AssistantHistory:
    try:
        messages = _service(db).get_history(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return AssistantHistory(conversation_id=conversation_id, messages=messages)


@router.post("/api/assistant/actions/{action_id}/confirm", response_model=AssistantReply)
def assistant_confirm(
    action_id: int,
    payload: AssistantConfirmationRequest,
    db: Session = Depends(get_db),
) -> AssistantReply:
    try:
        return _service(db).confirm_action(action_id, payload.confirmation_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/api/assistant/actions/{action_id}/cancel", response_model=AssistantReply)
def assistant_cancel(
    action_id: int,
    payload: AssistantConfirmationRequest,
    db: Session = Depends(get_db),
) -> AssistantReply:
    try:
        return _service(db).cancel_action(action_id, payload.confirmation_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


async def _store_temporary_audio(upload: UploadFile, max_bytes: int) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix="assistant-voice-", suffix=".audio")
    path = Path(raw_path)
    size = 0
    try:
        with os.fdopen(descriptor, "wb") as destination:
            while chunk := await upload.read(64 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="O arquivo de audio ultrapassa o limite permitido.",
                    )
                destination.write(chunk)
        if size == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="O arquivo de audio esta vazio.",
            )
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def _whisper_is_available(settings: object) -> bool:
    if importlib.util.find_spec("faster_whisper") is None:
        return False
    model_name = str(settings.voice_whisper_model)
    if Path(model_name).is_dir():
        return True
    prefix = f"models--Systran--faster-whisper-{model_name}"
    return any(settings.voice_model_dir.glob(f"{prefix}/snapshots/*/model.bin"))


def _piper_is_available(settings: object) -> bool:
    model_path = settings.voice_piper_model_path
    return (
        importlib.util.find_spec("piper") is not None
        and model_path.is_file()
        and Path(f"{model_path}.json").is_file()
    )
