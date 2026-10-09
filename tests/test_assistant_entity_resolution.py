import pytest

from app.assistant.service import AssistantService
from app.models import Client, User


def service_with_clients(db, names):
    clients = [Client(razao_social=name) for name in names]
    db.add_all(clients)
    db.flush()
    return AssistantService(db, None), clients


def test_exact_accent_and_partial_identity(db):
    service, clients = service_with_clients(db, ["Álfa", "Alfa Serviços", "Beta"])
    assert service._resolve_client("alfa") == (clients[0], None)
    assert service._resolve_client("bet") == (clients[2], None)
    assert service._resolve_task_client(" álfa ") == (clients[0], "álfa", "linked")


def test_exact_tie_differs_from_strict_partial_options(db):
    service, clients = service_with_clients(db, ["Alfa", "Álfa", "Alfa Serviços"])
    ordered = sorted(clients, key=lambda client: client.razao_social)
    assert service._resolve_client("alfa") == (
        None, "Encontrei mais de um cliente: " + ", ".join(c.razao_social for c in ordered) + ". Qual deles devo usar?"
    )
    assert service._resolve_task_client("alfa") == (None, "alfa", "needs_confirmation")
    assert service._resolve_task_client("Serviços")[0] is clients[2]


def test_missing_long_text_and_eight_options(db):
    service, clients = service_with_clients(db, [f"Alfa {i}" for i in range(10)])
    assert service._resolve_client(" Novo ") == (None, "Nao encontrei o cliente ' Novo '. Qual cadastro devo usar?")
    assert service._resolve_task_client(" Novo ") == (None, "Novo", "pending_review")
    assert service._resolve_task_client("x" * 300) == (None, "x" * 255, "pending_review")
    assert service._resolve_client("Alfa") == (None, "Encontrei mais de um cliente: " + ", ".join(c.razao_social for c in clients[:8]) + ". Qual deles devo usar?")


@pytest.mark.parametrize("name", [None, "", "  ", "none", "null", "nenhum", "nenhuma", "sem cliente", "não informado", "não informada", "não especificado", "não definida"])
def test_absent_sentinels(db, name):
    service = AssistantService(db, None)
    assert service._resolve_client(name) == (None, None)
    assert service._resolve_task_client(name) == (None, None, "unlinked")


def test_task_specific_sentinel(db):
    service = AssistantService(db, None)
    assert service._resolve_task_client("cliente a identificar") == (None, None, "unlinked")
    assert service._resolve_client("cliente a identificar")[1] == "Nao encontrei o cliente 'cliente a identificar'. Qual cadastro devo usar?"
    assert service._resolve_user("sem responsável") == (None, None)


def test_only_active_users_and_ambiguity(db):
    users = [User(nome=name, email=f"resolver{i}@example.invalid", senha_hash="unused", ativo=active)
             for i, (name, active) in enumerate([("Ana Silva", True), ("Ana Souza", True), ("Inativa", False)])]
    db.add_all(users)
    db.flush()
    service = AssistantService(db, None)
    assert service._resolve_user("ana silva")[0] is users[0]
    assert service._resolve_user("Ana") == (None, "Encontrei mais de um responsavel: Ana Silva, Ana Souza. Qual deles devo usar?")
    assert service._resolve_user("Inativa") == (None, "Nao encontrei o responsavel 'Inativa'. Qual cadastro devo usar?")
