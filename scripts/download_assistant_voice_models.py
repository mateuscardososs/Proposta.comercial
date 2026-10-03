from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from time import monotonic


WHISPER_REPOSITORY = "Systran/faster-whisper-small"
PIPER_REPOSITORY = "rhasspy/piper-voices"
PIPER_REVISION = "c10ece1aade47bb51c153c893d14e5bf8e5b7117"
PIPER_PREFIX = "pt/pt_BR/faber/medium"
PIPER_MODEL_SHA256 = "858555e3a064209c57088fe6bd70c4c3dc54d03eaa00c45d5ecaf43a33f95aa7"
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_models(model_dir: Path) -> dict[str, object]:
    from huggingface_hub import hf_hub_download, snapshot_download

    model_dir.mkdir(parents=True, exist_ok=True)
    started = monotonic()
    whisper_path = Path(
        snapshot_download(
            repo_id=WHISPER_REPOSITORY,
            cache_dir=model_dir,
        )
    )

    piper_files = {}
    for filename in (
        "pt_BR-faber-medium.onnx",
        "pt_BR-faber-medium.onnx.json",
        "MODEL_CARD",
    ):
        cached = Path(
            hf_hub_download(
                repo_id=PIPER_REPOSITORY,
                filename=f"{PIPER_PREFIX}/{filename}",
                revision=PIPER_REVISION,
            )
        )
        destination = model_dir / filename
        if not destination.exists() or sha256(destination) != sha256(cached):
            shutil.copyfile(cached, destination)
        piper_files[filename] = destination

    if sha256(piper_files["pt_BR-faber-medium.onnx"]) != PIPER_MODEL_SHA256:
        raise RuntimeError("O hash SHA-256 da voz Piper nao corresponde ao arquivo oficial.")

    installed = [path for path in whisper_path.rglob("*") if path.is_file()]
    installed.extend(piper_files.values())
    total_bytes = sum(path.stat().st_size for path in installed)
    if total_bytes > MAX_TOTAL_BYTES:
        raise RuntimeError("Os modelos ultrapassaram o limite autorizado de 2 GB.")

    report = {
        "whisper_repository": WHISPER_REPOSITORY,
        "whisper_snapshot": str(whisper_path),
        "piper_repository": PIPER_REPOSITORY,
        "piper_revision": PIPER_REVISION,
        "piper_model_sha256": PIPER_MODEL_SHA256,
        "total_bytes": total_bytes,
        "elapsed_seconds": round(monotonic() - started, 3),
        "files": {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in piper_files.values()
        },
    }
    (model_dir / "voice-models.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Baixa os dois modelos locais de voz aprovados.")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=repository / ".models" / "assistant_voice",
    )
    args = parser.parse_args()
    report = download_models(args.model_dir.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
