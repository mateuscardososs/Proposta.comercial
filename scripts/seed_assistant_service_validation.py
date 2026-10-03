"""Seed clearly synthetic service-validation records in the isolated 8011 SQLite DB."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base, ensure_service_history_guards_for_engine
from app.models import AssistantAction, AssistantConversation, Client, ServiceCall, Task, User
from app.schemas import ServiceEventCreate, ServiceStepChange, TaskCreate
from app.services import board_service, service_record_service


ALLOWED_DB = Path("/tmp/ad-balancas-services-8011/app.sqlite3")
SYNTHETIC_CLIENTS = (
    "Alfa Serviços Sintética",
    "Alfa Indústria Sintética",
    "Beta Comércio Sintética",
)


def validate_seed_target(database_url: str, enabled: str) -> Path:
    if enabled != "1":
        raise RuntimeError("Defina SERVICE_VALIDATION_ALLOW_SYNTHETIC_SEED=1 para autorizar a carga sintética.")
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise RuntimeError("A carga sintética aceita somente SQLite isolado.")
    target = Path(database_url[len(prefix) :]).resolve(strict=False)
    if target != ALLOWED_DB.resolve(strict=False):
        raise RuntimeError("A carga sintética só aceita o banco isolado da porta 8011.")
    return target


def main() -> None:
    target = validate_seed_target(
        os.environ.get("DATABASE_URL", ""),
        os.environ.get("SERVICE_VALIDATION_ALLOW_SYNTHETIC_SEED", ""),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{target}")
    Base.metadata.create_all(engine)
    ensure_service_history_guards_for_engine(engine)
    with Session(engine) as db:
        clients = {}
        for name in SYNTHETIC_CLIENTS:
            row = db.scalar(select(Client).where(Client.razao_social == name))
            if row is None:
                row = Client(razao_social=name, contato_padrao="DADOS SINTÉTICOS - NÃO CONTATAR")
                db.add(row)
                db.flush()
            clients[name] = row
        user = db.scalar(select(User).where(User.email == "carlos.teste@example.invalid"))
        if user is None:
            user = User(
                nome="Carlos Teste Sintético", email="carlos.teste@example.invalid",
                senha_hash="synthetic-validation-only-not-a-login", ativo=True,
            )
            db.add(user)
            db.flush()
        conversation = db.query(AssistantConversation).first()
        if conversation is None:
            conversation = AssistantConversation()
            db.add(conversation)
            db.flush()

        seeded_call_ids = []
        if not db.query(Task).filter(Task.titulo.like("[SINTÉTICO] %")).count():
            for title, client_row, status, due in (
                ("[SINTÉTICO] Preparar relatório de inspeção", clients[SYNTHETIC_CLIENTS[0]], "a_fazer", date(2026, 10, 5)),
                ("[SINTÉTICO] Confirmar proposta com cliente", clients[SYNTHETIC_CLIENTS[2]], "aguardando_cliente", None),
            ):
                board_service.create_task(db, TaskCreate(
                    titulo=title, descricao="Registro de validação; não representa serviço real.",
                    status=status, client_id=client_row.id, user_id=user.id, prazo=due,
                ), commit=False)

        if not db.query(AssistantAction).filter(AssistantAction.request_id.like("seed-service-%")).count():
            examples = (
                (SYNTHETIC_CLIENTS[0], "[SINTÉTICO] Inspeção de balança", "inspection", "Inspeção visual sintética.",
                 [ServiceStepChange(step_type="report", status="pending", note="Relatório sintético pendente.")]),
                (SYNTHETIC_CLIENTS[1], "[SINTÉTICO] Reparo de balança", "execution_completed", "Execução concluída em cenário sintético.",
                 [ServiceStepChange(step_type="report", status="pending", note="Relatório sintético pendente."),
                  ServiceStepChange(step_type="proposal", status="not_applicable", note="Não aplicável no cenário sintético.")]),
            )
            for index, (client_name, summary, event_type, description, changes) in enumerate(examples, start=1):
                action = AssistantAction(
                    conversation_id=conversation.id, request_id=f"seed-service-{index}",
                    confirmation_token_hash=f"{index:064d}", action_type="register_service_event",
                    status="executed", arguments_json={"synthetic": True}, result_json={},
                )
                db.add(action)
                db.flush()
                result = service_record_service.register_event(
                    db,
                    ServiceEventCreate(
                        client_id=clients[client_name].id, summary=summary,
                        event_type=event_type, occurred_on=date(2026, 10, 2),
                        description=description, step_changes=changes,
                    ),
                    conversation_id=conversation.id, assistant_action_id=action.id, commit=False,
                )
                action.result_json = {
                    "service_call_id": result.service_call.id,
                    "service_event_id": result.event.id,
                    "synthetic": True,
                }
                seeded_call_ids.append(result.service_call.id)
        db.commit()
        if not seeded_call_ids:
            seeded_call_ids = [row.id for row in db.query(ServiceCall).filter(
                ServiceCall.summary.like("[SINTÉTICO] %")
            ).all()]
        print(
            f"Carga sintética pronta: {len(SYNTHETIC_CLIENTS)} clientes, "
            f"{db.query(ServiceCall).filter(ServiceCall.summary.like('[SINTÉTICO] %')).count()} chamados, "
            f"{db.query(Task).filter(Task.titulo.like('[SINTÉTICO] %')).count()} tarefas. IDs de referência: "
            + ", ".join(str(item) for item in seeded_call_ids)
        )
    engine.dispose()


if __name__ == "__main__":
    main()
