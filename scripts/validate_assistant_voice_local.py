from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
from io import BytesIO
import json
import os
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Iterator
import wave
from zoneinfo import ZoneInfo


SCENARIO = (
    "Crie uma tarefa para revisar o relatorio amanha.",
    "Na verdade, depois de amanha.",
    "Pode criar.",
)


def isolation_environment(*, root: Path, model_dir: Path, ollama_model: str) -> dict[str, str]:
    return {
        "DATABASE_URL": f"sqlite:///{root / 'validation.sqlite3'}",
        "OUTPUT_DIR": str(root / "output"),
        "TEMPLATE_DOC_PATH": str(root / "templates" / "proposta.docx"),
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "OLLAMA_MODEL": ollama_model,
        "OLLAMA_CONNECT_TIMEOUT": "3",
        "OLLAMA_READ_TIMEOUT": "90",
        "VOICE_ENABLED": "true",
        "VOICE_MODEL_DIR": str(model_dir),
        "VOICE_PIPER_MODEL_PATH": str(model_dir / "pt_BR-faber-medium.onnx"),
        "VOICE_WHISPER_MODEL": "small",
        "VOICE_WHISPER_DEVICE": "cpu",
        "VOICE_WHISPER_COMPUTE_TYPE": "int8",
        "VOICE_WHISPER_INITIAL_PROMPT": (
            "Crie uma tarefa. Pode criar. Sim, confirmo. Nao, cancela."
        ),
        "VOICE_PIPER_NOISE_SCALE": "0",
        "VOICE_PIPER_NOISE_W_SCALE": "0",
        "APP_HOST": "127.0.0.1",
        "APP_RELOAD": "false",
    }


