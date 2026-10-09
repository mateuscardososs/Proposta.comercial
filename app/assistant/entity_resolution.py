from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

from sqlalchemy.orm import Session

from app.assistant.dates import normalize_text
from app.models import Client, User

ModelT = TypeVar("ModelT", Client, User)


class AssistantEntityResolver:
    def __init__(self, db: Session) -> None:
        self.db = db

    def client(self, name: str | None) -> tuple[Client | None, str | None]:
        return self.named(
            name,
            self.db.query(Client).order_by(Client.razao_social).all(),
            lambda client: client.razao_social,
            "cliente",
        )

    def task_client(self, name: str | None) -> tuple[Client | None, str | None, str]:
        """Resolve a unique client, but keep unresolved text instead of blocking a task."""
        if name is None or not name.strip():
            return None, None, "unlinked"
        original = name.strip()[:255]
        needle = normalize_text(original)
        absent_values = {
            "none",
            "null",
            "nenhum",
            "nenhuma",
            "sem cliente",
            "nao informado",
            "nao informada",
            "cliente a identificar",
        }
        if needle in absent_values or needle.startswith(("nao especificad", "nao definid")):
            return None, None, "unlinked"
        candidates = self.db.query(Client).order_by(Client.razao_social).all()
        exact = [candidate for candidate in candidates if normalize_text(candidate.razao_social) == needle]
        matches = exact or [candidate for candidate in candidates if needle in normalize_text(candidate.razao_social)]
        if len(matches) == 1:
            return matches[0], original, "linked"
        if len(matches) > 1:
            return None, original, "needs_confirmation"
        return None, original, "pending_review"

    def user(self, name: str | None) -> tuple[User | None, str | None]:
        return self.named(
            name,
            self.db.query(User).filter(User.ativo.is_(True)).order_by(User.nome).all(),
            lambda user: user.nome,
            "responsavel",
        )

    def named(
        self,
        name: str | None,
        candidates: Sequence[ModelT],
        label: Callable[[ModelT], str],
        entity_name: str,
    ) -> tuple[ModelT | None, str | None]:
        if name is None or not name.strip():
            return None, None
        needle = normalize_text(name)
        absent_values = {
            "none",
            "null",
            "nenhum",
            "nenhuma",
            "sem cliente",
            "sem responsavel",
            "nao informado",
            "nao informada",
        }
        if needle in absent_values or needle.startswith(("nao especificad", "nao definid")):
            return None, None
        exact = [candidate for candidate in candidates if normalize_text(label(candidate)) == needle]
        if len(exact) == 1:
            return exact[0], None
        matches = [candidate for candidate in candidates if needle in normalize_text(label(candidate))]
        if len(matches) == 1:
            return matches[0], None
        if not matches:
            return (
                None,
                f"Nao encontrei o {entity_name} '{name}'. Qual cadastro devo usar?",
            )
        options = ", ".join(label(candidate) for candidate in matches[:8])
        return (
            None,
            f"Encontrei mais de um {entity_name}: {options}. Qual deles devo usar?",
        )
