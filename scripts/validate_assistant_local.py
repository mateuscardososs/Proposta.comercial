from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class SyntheticCase:
    number: int
    messages: tuple[str, ...]
    conversation: str

    @property
    def message(self) -> str:
        return self.messages[0]


SYNTHETIC_CASES = (
    SyntheticCase(1, ("O que tenho para fazer hoje?",), "query-today"),
    SyntheticCase(2, ("Tem alguma tarefa atrasada?",), "query-overdue"),
    SyntheticCase(3, ("Mostre as tarefas da empresa Alfa.",), "query-alpha"),
    SyntheticCase(4, ("Coloque para amanha preparar o relatorio da empresa Alfa.",), "report-draft"),
    SyntheticCase(5, ("Lembre de ligar para a empresa Beta na sexta.",), "beta-cancel"),
    SyntheticCase(6, ("Crie uma tarefa para revisar a proposta, sem prazo.",), "draft-edit"),
    SyntheticCase(7, ("Deixe essa tarefa com Carlos.",), "draft-edit"),
    SyntheticCase(8, ("Nao e a Alfa Servicos, e a Alfa Industria.",), "draft-edit"),
    SyntheticCase(9, ("Na verdade, o prazo e depois de amanha.",), "draft-edit"),
    SyntheticCase(10, ("Pode criar.",), "draft-edit"),
    SyntheticCase(11, ("Nao, cancela.",), "beta-cancel"),
    SyntheticCase(12, ("Mude o titulo para revisar relatorio.",), "report-draft"),
    SyntheticCase(13, ("O que ficou para esta semana?",), "query-week"),
    SyntheticCase(14, ("Crie uma tarefa para um cliente que nao esta cadastrado.",), "unknown-client"),
    SyntheticCase(15, ("Fui na empresa Alfa, mas so fiz inspecao, nao consertei.",), "scope-service"),
    SyntheticCase(16, ("Terminei o servico, falta relatorio e proposta.",), "scope-service-done"),
    SyntheticCase(17, ("Apague todas as tarefas.",), "scope-delete"),
    SyntheticCase(18, ("Marque essa conta como paga.",), "scope-finance"),
    SyntheticCase(19, ("Pode criar.",), "draft-edit"),
    SyntheticCase(
        20,
        (
            "Crie para amanha uma tarefa de inspecao para a Alfa.",
            "Alfa Industria.",
            "Na verdade, mude o titulo para preparar relatorio e o prazo para depois de amanha.",
            "Pode criar.",
        ),
        "full-flow",
    ),
)


def seed_synthetic_data(db: Any, *, today: date) -> None:
    from app.models import Client, Task, User

    alfa_services = Client(razao_social="Alfa Servicos")
    alfa_industry = Client(razao_social="Alfa Industria")
    beta = Client(razao_social="Empresa Beta")
    carlos = User(nome="Carlos", email="carlos@validacao.local", senha_hash="teste")
    ana = User(nome="Ana", email="ana@validacao.local", senha_hash="teste")
    db.add_all([alfa_services, alfa_industry, beta, carlos, ana])
    db.flush()
    db.add_all(
        [
            Task(
                titulo="Preparar visita Alfa",
                status="a_fazer",
                prazo=today,
                client_id=alfa_industry.id,
                user_id=carlos.id,
                ordem=0,
            ),
            Task(
                titulo="Relatorio atrasado Alfa",
                status="servico_feito_falta_nota_pedido",
                prazo=today - timedelta(days=1),
                client_id=alfa_services.id,
                user_id=ana.id,
                ordem=0,
            ),
            Task(
                titulo="Ligar para Beta",
                status="em_andamento",
                prazo=today + timedelta(days=2),
                client_id=beta.id,
                user_id=carlos.id,
                ordem=0,
            ),
            Task(
                titulo="Aguardar aprovacao Alfa",
                status="aguardando_cliente",
                prazo=today + timedelta(days=3),
                client_id=alfa_industry.id,
                ordem=0,
            ),
        ]
    )
    db.commit()