@contextmanager
def applied_environment(values: dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _silence_wav(duration: float = 0.8, rate: int = 16000) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(struct.pack("<h", 0) * int(duration * rate))
    return buffer.getvalue()


def run_validation(*, model_dir: Path, ollama_model: str) -> dict[str, object]:
    repository = Path(__file__).resolve().parents[1]
    if str(repository) not in sys.path:
        sys.path.insert(0, str(repository))

    with TemporaryDirectory(prefix="assistente-voz-validacao-") as temporary:
        root = Path(temporary)
        environment = isolation_environment(
            root=root, model_dir=model_dir, ollama_model=ollama_model
        )
        with applied_environment(environment):
            from fastapi.testclient import TestClient

            from app.db import Base, SessionLocal, engine
            from app.main import app
            from app.models import Task, User
            from scripts.validate_assistant_local import seed_synthetic_data

            Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)
            records: list[dict[str, object]] = []
            conversation_id = None
            first_audio_seconds = None
            try:
                with TestClient(app) as client:
                    with SessionLocal() as db:
                        db.query(User).delete()
                        db.commit()
                        today = datetime.now(ZoneInfo("America/Recife")).date()
                        seed_synthetic_data(db, today=today)
                        initial_count = db.query(Task).count()

                    status_response = client.get("/api/assistant/voice/status")
                    if status_response.status_code != 200:
                        raise RuntimeError(status_response.text)
                    status_payload = status_response.json()
                    if not (
                        status_payload["transcription_available"]
                        and status_payload["synthesis_available"]
                    ):
                        raise RuntimeError(status_payload["message"])

                    for index, phrase in enumerate(SCENARIO, start=1):
                        tts_started = monotonic()
                        speech = client.post(
                            "/api/assistant/voice/speech",
                            json={"text": phrase, "kind": "text"},
                        )
                        tts_seconds = monotonic() - tts_started
                        if speech.status_code != 200:
                            raise RuntimeError(speech.text)
                        if first_audio_seconds is None:
                            first_audio_seconds = tts_seconds

                        stt_started = monotonic()
                        transcription = client.post(
                            "/api/assistant/voice/transcriptions",
                            files={"audio": (f"synthetic-{index}.wav", speech.content, "audio/wav")},
                        )
                        stt_seconds = monotonic() - stt_started
                        if transcription.status_code != 200:
                            raise RuntimeError(transcription.text)
                        transcript = transcription.json()["text"]

                        assistant_started = monotonic()
                        reply = client.post(
                            "/api/assistant/messages",
                            json={
                                "message": transcript,
                                "request_id": f"voice-real-{index}",
                                "conversation_id": conversation_id,
                            },
                        )
                        assistant_seconds = monotonic() - assistant_started
                        if reply.status_code != 200:
                            raise RuntimeError(reply.text)
                        payload = reply.json()
                        conversation_id = payload["conversation_id"]
                        records.append(
                            {
                                "input": phrase,
                                "transcript": transcript,
                                "reply_kind": payload["kind"],
                                "reply": payload["message"],
                                "tts_seconds": round(tts_seconds, 3),
                                "stt_seconds": round(stt_seconds, 3),
                                "assistant_seconds": round(assistant_seconds, 3),
                            }
                        )

                    final_reply = records[-1]
                    spoken_confirmation = client.post(
                        "/api/assistant/voice/speech",
                        json={"text": final_reply["reply"], "kind": final_reply["reply_kind"]},
                    )
                    if spoken_confirmation.status_code != 200:
                        raise RuntimeError(spoken_confirmation.text)

                    repeated = client.post(
                        "/api/assistant/messages",
                        json={
                            "message": records[-1]["transcript"],
                            "request_id": "voice-real-repeat-confirmation",
                            "conversation_id": conversation_id,
                        },
                    )

                    cancel_records = []
                    cancel_conversation_id = None
                    for index, phrase in enumerate(
                        ("Por favor, crie uma tarefa para telefonar.", "Cancela."), start=1
                    ):
                        cancel_speech = client.post(
                            "/api/assistant/voice/speech",
                            json={"text": phrase, "kind": "text"},
                        )
                        if cancel_speech.status_code != 200:
                            raise RuntimeError(cancel_speech.text)
                        cancel_transcription = client.post(
                            "/api/assistant/voice/transcriptions",
                            files={
                                "audio": (
                                    f"cancel-{index}.wav",
                                    cancel_speech.content,
                                    "audio/wav",
                                )
                            },
                        )
                        if cancel_transcription.status_code != 200:
                            raise RuntimeError(cancel_transcription.text)
                        cancel_text = cancel_transcription.json()["text"]
                        cancel_reply = client.post(
                            "/api/assistant/messages",
                            json={
                                "message": cancel_text,
                                "request_id": f"voice-real-cancel-{index}",
                                "conversation_id": cancel_conversation_id,
                            },
                        )
                        if cancel_reply.status_code != 200:
                            raise RuntimeError(cancel_reply.text)
                        cancel_payload = cancel_reply.json()
                        cancel_conversation_id = cancel_payload["conversation_id"]
                        cancel_records.append(
                            {
                                "input": phrase,
                                "transcript": cancel_text,
                                "reply_kind": cancel_payload["kind"],
                                "reply": cancel_payload["message"],
                            }
                        )

                    invalid = client.post(
                        "/api/assistant/voice/transcriptions",
                        files={"audio": ("invalid.webm", b"not audio", "audio/webm")},
                    )
                    silence = client.post(
                        "/api/assistant/voice/transcriptions",
                        files={"audio": ("silence.wav", _silence_wav(), "audio/wav")},
                    )

                    with SessionLocal() as db:
                        tasks = db.query(Task).order_by(Task.id).all()
                        created = tasks[-1]
                        expected_due = today + timedelta(days=2)
                        checks = {
                            "exactly_one_task_created": len(tasks) == initial_count + 1,
                            "corrected_due_date": created.prazo == expected_due,
                            "title_contains_review": "revis" in created.titulo.lower(),
                            "success_only_after_save": records[-1]["reply_kind"] == "success",
                            "repeated_confirmation_did_not_duplicate": db.query(Task).count()
                            == initial_count + 1,
                            "spoken_cancellation_did_not_create": (
                                db.query(Task).count() == initial_count + 1
                                and "cancelada" in cancel_records[-1]["reply"].lower()
                            ),
                            "invalid_audio_rejected": invalid.status_code == 422,
                            "silence_rejected": silence.status_code == 422,
                            "spoken_confirmation_generated": spoken_confirmation.content.startswith(b"RIFF"),
                        }
                        created_task = {
                            "id": created.id,
                            "title": created.titulo,
                            "due_date": created.prazo.isoformat() if created.prazo else None,
                        }
            finally:
                app.dependency_overrides.clear()

    if not all(checks.values()):
        raise RuntimeError(
            "A validacao real falhou: "
            + json.dumps(
                {
                    "checks": checks,
                    "records": records,
                    "cancel_records": cancel_records,
                    "created_task": created_task,
                },
                ensure_ascii=False,
            )
        )
    return {
        "evidence": "synthetic-piper-audio-real-components",
        "ollama_model": ollama_model,
        "whisper_model": "Systran/faster-whisper-small (CPU int8)",
        "piper_voice": "pt_BR-faber-medium",
        "first_audio_seconds": round(first_audio_seconds or 0, 3),
        "records": records,
        "cancel_records": cancel_records,
        "created_task": created_task,
        "repeated_confirmation_status": repeated.status_code,
        "checks": checks,
    }


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Valida voz, Ollama e persistencia em ambiente isolado.")
    parser.add_argument("--model-dir", type=Path, default=repository / ".models" / "assistant_voice")
    parser.add_argument("--ollama-model", default=os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct-2507-q4_K_M"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_validation(
        model_dir=args.model_dir.resolve(), ollama_model=args.ollama_model
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
