# Contas a Receber e Contas a Pagar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar dois murais financeiros manuais e independentes, com criação/edição de lançamentos, destaque de atraso e movimentação segura entre pendente e pago.

**Architecture:** Um único model `Lancamento`, um service financeiro e um router parametrizado atendem contas a receber e pagar. Templates compartilhados evitam duplicação; o JavaScript genérico de drag-and-drop também atende o Kanban de tarefas, preservando suas URLs e payload com `ordem`.

**Tech Stack:** Python 3.12, FastAPI 0.116.1, SQLAlchemy 2.0.44, Pydantic 2.11.9, PostgreSQL 16, Jinja2 3.1.6, JavaScript puro, pytest e HTTPX.

## Global Constraints

- Lançamentos são manuais; não criar checkbox, evento ou sincronização com propostas.
- Não adicionar `Client.dias_pagamento_padrao` nem alterar o fluxo de propostas.
- `proposal_id` é somente referência opcional.
- `client_id` e `proposal_id` usam `ondelete="SET NULL"` e permanecem anuláveis.
- Reutilizar o design system de `app/templates_web/base.html`; não introduzir framework visual ou JavaScript novo.
- Manter `Base.metadata.create_all` no startup; não introduzir Alembic.
- Não adicionar campo `ordem` a `Lancamento`; ordenar por vencimento ascendente e ID descendente.
- Ao mover para pago, definir `data_pagamento=date.today()`; ao voltar para pendente, limpar a data.
- Criar commits atômicos e não modificar `app/routers/pages.py`, `app/services/proposal_service.py` ou `app/templates_web/proposal_form.html`.

---

### Task 1: Infraestrutura de testes, model e schemas

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/conftest.py`
- Create: `tests/test_lancamento_model.py`
- Modify: `app/db.py:3-26`
- Modify: `app/models.py:150-167`
- Modify: `app/schemas.py:272-274`

**Interfaces:**
- Consumes: `Base`, `TimestampMixin`, `Client`, `Proposal`, `ClientRead` e `ProposalSummary` existentes.
- Produces: `Lancamento`, `LancamentoCreate`, `LancamentoUpdate`, `LancamentoRead`, `LancamentoMove`, `TipoLancamento` e `StatusLancamento`.

- [ ] **Step 1: Adicionar dependências de teste isoladas da imagem de produção**

Criar `requirements-dev.txt`:

```text
-r requirements.txt
pytest==8.4.2
httpx==0.28.1
```

- [ ] **Step 2: Criar banco SQLite descartável para testes**

Criar `tests/conftest.py`:

```python
from __future__ import annotations

import os
from pathlib import Path
from tempfile import gettempdir

import pytest

TEST_DB_PATH = Path(gettempdir()) / "proposta_comercial_financeiro_tests.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["OUTPUT_DIR"] = str(Path(gettempdir()) / "proposta_comercial_test_output")

from app.db import Base, SessionLocal, engine  # noqa: E402


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

- [ ] **Step 3: Escrever os testes que exigem FKs anuláveis e schemas estritos**

Criar `tests/test_lancamento_model.py`:

```python
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models import Client, Lancamento, Proposal, User
from app.schemas import LancamentoCreate


def test_lancamento_foreign_keys_use_set_null():
    foreign_keys = {fk.parent.name: fk for fk in Lancamento.__table__.foreign_keys}
    assert foreign_keys["client_id"].ondelete == "SET NULL"
    assert foreign_keys["proposal_id"].ondelete == "SET NULL"
    assert Lancamento.__table__.c.client_id.nullable is True
    assert Lancamento.__table__.c.proposal_id.nullable is True


def test_deleting_client_and_proposal_preserves_lancamento(db):
    client = Client(razao_social="Cliente teste")
    user = User(nome="Responsável", email="responsavel@example.com", senha_hash="hash")
    db.add_all([client, user])
    db.flush()
    proposal = Proposal(numero=1, revisao="00", client_id=client.id, user_id=user.id)
    db.add(proposal)
    db.flush()
    lancamento = Lancamento(
        tipo="receber",
        descricao="Serviço",
        client_id=client.id,
        proposal_id=proposal.id,
        valor=Decimal("100.00"),
        data_emissao=date(2026, 8, 27),
        data_vencimento=date(2026, 9, 27),
        status="pendente",
    )
    db.add(lancamento)
    db.commit()
    lancamento_id = lancamento.id

    db.delete(client)
    db.commit()
    db.expire_all()

    preserved = db.get(Lancamento, lancamento_id)
    assert preserved is not None
    assert preserved.client_id is None
    assert preserved.proposal_id is None


@pytest.mark.parametrize("tipo", ["entrada", "", "RECEBER"])
def test_lancamento_create_rejects_invalid_tipo(tipo):
    with pytest.raises(ValidationError):
        LancamentoCreate(
            tipo=tipo,
            descricao="Serviço",
            valor=Decimal("10.00"),
            data_vencimento=date(2026, 9, 1),
        )


def test_lancamento_create_rejects_empty_description_and_non_positive_value():
    with pytest.raises(ValidationError):
        LancamentoCreate(
            tipo="pagar",
            descricao="   ",
            valor=Decimal("0.00"),
            data_vencimento=date(2026, 9, 1),
        )
```

