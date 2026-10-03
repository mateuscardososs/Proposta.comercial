from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Any, Callable
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    messages: tuple[str, ...]
    validator: Callable[[list[dict[str, Any]]], bool]


def _contains_reply(*terms: str) -> Callable[[list[dict[str, Any]]], bool]:
    def validate(turns: list[dict[str, Any]]) -> bool:
        reply = " ".join(str(turn["response"].get("message", "")).casefold() for turn in turns)
        return all(term.casefold() in reply for term in terms)

    return validate


CASES = (
    BenchmarkCase(
        "conversa-geral",
        ("Meu dia ficou desorganizado e tenho várias pendências. Como você pode me ajudar a começar?",),
        lambda turns: turns[-1]["response"].get("kind") == "text"
        and len(turns[-1]["response"].get("message", "")) >= 20,
    ),
    BenchmarkCase(
        "continuidade-mudanca-assunto",
        (
            "Sugira uma forma simples de organizar a manhã.",
            "Mudando de assunto: o que você consegue fazer dentro deste sistema?",
        ),
        lambda turns: all(turn["response"].get("kind") == "text" for turn in turns)
        and "tarefa" in turns[-1]["response"].get("message", "").casefold(),
    ),
    BenchmarkCase(
        "consulta-recomendacao",
        ("Analise as pendências do quadro e recomende qual devo atacar primeiro, explicando o motivo.",),
        lambda turns: turns[-1]["response"].get("kind") == "text"
        and "relat" in turns[-1]["response"].get("message", "").casefold(),
    ),
    BenchmarkCase(
        "criacao-correcao",
        (
            "Prepare uma tarefa sem prazo chamada conferir documentação da Beta.",
            "Antes de confirmar, troque o título para conferir proposta da Beta e deixe para amanhã.",
            "Pode criar.",
        ),
        lambda turns: turns[0]["response"].get("kind") == "confirmation"
        and turns[1]["response"].get("kind") == "confirmation"
        and turns[2]["response"].get("kind") == "success",
    ),
    BenchmarkCase(
        "tecnica-tara",
        ("Em uma balança, o que significa tara?",),
        lambda turns: any(
            term in turns[-1]["response"].get("message", "").casefold()
            for term in ("recipiente", "descont", "subtra", "peso líquido", "peso liquido")
        )
        and not any(
            wrong in turns[-1]["response"].get("message", "").casefold()
            for wrong in ("tara é calibra", "tara e calibra", "usada para calibrar")
        ),
    ),
    BenchmarkCase(
        "tecnica-calibracao-verificacao",
        ("Qual é a diferença entre calibração e verificação de uma balança?",),
        lambda turns: all(
            term in turns[-1]["response"].get("message", "").casefold()
            for term in ("calibra", "verifica", "requis")
        ),
    ),
)


def _seed(db: Any, *, today: date) -> None:
    from app.models import Client, Task, User

    alfa = Client(razao_social="Alfa Laboratorio")
    alfa_industria = Client(razao_social="Alfa Industria")
    beta = Client(razao_social="Beta Comercio")
    carlos = User(nome="Carlos Teste", email="carlos-benchmark@local", senha_hash="teste")
    db.add_all([alfa, alfa_industria, beta, carlos])
    db.flush()
    db.add_all(
        [
            Task(
                titulo="Finalizar relatório da Alfa",
                status="servico_feito_falta_nota_pedido",
                prazo=today - timedelta(days=1),
                client_id=alfa_industria.id,
                user_id=carlos.id,
                ordem=0,
            ),
            Task(
                titulo="Revisar proposta da Beta",
                status="a_fazer",
                prazo=today,
                client_id=beta.id,
                ordem=0,
            ),
        ]
    )
    db.commit()