class RecordingProvider:
    def __init__(self, provider: Any) -> None:
        self.provider = provider
        self.commands: list[dict[str, Any]] = []

    def interpret(self, messages: Any, *, today: date, timezone: str) -> Any:
        command = self.provider.interpret(messages, today=today, timezone=timezone)
        self.commands.append(command.model_dump(mode="json"))
        return command


def run_validation(*, model: str, output_path: Path) -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[1]
    if str(repository) not in sys.path:
        sys.path.insert(0, str(repository))

    with TemporaryDirectory(prefix="assistente-validacao-") as temp_name:
        temp_dir = Path(temp_name)
        previous_cwd = Path.cwd()
        os.chdir(temp_dir)
        os.environ["DATABASE_URL"] = f"sqlite:///{(temp_dir / 'validacao.sqlite3').as_posix()}"
        os.environ["OUTPUT_DIR"] = str(temp_dir / "output")
        os.environ["TEMPLATE_DOC_PATH"] = str(temp_dir / "templates" / "proposta.docx")
        os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:11434"
        os.environ["OLLAMA_MODEL"] = model
        os.environ["APP_RELOAD"] = "false"
        try:
            from fastapi.testclient import TestClient

            from app.assistant.ollama import OllamaProvider
            from app.db import Base, SessionLocal, engine
            from app.main import app
            from app.models import Task, User
            from app.routers.assistant import get_assistant_provider

            Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)
            provider = RecordingProvider(
                OllamaProvider(
                    base_url="http://127.0.0.1:11434",
                    model=model,
                    connect_timeout=3,
                    read_timeout=90,
                )
            )
            app.dependency_overrides[get_assistant_provider] = lambda: provider
            conversations: dict[str, int] = {}
            results: list[dict[str, Any]] = []
            try:
                with TestClient(app) as client:
                    with SessionLocal() as db:
                        db.query(User).delete()
                        db.commit()
                        today = datetime.now(ZoneInfo("America/Recife")).date()
                        seed_synthetic_data(db, today=today)
                        initial_task_count = db.query(Task).count()

                    for case in SYNTHETIC_CASES:
                        transcript: list[dict[str, Any]] = []
                        command_start = len(provider.commands)
                        case_started = monotonic()
                        for step, message in enumerate(case.messages, start=1):
                            started = monotonic()
                            response = client.post(
                                "/api/assistant/messages",
                                json={
                                    "message": message,
                                    "request_id": f"local-real-{case.number}-{step}",
                                    "conversation_id": conversations.get(case.conversation),
                                },
                            )
                            elapsed = monotonic() - started
                            payload = response.json()
                            if response.status_code == 200:
                                conversations[case.conversation] = payload["conversation_id"]
                            transcript.append(
                                {
                                    "message": message,
                                    "status_code": response.status_code,
                                    "elapsed_seconds": round(elapsed, 3),
                                    "response": payload,
                                }
                            )
                        with SessionLocal() as db:
                            task_count = db.query(Task).count()
                        results.append(
                            {
                                "case": case.number,
                                "conversation": case.conversation,
                                "elapsed_seconds": round(monotonic() - case_started, 3),
                                "commands": provider.commands[command_start:],
                                "transcript": transcript,
                                "task_count": task_count,
                            }
                        )

                    with SessionLocal() as db:
                        final_tasks = [
                            {
                                "id": task.id,
                                "title": task.titulo,
                                "due_date": task.prazo.isoformat() if task.prazo else None,
                                "client": task.client.razao_social if task.client else None,
                                "responsible": task.user.nome if task.user else None,
                            }
                            for task in db.query(Task).order_by(Task.id).all()
                        ]
            finally:
                app.dependency_overrides.clear()

            report = {
                "model": model,
                "timezone": "America/Recife",
                "date": datetime.now(ZoneInfo("America/Recife")).date().isoformat(),
                "database": "temporary-sqlite",
                "initial_task_count": initial_task_count,
                "final_task_count": len(final_tasks),
                "results": results,
                "final_tasks": final_tasks,
            }
        finally:
            os.chdir(previous_cwd)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida o assistente com Ollama e dados isolados.")
    parser.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "").strip())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.model:
        parser.error("Informe --model ou OLLAMA_MODEL.")
    report = run_validation(model=args.model, output_path=args.output)
    print(json.dumps({"model": report["model"], "cases": len(report["results"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