- [ ] **Step 4: Executar os testes e confirmar a falha inicial**

Run:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/test_lancamento_model.py -v
```

Expected: collection fails because `Lancamento` and `LancamentoCreate` do not exist.

- [ ] **Step 5: Habilitar enforcement de FKs no fallback SQLite**

Em `app/db.py`, importar `event` e registrar o pragma logo após `create_engine`:

```python
from sqlalchemy import create_engine, event, text


if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
```

- [ ] **Step 6: Implementar o model**

Adicionar ao final de `app/models.py`:

```python
class Lancamento(Base, TimestampMixin):
    __tablename__ = "lancamentos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    descricao: Mapped[str] = mapped_column(String(255), nullable=False)
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    proposal_id: Mapped[int | None] = mapped_column(
        ForeignKey("proposals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    fornecedor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    data_emissao: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    data_vencimento: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pendente", nullable=False, index=True)
    data_pagamento: Mapped[date | None] = mapped_column(Date, nullable=True)

    client: Mapped[Client | None] = relationship()
    proposal: Mapped[Proposal | None] = relationship()
```

- [ ] **Step 7: Implementar os schemas**

Atualizar os imports no topo de `app/schemas.py`:

```python
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
```

Adicionar após `TaskMove`:

```python

TipoLancamento = Literal["receber", "pagar"]
StatusLancamento = Literal["pendente", "pago"]
DescricaoLancamento = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
ValorLancamento = Annotated[
    Decimal,
    Field(gt=Decimal("0.00"), max_digits=14, decimal_places=2),
]


class LancamentoBase(BaseModel):
    descricao: DescricaoLancamento
    client_id: int | None = None
    proposal_id: int | None = None
    fornecedor: str | None = Field(default=None, max_length=255)
    valor: ValorLancamento
    data_emissao: date = Field(default_factory=date.today)
    data_vencimento: date
    status: StatusLancamento = "pendente"
    data_pagamento: date | None = None


class LancamentoCreate(LancamentoBase):
    tipo: TipoLancamento


class LancamentoUpdate(LancamentoBase):
    pass


class LancamentoRead(ORMModel, LancamentoBase):
    id: int
    tipo: TipoLancamento
    created_at: datetime
    updated_at: datetime
    client: ClientRead | None = None
    proposal: ProposalSummary | None = None


class LancamentoMove(BaseModel):
    status: StatusLancamento
```

- [ ] **Step 8: Rodar os testes e commitar**

Run: `python -m pytest tests/test_lancamento_model.py -v`

Expected: `6 passed`, sem falhas.

```bash
git add requirements-dev.txt tests/conftest.py tests/test_lancamento_model.py app/db.py app/models.py app/schemas.py
git commit -m "feat: add financial entry domain model"
```

---

### Task 2: Service financeiro e regras de estado

**Files:**
- Create: `app/services/lancamento_service.py`
- Create: `tests/test_lancamento_service.py`

**Interfaces:**
- Consumes: schemas e model da Task 1.
- Produces: `list_lancamentos`, `get_lancamento`, `create_lancamento`, `update_lancamento`, `move_lancamento` e `is_atrasado`.

- [ ] **Step 1: Escrever testes de criação, ordenação, isolamento e movimentação**

Criar `tests/test_lancamento_service.py` com factories locais e estes casos:

```python
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models import Client, Lancamento, Proposal, User
from app.schemas import LancamentoCreate, LancamentoMove, LancamentoUpdate, ProposalCreate
from app.services import lancamento_service, proposal_service


def make_references(db):
    client = Client(razao_social="Cliente A")
    user = User(nome="Responsável", email="financeiro@example.com", senha_hash="hash")
    db.add_all([client, user])
    db.flush()
    proposal = Proposal(numero=10, revisao="00", client_id=client.id, user_id=user.id)
    db.add(proposal)
    db.commit()
    return client, proposal


def test_create_receivable_keeps_references_and_clears_supplier(db):
    client, proposal = make_references(db)
    created = lancamento_service.create_lancamento(
        db,
        LancamentoCreate(
            tipo="receber",
            descricao="Manutenção",
            client_id=client.id,
            proposal_id=proposal.id,
            fornecedor="não deve persistir",
            valor=Decimal("4500.00"),
            data_vencimento=date(2026, 10, 1),
        ),
    )
    assert created.client_id == client.id
    assert created.proposal_id == proposal.id
    assert created.fornecedor is None


def test_create_payable_clears_client_and_keeps_optional_proposal(db):
    client, proposal = make_references(db)
    created = lancamento_service.create_lancamento(
        db,
        LancamentoCreate(
            tipo="pagar",
            descricao="Combustível",
            client_id=client.id,
            proposal_id=proposal.id,
            fornecedor="Posto Central",
            valor=Decimal("300.00"),
            data_vencimento=date(2026, 9, 5),
        ),
    )
    assert created.client_id is None
    assert created.proposal_id == proposal.id
    assert created.fornecedor == "Posto Central"


def test_list_orders_by_due_date_then_descending_id(db):
    for description, due_date in [
        ("Segundo", date(2026, 9, 2)),
        ("Primeiro antigo", date(2026, 9, 1)),
        ("Primeiro novo", date(2026, 9, 1)),
    ]:
        db.add(Lancamento(tipo="pagar", descricao=description, valor=10, data_vencimento=due_date))
        db.flush()
    db.commit()
    assert [item.descricao for item in lancamento_service.list_lancamentos(db, "pagar")] == [
        "Primeiro novo",
        "Primeiro antigo",
        "Segundo",
    ]


def test_move_sets_and_clears_payment_date(db, monkeypatch):
    fixed_today = date(2026, 8, 27)
    entry = Lancamento(tipo="receber", descricao="Serviço", valor=100, data_vencimento=fixed_today)
    db.add(entry)
    db.commit()
    monkeypatch.setattr(lancamento_service, "today", lambda: fixed_today)

    paid = lancamento_service.move_lancamento(db, entry.id, LancamentoMove(status="pago"))
    assert paid.status == "pago"
    assert paid.data_pagamento == fixed_today

    pending = lancamento_service.move_lancamento(db, entry.id, LancamentoMove(status="pendente"))
    assert pending.status == "pendente"
    assert pending.data_pagamento is None


def test_update_paid_entry_uses_supplied_payment_date(db):
    entry = Lancamento(
        tipo="pagar",
        descricao="Conta antiga",
        valor=100,
        data_vencimento=date(2026, 9, 1),
    )
    db.add(entry)
    db.commit()
    updated = lancamento_service.update_lancamento(
        db,
        entry.id,
        "pagar",
        LancamentoUpdate(
            descricao="Conta corrigida",
            fornecedor="Fornecedor",
            valor=Decimal("120.00"),
            data_emissao=date(2026, 8, 27),
            data_vencimento=date(2026, 9, 10),
            status="pago",
            data_pagamento=date(2026, 8, 28),
        ),
    )
    assert updated.descricao == "Conta corrigida"
    assert updated.valor == Decimal("120.00")
    assert updated.data_pagamento == date(2026, 8, 28)


def test_edit_url_type_cannot_cross_financial_board(db):
    entry = Lancamento(tipo="pagar", descricao="Conta", valor=100, data_vencimento=date(2026, 9, 1))
    db.add(entry)
    db.commit()
    with pytest.raises(HTTPException) as exc_info:
        lancamento_service.get_lancamento(db, entry.id, tipo="receber")
    assert exc_info.value.status_code == 404


def test_is_atrasado_only_for_unpaid_past_due_entries():
    today_value = date(2026, 8, 27)
    pending = Lancamento(status="pendente", data_vencimento=date(2026, 8, 26))
    paid = Lancamento(status="pago", data_vencimento=date(2026, 8, 26))
    assert lancamento_service.is_atrasado(pending, today_value) is True
    assert lancamento_service.is_atrasado(paid, today_value) is False


def test_proposal_creation_does_not_create_financial_entry(db):
    client, proposal = make_references(db)
    created = proposal_service.create_proposal(
        db,
        ProposalCreate(client_id=client.id, user_id=proposal.user_id),
    )
    assert created.id is not None
    assert db.query(Lancamento).count() == 0
```

- [ ] **Step 2: Confirmar falha por ausência do service**

Run: `python -m pytest tests/test_lancamento_service.py -v`

Expected: import fails because `app.services.lancamento_service` does not exist.

- [ ] **Step 3: Implementar o service com validação centralizada**

Criar `app/services/lancamento_service.py` com estas assinaturas e regras:

```python
from __future__ import annotations

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models import Client, Lancamento, Proposal
from app.schemas import LancamentoCreate, LancamentoMove, LancamentoUpdate

TIPOS = {"receber", "pagar"}


def today() -> date:
    return date.today()


def _validate_tipo(tipo: str) -> None:
    if tipo not in TIPOS:
        raise ValueError("Tipo de lançamento inválido.")


def _validate_references(db: Session, client_id: int | None, proposal_id: int | None) -> None:
    if client_id is not None and db.get(Client, client_id) is None:
        raise ValueError("Cliente não encontrado.")
    if proposal_id is not None and db.get(Proposal, proposal_id) is None:
        raise ValueError("Proposta não encontrada.")


def _payment_date(status_value: str, supplied: date | None) -> date | None:
    if status_value == "pendente":
        return None
    return supplied or today()


def _supplier_for(tipo: str, supplied: str | None) -> str | None:
    if tipo != "pagar":
        return None
    return (supplied or "").strip() or None


def list_lancamentos(db: Session, tipo: str) -> list[Lancamento]:
    _validate_tipo(tipo)
    return (
        db.query(Lancamento)
        .options(joinedload(Lancamento.client), joinedload(Lancamento.proposal))
        .filter(Lancamento.tipo == tipo)
        .order_by(Lancamento.data_vencimento.asc(), Lancamento.id.desc())
        .all()
    )


def get_lancamento(db: Session, lancamento_id: int, tipo: str | None = None) -> Lancamento:
    query = db.query(Lancamento).options(
        joinedload(Lancamento.client), joinedload(Lancamento.proposal)
    ).filter(Lancamento.id == lancamento_id)
    if tipo is not None:
        _validate_tipo(tipo)
        query = query.filter(Lancamento.tipo == tipo)
    entry = query.first()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lançamento não encontrado.")
    return entry


def create_lancamento(db: Session, payload: LancamentoCreate) -> Lancamento:
    client_id = payload.client_id if payload.tipo == "receber" else None
    fornecedor = _supplier_for(payload.tipo, payload.fornecedor)
    _validate_references(db, client_id, payload.proposal_id)
    entry = Lancamento(
        tipo=payload.tipo,
        descricao=payload.descricao,
        client_id=client_id,
        proposal_id=payload.proposal_id,
        fornecedor=fornecedor,
        valor=payload.valor,
        data_emissao=payload.data_emissao,
        data_vencimento=payload.data_vencimento,
        status=payload.status,
        data_pagamento=_payment_date(payload.status, payload.data_pagamento),
    )
    db.add(entry)
    db.commit()
    return get_lancamento(db, entry.id)


def update_lancamento(
    db: Session,
    lancamento_id: int,
    tipo: str,
    payload: LancamentoUpdate,
) -> Lancamento:
    entry = get_lancamento(db, lancamento_id, tipo=tipo)
    client_id = payload.client_id if tipo == "receber" else None
    fornecedor = _supplier_for(tipo, payload.fornecedor)
    _validate_references(db, client_id, payload.proposal_id)
    entry.descricao = payload.descricao
    entry.client_id = client_id
    entry.proposal_id = payload.proposal_id
    entry.fornecedor = fornecedor
    entry.valor = payload.valor
    entry.data_emissao = payload.data_emissao
    entry.data_vencimento = payload.data_vencimento
    entry.status = payload.status
    entry.data_pagamento = _payment_date(payload.status, payload.data_pagamento)
    db.commit()
    return get_lancamento(db, entry.id)


def move_lancamento(db: Session, lancamento_id: int, payload: LancamentoMove) -> Lancamento:
    entry = get_lancamento(db, lancamento_id)
    entry.status = payload.status
    entry.data_pagamento = today() if payload.status == "pago" else None
    db.commit()
    return get_lancamento(db, entry.id)


def is_atrasado(entry: Lancamento, today_value: date) -> bool:
    return entry.status != "pago" and entry.data_vencimento < today_value
```

- [ ] **Step 4: Executar testes e commitar**

Run: `python -m pytest tests/test_lancamento_service.py -v`

Expected: all service tests pass.

```bash
git add app/services/lancamento_service.py tests/test_lancamento_service.py
git commit -m "feat: add financial entry service"
```

---

### Task 3: API JSON de movimentação

**Files:**
- Create: `app/routers/financeiro.py`
- Create: `tests/test_financeiro_routes.py`
- Modify: `app/main.py:13,63`

**Interfaces:**
- Consumes: `move_lancamento` e `LancamentoMove` das Tasks 1–2.
- Produces: `POST /api/lancamentos/{id}/move`, registrado na aplicação.

- [ ] **Step 1: Criar testes de rotas antes do router**

Criar `tests/test_financeiro_routes.py` com os testes da API:

```python
from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.models import Lancamento


def test_move_endpoint_returns_updated_payment_state(db):
    entry = Lancamento(tipo="receber", descricao="Serviço", valor=10, data_vencimento=date(2026, 9, 1))
    db.add(entry)
    db.commit()
    with TestClient(app) as client:
        response = client.post(f"/api/lancamentos/{entry.id}/move", json={"status": "pago"})
    assert response.status_code == 200
    assert response.json()["status"] == "pago"
    assert response.json()["data_pagamento"] is not None


def test_move_endpoint_rejects_invalid_status(db):
    entry = Lancamento(tipo="pagar", descricao="Conta", valor=10, data_vencimento=date(2026, 9, 1))
    db.add(entry)
    db.commit()
    with TestClient(app) as client:
        response = client.post(f"/api/lancamentos/{entry.id}/move", json={"status": "cancelado"})
    assert response.status_code == 422
```

- [ ] **Step 2: Executar e confirmar 404/falhas de rota**

Run: `python -m pytest tests/test_financeiro_routes.py -v`

Expected: the move URL returns 404 because the router is not registered.

- [ ] **Step 3: Implementar o router inicial somente com a API**

Criar `app/routers/financeiro.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import LancamentoMove, LancamentoRead
from app.services import lancamento_service

router = APIRouter(tags=["financeiro"])


@router.post("/api/lancamentos/{lancamento_id}/move", response_model=LancamentoRead)
def api_move_lancamento(
    lancamento_id: int,
    payload: LancamentoMove,
    db: Session = Depends(get_db),
) -> object:
    return lancamento_service.move_lancamento(db, lancamento_id, payload)
```

- [ ] **Step 4: Registrar o router no app**

Em `app/main.py`:

```python
from app.routers import board, clients, financeiro, imports, pages, proposals, users

app.include_router(financeiro.router)
```

- [ ] **Step 5: Rodar os testes e commitar**

Run: `python -m pytest tests/test_financeiro_routes.py -v`

Expected: both API route tests pass.

```bash
git add app/routers/financeiro.py app/main.py tests/test_financeiro_routes.py
git commit -m "feat: add financial entry move API"
```

---

### Task 4: Murais, formulários, navegação e drag-and-drop compartilhado

**Files:**
- Create: `app/templates_web/lancamentos_board.html`
- Create: `app/templates_web/lancamento_form.html`
- Create: `app/templates_web/_kanban_drag.html`
- Modify: `app/routers/financeiro.py`
- Modify: `app/templates_web/base.html:1-746,760-767`
- Modify: `app/templates_web/board.html:14-259`
- Modify: `tests/test_financeiro_routes.py`

**Interfaces:**
- Consumes: API da Task 3, service financeiro e `render_template` de `app.routers.pages`.
- Produces: dez rotas web, contexto `config`, `pendentes`, `pagos`, `today`, `is_atrasado`, `clients`, `proposals`, `entry`, `form_data`, `action_url` e `error`, além de HTML responsivo e drag-and-drop com rollback.

- [ ] **Step 1: Ampliar testes HTML antes dos templates finais**

Adicionar a `tests/test_financeiro_routes.py`:

```python
from app.db import SessionLocal


def test_create_receivable_redirects_and_persists():
    with TestClient(app) as client:
        response = client.post(
            "/web/contas-a-receber/new",
            data={
                "descricao": "Manutenção",
                "valor": "1.250,50",
                "data_emissao": "2026-08-27",
                "data_vencimento": "2026-09-27",
                "status": "pendente",
                "client_id": "",
                "proposal_id": "",
            },
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"].endswith("/web/contas-a-receber")
    with SessionLocal() as db:
        entry = db.query(Lancamento).one()
        assert entry.tipo == "receber"
        assert str(entry.valor) == "1250.50"


def test_invalid_form_rerenders_with_message():
    with TestClient(app) as client:
        response = client.post(
            "/web/contas-a-pagar/new",
            data={
                "descricao": "",
                "valor": "0",
                "data_emissao": "2026-08-27",
                "data_vencimento": "2026-09-01",
                "status": "pendente",
            },
        )
    assert response.status_code == 400
    assert "Verifique os campos informados" in response.text


def test_cross_type_edit_returns_404(db):
    entry = Lancamento(tipo="pagar", descricao="Conta", valor=10, data_vencimento=date(2026, 9, 1))
    db.add(entry)
    db.commit()
    with TestClient(app) as client:
        response = client.get(f"/web/contas-a-receber/{entry.id}/edit")
    assert response.status_code == 404


def test_boards_filter_type_and_mark_only_pending_overdue(db):
    db.add_all([
        Lancamento(tipo="receber", descricao="Receber atrasado", valor=10, data_vencimento=date(2020, 1, 1), status="pendente"),
        Lancamento(tipo="receber", descricao="Receber pago", valor=20, data_vencimento=date(2020, 1, 1), status="pago", data_pagamento=date(2020, 1, 2)),
        Lancamento(tipo="pagar", descricao="Pagar oculto", valor=30, data_vencimento=date(2020, 1, 1), status="pendente"),
    ])
    db.commit()
    with TestClient(app) as client:
        response = client.get("/web/contas-a-receber")
    assert response.status_code == 200
    assert "Receber atrasado" in response.text
    assert "Pagar oculto" not in response.text
    assert response.text.count('class="kanban-card is-overdue"') == 1


def test_navigation_contains_both_financial_links():
    with TestClient(app) as client:
        response = client.get("/web/contas-a-pagar")
    assert 'href="/web/contas-a-receber"' in response.text
    assert 'href="/web/contas-a-pagar"' in response.text


def test_shared_drag_script_has_rollback_and_error_region():
    with TestClient(app) as client:
        response = client.get("/web/contas-a-pagar")
    assert "originZone" in response.text
    assert "originNextSibling" in response.text
    assert 'role="alert"' in response.text
    assert "/api/lancamentos/{id}/move" in response.text
```

- [ ] **Step 2: Confirmar falhas de conteúdo**

Run: `python -m pytest tests/test_financeiro_routes.py -v`

Expected: assertions de HTML falham até templates, CSS e include existirem.

- [ ] **Step 3: Acrescentar as rotas web e o parser de formulário**

Em `app/routers/financeiro.py`, definir um `BOARD_CONFIG` central para `receber` e `pagar`, com `board_url`, `new_url`, `edit_prefix`, `page_title`, `pending_label` e `new_label`. Adicionar:

```python
from datetime import date

from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.models import Client, Proposal
from app.routers.pages import render_template
from app.schemas import LancamentoCreate, LancamentoUpdate
from app.utils.formatters import decimal_from_str

BOARD_CONFIG = {
    "receber": {
        "board_url": "/web/contas-a-receber",
        "new_url": "/web/contas-a-receber/new",
        "edit_prefix": "/web/contas-a-receber",
        "page_title": "Contas a Receber",
        "pending_label": "A Receber",
        "new_label": "Novo recebimento",
    },
    "pagar": {
        "board_url": "/web/contas-a-pagar",
        "new_url": "/web/contas-a-pagar/new",
        "edit_prefix": "/web/contas-a-pagar",
        "page_title": "Contas a Pagar",
        "pending_label": "A Pagar",
        "new_label": "Novo pagamento",
    },
}


def _optional_int(value: object) -> int | None:
    text = str(value or "").strip()
    return int(text) if text else None


def _parse_payload(form, tipo: str, *, update: bool):
    values = {
        "descricao": str(form.get("descricao", "")).strip(),
        "client_id": _optional_int(form.get("client_id")),
        "proposal_id": _optional_int(form.get("proposal_id")),
        "fornecedor": str(form.get("fornecedor", "")).strip() or None,
        "valor": decimal_from_str(str(form.get("valor", ""))),
        "data_emissao": date.fromisoformat(str(form.get("data_emissao", ""))),
        "data_vencimento": date.fromisoformat(str(form.get("data_vencimento", ""))),
        "status": str(form.get("status", "pendente")),
        "data_pagamento": (
            date.fromisoformat(str(form.get("data_pagamento")))
            if form.get("data_pagamento") else None
        ),
    }
    return LancamentoUpdate(**values) if update else LancamentoCreate(tipo=tipo, **values)


def _board(request: Request, tipo: str, db: Session) -> object:
    entries = lancamento_service.list_lancamentos(db, tipo)
    return render_template(request, "lancamentos_board.html", {
        "config": BOARD_CONFIG[tipo],
        "tipo": tipo,
        "pendentes": [entry for entry in entries if entry.status == "pendente"],
        "pagos": [entry for entry in entries if entry.status == "pago"],
        "today": date.today(),
        "is_atrasado": lancamento_service.is_atrasado,
    })
```

Criar `_form_context` para carregar `Client` por razão social e `Proposal` por número/ID descendentes. Criar `_submit` para chamar `create_lancamento` ou `update_lancamento`; capturar somente `ValidationError` e `ValueError`, reapresentar `lancamento_form.html`, definir `response.status_code = 400` e usar `error="Verifique os campos informados."`. Deixar `HTTPException` 404 do service propagar.

Registrar as rotas nesta ordem, garantindo que `/new` venha antes de `/{lancamento_id}/edit`:

```python
@router.get("/web/contas-a-receber", name="web_contas_receber")
@router.get("/web/contas-a-pagar", name="web_contas_pagar")
@router.get("/web/contas-a-receber/new", name="web_contas_receber_new")
@router.post("/web/contas-a-receber/new")
@router.get("/web/contas-a-receber/{lancamento_id}/edit", name="web_contas_receber_edit")
@router.post("/web/contas-a-receber/{lancamento_id}/edit")
@router.get("/web/contas-a-pagar/new", name="web_contas_pagar_new")
@router.post("/web/contas-a-pagar/new")
@router.get("/web/contas-a-pagar/{lancamento_id}/edit", name="web_contas_pagar_edit")
@router.post("/web/contas-a-pagar/{lancamento_id}/edit")
```

Cada wrapper deve chamar `_board`, `_form_context` ou `_submit` com o tipo literal correspondente; após sucesso, retornar `RedirectResponse(config["board_url"], status_code=303)`.

- [ ] **Step 4: Mover o estilo estrutural do board para `base.html`**

Adicionar classes `.kanban-board`, `.kanban-column`, `.kanban-column-title`, `.kanban-dropzone`, `.kanban-card`, `.kanban-card.dragging`, `.kanban-card.is-overdue`, `.kanban-card-header`, `.kanban-card-title`, `.kanban-card-meta` e `.kanban-error`. Usar:

```css
.kanban-board {
  display: grid;
  grid-template-columns: repeat(var(--kanban-columns, 4), minmax(0, 1fr));
  gap: 16px;
  margin-top: 10px;
  align-items: start;
}
.kanban-card.is-overdue {
  border-color: var(--danger);
  background: color-mix(in srgb, var(--danger) 8%, var(--surface));
}
.kanban-error {
  display: none;
  color: var(--danger);
  margin-top: 10px;
}
.kanban-error.visible { display: block; }
@media (max-width: 1024px) {
  .kanban-board { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .kanban-board { grid-template-columns: minmax(0, 1fr); }
}
```

Replicar nas classes genéricas os valores atuais de borda, raio, padding, sombra, overflow e tipografia de `board.html`; depois remover o bloco `<style>` local para existir uma única fonte visual.

- [ ] **Step 5: Criar o include genérico de drag-and-drop**

Criar `app/templates_web/_kanban_drag.html`. O script deve ler `data-endpoint-template` e `data-ordered`, guardar `originZone` e `originNextSibling` no `dragstart`, enviar `{status}` para finanças e `{status, ordem}` para tarefas. Em erro HTTP/rede, recolocar o card na origem, restaurar contadores e mostrar o `role="alert"`; em sucesso, atualizar contadores.

Código central obrigatório:

```javascript
const board = document.querySelector('[data-kanban-board]');
const errorRegion = board.querySelector('[data-kanban-error]');
let draggedCard = null;
let originZone = null;
let originNextSibling = null;

function rollback() {
  if (originNextSibling && originNextSibling.parentNode === originZone) {
    originZone.insertBefore(draggedCard, originNextSibling);
  } else {
    originZone.appendChild(draggedCard);
  }
  updateCounters();
  errorRegion.textContent = 'Não foi possível mover o card. Tente novamente.';
  errorRegion.classList.add('visible');
}

const payload = { status: newStatus };
if (board.dataset.ordered === 'true') {
  payload.ordem = [...zone.querySelectorAll('.kanban-card')].indexOf(draggedCard);
}
const endpoint = board.dataset.endpointTemplate.replace('{id}', draggedCard.dataset.id);
const response = await fetch(endpoint, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
});
if (!response.ok) rollback();
```

Completar handlers de `dragstart`, `dragend`, `dragover`, `drop`, `getDragAfterElement` e `updateCounters` com escopo restrito ao board atual. Desabilitar movimentação dentro da mesma coluna quando `data-ordered="false"`, deixando o card na posição definida pela ordenação original.

- [ ] **Step 6: Adaptar o quadro de tarefas ao include sem mudar contrato**

Em `board.html`, substituir classes locais por `.kanban-*`, configurar:

```html
<div class="kanban-board" data-kanban-board data-ordered="true"
     data-endpoint-template="/api/tasks/{id}/move" style="--kanban-columns: 4;">
```

Adicionar `<p class="kanban-error" data-kanban-error role="alert"></p>` e `{% include "_kanban_drag.html" %}`. Manter quatro colunas, links, badges, `data-id`, status e payload `ordem` atuais.

- [ ] **Step 7: Criar o mural financeiro parametrizado**

Em `lancamentos_board.html`, renderizar duas colunas a partir de `pendentes` e `pagos`, usando:

```html
<div class="kanban-board" data-kanban-board data-ordered="false"
     data-endpoint-template="/api/lancamentos/{id}/move" style="--kanban-columns: 2;">
```

Cada card deve ter exatamente `class="kanban-card{% if is_atrasado(entry, today) %} is-overdue{% endif %}"`, link de edição do tipo correto, `format_brl(entry.valor)`, `format_date_br(entry.data_vencimento)`, cliente para receber e fornecedor para pagar. Mostrar link da proposta somente no mural de contas a receber e somente quando presente. Incluir região `role="alert"` e `_kanban_drag.html`.

- [ ] **Step 8: Criar o formulário compartilhado**

Em `lancamento_form.html`, usar `.card`, `.form-grid-2`, `.form-grid-3`, `.field`, `.btn` e `.badge`. Renderizar:

- descrição, valor, emissão, vencimento e status para os dois tipos;
- cliente somente em receber;
- fornecedor somente em pagar;
- proposta opcional nos dois tipos;
- data de pagamento apenas em edição ou quando status for pago;
- `error` em região `role="alert"`;
- cancelar apontando para `config.board_url`.

Usar `form_data` tanto no primeiro acesso quanto em reapresentação após erro, evitando perda do que foi digitado.

- [ ] **Step 9: Adicionar navegação**

Após “Quadro” em `base.html`:

```html
<a href="/web/contas-a-receber" class="{% if request.url.path.startswith('/web/contas-a-receber') %}active{% endif %}">Contas a Receber</a>
<a href="/web/contas-a-pagar" class="{% if request.url.path.startswith('/web/contas-a-pagar') %}active{% endif %}">Contas a Pagar</a>
```

- [ ] **Step 10: Rodar testes do módulo e regressão do Kanban**

Run:

```bash
python -m pytest tests/test_lancamento_model.py tests/test_lancamento_service.py tests/test_financeiro_routes.py -v
python -m compileall -q app tests
git diff --check
```

Expected: all tests pass, compilation exits 0 and `git diff --check` has no output.

- [ ] **Step 11: Commitar UI e comportamento compartilhado**

```bash
git add app/routers/financeiro.py app/templates_web/base.html app/templates_web/board.html app/templates_web/_kanban_drag.html app/templates_web/lancamentos_board.html app/templates_web/lancamento_form.html tests/test_financeiro_routes.py
git commit -m "feat: add receivable and payable boards"
```

---

### Task 5: Verificação integrada em PostgreSQL e preservação do fluxo existente

**Files:**
- Verify only: `docker-compose.yml`, `app/routers/pages.py`, `app/services/proposal_service.py`, `app/templates_web/proposal_form.html`

**Interfaces:**
- Consumes: aplicação completa das Tasks 1–4.
- Produces: evidência de schema, rotas, regressão e ausência de alterações fora do escopo.

- [ ] **Step 1: Executar a suíte completa e verificações estáticas**

```bash
python -m pytest -v
python -m compileall -q app tests
git diff --check
```

Expected: zero falhas, zero erros de compilação e nenhuma saída de `git diff --check`.

- [ ] **Step 2: Confirmar que o escopo de propostas permaneceu intocado**

```bash
git diff 96c53d0..HEAD -- app/routers/pages.py app/services/proposal_service.py app/templates_web/proposal_form.html app/templates_web/client_form.html app/routers/clients.py
```

Expected: no output.

- [ ] **Step 3: Subir a stack compatível com PostgreSQL**

```bash
docker compose up -d --build
docker compose ps
curl -fsS http://localhost:8000/healthz
```

Expected: `db` e `app` healthy; health retorna `{"status":"ok"}`.

- [ ] **Step 4: Inspecionar tabela e política das FKs no PostgreSQL**

```bash
docker compose exec app python -c "from sqlalchemy import inspect; from app.db import engine; i=inspect(engine); print(i.has_table('lancamentos')); print([(fk['constrained_columns'], fk.get('options', {})) for fk in i.get_foreign_keys('lancamentos')])"
```

Expected: `True`; as FKs de `client_id` e `proposal_id` exibem `ondelete` como `SET NULL`.

- [ ] **Step 5: Fazer UAT no navegador**

Validar em desktop e viewport móvel:

1. Criar uma conta a receber com cliente e proposta opcionais.
2. Criar uma conta a pagar com fornecedor e vencimento manual.
3. Confirmar ordenação por vencimento e destaque vermelho de pendente atrasado.
4. Mover um card para Pago e confirmar persistência após recarregar.
5. Mover o card de volta e confirmar limpeza de `data_pagamento`.
6. Simular falha da API pelo DevTools e confirmar rollback e mensagem acessível.
7. Tentar abrir um lançamento pagar pela URL de edição receber e confirmar 404.
8. Abrir o Quadro de tarefas, mover cards entre colunas e reordenar na mesma coluna.
9. Criar, revisar e clonar uma proposta; gerar DOCX/PDF e confirmar que nenhum lançamento é criado.

- [ ] **Step 6: Registrar evidências finais sem novo commit vazio**

Run:

```bash
git status --short
git log --oneline --decorate -5
```

Expected: árvore limpa e quatro commits de implementação separados por domínio, service, API e UI web.