def run_benchmark(*, model: str, repetitions: int, output: Path, label: str) -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[1]
    if str(repository) not in sys.path:
        sys.path.insert(0, str(repository))

    with TemporaryDirectory(prefix=f"assistente-benchmark-{label}-") as temp_name:
        temp_dir = Path(temp_name)
        previous_cwd = Path.cwd()
        os.chdir(temp_dir)
        os.environ.update(
            {
                "DATABASE_URL": f"sqlite:///{(temp_dir / 'benchmark.sqlite3').as_posix()}",
                "OUTPUT_DIR": str(temp_dir / "output"),
                "TEMPLATE_DOC_PATH": str(temp_dir / "templates" / "proposta.docx"),
                "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
                "OLLAMA_MODEL": model,
                "APP_RELOAD": "false",
            }
        )
        try:
            from fastapi.testclient import TestClient

            from app.db import Base, SessionLocal, engine
            from app.main import app
            from app.models import AssistantMessage

            runs: list[dict[str, Any]] = []
            with TestClient(app) as client:
                for repetition in range(1, repetitions + 1):
                    for case in CASES:
                        Base.metadata.drop_all(bind=engine)
                        Base.metadata.create_all(bind=engine)
                        with SessionLocal() as db:
                            today = datetime.now(ZoneInfo("America/Recife")).date()
                            _seed(db, today=today)

                        conversation_id: int | None = None
                        turns: list[dict[str, Any]] = []
                        for step, message in enumerate(case.messages, start=1):
                            request_id = f"benchmark-{label}-{repetition}-{case.name}-{step}"
                            started = monotonic()
                            response = client.post(
                                "/api/assistant/messages",
                                json={
                                    "message": message,
                                    "request_id": request_id,
                                    "conversation_id": conversation_id,
                                },
                            )
                            elapsed = monotonic() - started
                            payload = response.json()
                            if response.status_code == 200:
                                conversation_id = payload["conversation_id"]
                            with SessionLocal() as db:
                                stored = (
                                    db.query(AssistantMessage)
                                    .filter(AssistantMessage.reply_to_request_id == request_id)
                                    .one_or_none()
                                )
                                details = dict(stored.details_json) if stored else {}
                            turns.append(
                                {
                                    "message": message,
                                    "status_code": response.status_code,
                                    "elapsed_seconds": round(elapsed, 4),
                                    "response": payload,
                                    "provider_inferences": details.get("provider_inferences", []),
                                    "executed_tools": details.get("executed_tools", []),
                                }
                            )
                        runs.append(
                            {
                                "case": case.name,
                                "repetition": repetition,
                                "passed": case.validator(turns),
                                "elapsed_seconds": round(sum(turn["elapsed_seconds"] for turn in turns), 4),
                                "inference_count": sum(
                                    len(turn["provider_inferences"]) for turn in turns
                                ),
                                "repair_count": sum(
                                    1
                                    for turn in turns
                                    for trace in turn["provider_inferences"]
                                    if trace.get("repair_reason")
                                ),
                                "turns": turns,
                            }
                        )
        finally:
            os.chdir(previous_cwd)

    summaries = []
    for case in CASES:
        selected = [run for run in runs if run["case"] == case.name]
        times = [run["elapsed_seconds"] for run in selected]
        summaries.append(
            {
                "case": case.name,
                "runs": len(selected),
                "median_seconds": round(statistics.median(times), 4),
                "worst_seconds": round(max(times), 4),
                "accuracy": round(sum(run["passed"] for run in selected) / len(selected), 3),
                "median_inferences": statistics.median(
                    run["inference_count"] for run in selected
                ),
                "worst_inferences": max(run["inference_count"] for run in selected),
                "repairs": sum(run["repair_count"] for run in selected),
            }
        )
    report = {
        "label": label,
        "model": model,
        "repetitions": repetitions,
        "generated_at": datetime.now(ZoneInfo("America/Recife")).isoformat(),
        "database": "temporary-sqlite",
        "summaries": summaries,
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark real e isolado do assistente local.")
    parser.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "").strip())
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.model:
        parser.error("Informe --model ou OLLAMA_MODEL.")
    if args.repetitions < 2:
        parser.error("Use ao menos duas repeticoes.")
    report = run_benchmark(
        model=args.model,
        repetitions=args.repetitions,
        output=args.output,
        label=args.label,
    )
    print(json.dumps(report["summaries"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
