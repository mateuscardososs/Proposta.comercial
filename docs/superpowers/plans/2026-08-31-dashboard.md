# Dashboard executivo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir a página inicial atual por um dashboard de leitura com indicadores agregados de financeiro, tarefas e propostas do mês.

**Architecture:** Um novo `dashboard_service.py` calcula um contrato imutável com exatamente três consultas agregadas, sem carregar registros completos. A rota `/` permanece em `pages.py`, chama esse service e renderiza os nove KPIs com os componentes existentes de `base.html`.

**Tech Stack:** Python 3.12, FastAPI 0.116.1, SQLAlchemy 2.0.44, PostgreSQL 16, Jinja2 3.1.6, pytest 8.4.2 e HTTPX 0.28.1.

## Global Constraints

- Não criar ou alterar models, tabelas, migrations ou schemas persistentes.
- Manter `GET /` como rota canônica e o item “Início” da navbar.
- Executar no máximo três consultas SQL de leitura para montar o resumo.
- Usar agregações SQL (`COUNT`, `SUM`, `CASE`, `COALESCE`) em vez de carregar coleções.
- Considerar vencido/atrasado somente quando a data for estritamente menor que hoje.
- Contar como tarefa atrasada qualquer status diferente de `concluido`.
- Exibir KPIs de coluna somente para `a_fazer` e `em_andamento`.
- Reutilizar `.card`, `.kpi-grid`, `.kpi-card`, `.badge`, `.btn` e `var(--danger)`.
- Não adicionar funcionalidades futuras, gráficos, listas detalhadas ou polling.
- Não alterar fluxos de propostas, Kanban ou financeiro.
- Não criar commit sem autorização explícita do usuário.

---

### Task 1: Service agregado e contrato do dashboard

**Files:**
- Create: `app/services/dashboard_service.py`
- Create: `tests/test_dashboard_service.py`

**Interfaces:**
- Consumes: `Task`, `Lancamento`, `Proposal` e uma `Session` SQLAlchemy existente.
- Produces: `DashboardSummary` e `get_dashboard_summary(db: Session, reference_date: date | None = None) -> DashboardSummary`.

- [ ] **Step 1: Escrever o teste abrangente das regras de agregação**

Criar `tests/test_dashboard_service.py` com `reference_date=date(2026, 8, 31)` e os seguintes registros exatos:

- receber pendente: `100.00` vencido em `2026-08-30`, `50.00` vencendo em `2026-08-31` e `200.00` vencendo em `2026-09-10`;
- receber pago: `999.00` vencido em `2026-08-01`, que deve ser ignorado;
- pagar pendente: `70.00` vencido em `2026-08-30`, `20.00` vencendo em `2026-08-31` e `30.00` vencendo em `2026-09-10`;
- pagar pago: `888.00` vencido em `2026-08-01`, que deve ser ignorado;
- duas tarefas `a_fazer`, uma vencida e uma futura;
- uma tarefa `em_andamento` vencida;
- uma tarefa `servico_feito_falta_nota_pedido` vencida;
- uma tarefa `aguardando_cliente` vencida;
- uma tarefa `concluido` vencida, que deve ser ignorada no atraso;
- uma tarefa `servico_feito_falta_nota_pedido` sem prazo, que também deve ser ignorada no atraso;
- propostas de `500.00` em `2026-08-01` e `1000.00` em `2026-08-31`;
- propostas em `2026-07-31` e `2026-09-01`, que devem ficar fora do mês.

Criar um `Client` e um `User` locais para satisfazer as FKs obrigatórias das propostas; não usar `proposal_service`, pois o teste deve isolar as agregações do dashboard.

O teste principal deve usar `reference_date=date(2026, 8, 31)` e afirmar o contrato completo:

```python
summary = dashboard_service.get_dashboard_summary(
    db,
    reference_date=date(2026, 8, 31),
)

assert summary.receber_pendente == Decimal("350.00")
assert summary.receber_vencido == Decimal("100.00")
assert summary.pagar_pendente == Decimal("120.00")
assert summary.pagar_vencido == Decimal("70.00")
assert summary.tarefas_atrasadas == 4
assert summary.tarefas_a_fazer == 2
assert summary.tarefas_em_andamento == 1
assert summary.propostas_mes_quantidade == 2
assert summary.propostas_mes_valor == Decimal("1500.00")
assert summary.mes_inicio == date(2026, 8, 1)
assert summary.mes_fim_exclusivo == date(2026, 9, 1)
```

Os dados de teste devem demonstrar separadamente que:

- vencimento igual a `2026-08-31` não entra em vencido;
- lançamento pago não entra em pendente;
- tarefa concluída vencida não entra em atrasadas;
- tarefa sem prazo não entra em atrasadas;
- os dois status adicionais do quadro entram em atrasadas quando o prazo venceu, mas não alteram os KPIs A Fazer/Em Andamento.

- [ ] **Step 2: Executar o teste e confirmar a falha inicial**

Run:

```bash
python3 -m pytest tests/test_dashboard_service.py -q
```

Expected: erro de importação porque `app.services.dashboard_service` ainda não existe.

- [ ] **Step 3: Criar o contrato imutável e o cálculo de período**

Criar `app/services/dashboard_service.py` com:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session

from app.models import Lancamento, Proposal, Task


ZERO = Decimal("0.00")


@dataclass(frozen=True)
class DashboardSummary:
    receber_pendente: Decimal
    receber_vencido: Decimal
    pagar_pendente: Decimal
    pagar_vencido: Decimal
    tarefas_atrasadas: int
    tarefas_a_fazer: int
    tarefas_em_andamento: int
    propostas_mes_quantidade: int
    propostas_mes_valor: Decimal
    mes_inicio: date
    mes_fim_exclusivo: date


def _month_bounds(reference_date: date) -> tuple[date, date]:
    month_start = reference_date.replace(day=1)
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    return month_start, next_month


def _money(value: object) -> Decimal:
    return Decimal(value or ZERO).quantize(Decimal("0.01"))
```

- [ ] **Step 4: Implementar a consulta financeira única**

Dentro de `get_dashboard_summary`, definir `today_value = reference_date or date.today()` e executar uma única query filtrada por `status == "pendente"`. Ela deve retornar quatro somas condicionais:

```python
financial = db.query(
    func.coalesce(func.sum(case(
        (Lancamento.tipo == "receber", Lancamento.valor),
        else_=0,
    )), 0),
    func.coalesce(func.sum(case(
        (and_(
            Lancamento.tipo == "receber",
            Lancamento.data_vencimento < today_value,
        ), Lancamento.valor),
        else_=0,
    )), 0),
    func.coalesce(func.sum(case(
        (Lancamento.tipo == "pagar", Lancamento.valor),
        else_=0,
    )), 0),
    func.coalesce(func.sum(case(
        (and_(
            Lancamento.tipo == "pagar",
            Lancamento.data_vencimento < today_value,
        ), Lancamento.valor),
        else_=0,
    )), 0),
).filter(Lancamento.status == "pendente").one()
```

- [ ] **Step 5: Implementar a consulta única de tarefas**

Executar uma query sem carregar `Task`:

```python
tasks = db.query(
    func.coalesce(func.sum(case(
        (and_(
            Task.status != "concluido",
            Task.prazo.is_not(None),
            Task.prazo < today_value,
        ), 1),
        else_=0,
    )), 0),
    func.coalesce(func.sum(case(
        (Task.status == "a_fazer", 1),
        else_=0,
    )), 0),
    func.coalesce(func.sum(case(
        (Task.status == "em_andamento", 1),
        else_=0,
    )), 0),
).one()
```

- [ ] **Step 6: Implementar a consulta única de propostas e montar o retorno**

Calcular `month_start, next_month = _month_bounds(today_value)` e executar:

```python
proposals = db.query(
    func.count(Proposal.id),
    func.coalesce(func.sum(Proposal.valor_total), 0),
).filter(
    Proposal.data_geracao >= month_start,
    Proposal.data_geracao < next_month,
).one()
```

Retornar `DashboardSummary`, normalizando dinheiro com `_money` e contadores com `int(value or 0)`.

- [ ] **Step 7: Executar o teste abrangente e confirmar que passa**

Run:

```bash
python3 -m pytest tests/test_dashboard_service.py -q
```

Expected: o teste principal de agregações passa.

- [ ] **Step 8: Adicionar testes de banco vazio, dezembro e orçamento de queries**

Adicionar os três testes completos abaixo. O teste de banco vazio afirma tipos e limites; o teste de dezembro cobre a virada de ano; o teste de orçamento instala temporariamente um listener no engine da sessão e o remove em `finally`:

```python
from sqlalchemy import event


def test_empty_database_returns_typed_zeroes(db):
    summary = dashboard_service.get_dashboard_summary(
        db,
        reference_date=date(2026, 8, 31),
    )

    assert summary.receber_pendente == Decimal("0.00")
    assert summary.receber_vencido == Decimal("0.00")
    assert summary.pagar_pendente == Decimal("0.00")
    assert summary.pagar_vencido == Decimal("0.00")
    assert summary.tarefas_atrasadas == 0
    assert summary.tarefas_a_fazer == 0
    assert summary.tarefas_em_andamento == 0
    assert summary.propostas_mes_quantidade == 0
    assert summary.propostas_mes_valor == Decimal("0.00")
    assert summary.mes_inicio == date(2026, 8, 1)
    assert summary.mes_fim_exclusivo == date(2026, 9, 1)


def test_december_uses_january_as_exclusive_upper_bound(db):
    summary = dashboard_service.get_dashboard_summary(
        db,
        reference_date=date(2026, 12, 15),
    )

    assert summary.mes_inicio == date(2026, 12, 1)
    assert summary.mes_fim_exclusivo == date(2027, 1, 1)


def test_dashboard_summary_executes_exactly_three_selects(db):
    selects: list[str] = []

    def capture_select(conn, cursor, statement, parameters, context, executemany):
        del conn, cursor, parameters, context, executemany
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", capture_select)
    try:
        dashboard_service.get_dashboard_summary(
            db,
            reference_date=date(2026, 8, 31),
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_select)

    assert len(selects) == 3
```

- [ ] **Step 9: Executar todos os testes do service**

Run:

```bash
python3 -m pytest tests/test_dashboard_service.py -q
```

Expected: todos os testes do service passam e o orçamento permanece em três `SELECT`s.

- [ ] **Step 10: Checkpoint sem commit**

Run:

```bash
git diff --check
git status --short
```

Expected: apenas o service, seus testes, a spec e este plano aparecem como alterações locais. Não executar `git commit`.

---

### Task 2: Rota inicial, template e destaque visual

**Files:**
- Create: `tests/test_dashboard_routes.py`
- Modify: `app/routers/pages.py:8-31,173-195`
- Modify: `app/templates_web/index.html:1-98`
- Modify: `app/templates_web/base.html:260-330`

**Interfaces:**
- Consumes: `dashboard_service.get_dashboard_summary(db) -> DashboardSummary` da Task 1.
- Produces: `GET /` renderizando `index.html` com `summary: DashboardSummary` e `full_width=True`.

- [ ] **Step 1: Escrever o teste do novo contrato da página inicial**

Criar `tests/test_dashboard_routes.py`. Inserir dados mínimos para produzir um valor vencido positivo e um KPI atrasado positivo; calcular datas em relação a `date.today()` para não depender do relógio fixo do teste.

O teste deve requisitar `GET /` e afirmar:

```python
assert response.status_code == 200
assert "Visão geral da empresa" in response.text
assert "Financeiro" in response.text
assert "Tarefas" in response.text
assert "Propostas do mês" in response.text
assert response.text.count('class="kpi-card') == 9
assert 'data-kpi="receber-vencido"' in response.text
assert 'data-kpi="tarefas-atrasadas"' in response.text
assert "is-danger" in response.text
assert "R$ 100,00" in response.text
assert 'class="layout-grid full-width"' in response.text
assert 'href="/" class="active"' in response.text
```

Também afirmar ausência do conteúdo antigo:

```python
assert "Clientes ativos" not in response.text
assert "Usuarios internos" not in response.text
assert "Ultimas propostas" not in response.text
assert "em breve" not in response.text.lower()
```

- [ ] **Step 2: Escrever o teste do estado zerado neutro**

Com o banco vazio, requisitar `/` e confirmar HTTP 200, nove KPIs, valores monetários `R$ 0,00` e ausência de `is-danger` nos cards `receber-vencido`, `pagar-vencido` e `tarefas-atrasadas`.

- [ ] **Step 3: Executar os testes de rota e confirmar a falha inicial**

Run:

```bash
python3 -m pytest tests/test_dashboard_routes.py -q
```

Expected: falhas porque a rota ainda fornece o contexto antigo e o template ainda mostra clientes/usuários/últimas propostas.

- [ ] **Step 4: Tornar `pages.index()` um controller fino**

Adicionar `dashboard_service` aos imports de services em `app/routers/pages.py` e substituir o corpo de `index` por:

```python
@router.get("/", name="web_index")
def index(request: Request, db: Session = Depends(get_db)) -> object:
    summary = dashboard_service.get_dashboard_summary(db)
    return render_template(
        request,
        "index.html",
        {"summary": summary, "full_width": True},
    )
```

Não remover imports de `Client`, `Proposal`, `User` ou `joinedload` sem confirmar seu uso nas demais rotas do mesmo arquivo.

- [ ] **Step 5: Adicionar somente o modificador visual de perigo ao design system**

Ao lado dos estilos existentes de `.kpi-card` e `.kpi-value` em `base.html`, adicionar:

```css
.kpi-card.is-danger {
  border-color: var(--danger);
  background: #fff2f3;
}

.kpi-card.is-danger .kpi-value {
  color: var(--danger);
}
```

Não criar um segundo componente de card nem novos tokens de cor.

- [ ] **Step 6: Substituir `index.html` pelo dashboard aprovado**

O template deve conter:

```jinja2
{% extends "base.html" %}
{% block content %}
<section class="page-header">
  <h1 class="page-title">Visão geral da empresa</h1>
  <p class="page-subtitle">Financeiro, tarefas e propostas em um único lugar.</p>
  <div class="meta-line">
    <span class="badge primary">Mês de referência: {{ summary.mes_inicio.strftime('%m/%Y') }}</span>
  </div>
</section>
```

Em seguida, renderizar três `<section class="card">`:

1. “Financeiro”, com quatro `.kpi-card` e `data-kpi` iguais a `receber-pendente`, `receber-vencido`, `pagar-pendente` e `pagar-vencido`;
2. “Tarefas”, com três `.kpi-card` e `data-kpi` iguais a `tarefas-atrasadas`, `tarefas-a-fazer` e `tarefas-em-andamento`;
3. “Propostas do mês”, com duas `.kpi-card` e `data-kpi` iguais a `propostas-mes-quantidade` e `propostas-mes-valor`.

Aplicar a classe condicional somente nos três KPIs de risco:

```jinja2
<article class="kpi-card{% if summary.receber_vencido > 0 %} is-danger{% endif %}"
         data-kpi="receber-vencido">
```

Repetir a condição para `pagar_vencido` e `tarefas_atrasadas`. Os quatro valores financeiros e o valor das propostas usam `format_brl`; contadores são exibidos como inteiros.

Não manter a tabela de últimas propostas, os KPIs de clientes/usuários ou os blocos `side_actions` antigos.

- [ ] **Step 7: Executar os testes de rota e ajustar somente o contrato aprovado**

Run:

```bash
python3 -m pytest tests/test_dashboard_routes.py -q
```

Expected: todos os testes da rota/template passam.

- [ ] **Step 8: Executar os testes do dashboard juntos**

Run:

```bash
python3 -m pytest tests/test_dashboard_service.py tests/test_dashboard_routes.py -q
```

Expected: agregações, orçamento de queries, rota e contrato visual passam em conjunto.

- [ ] **Step 9: Checkpoint sem commit**

Run:

```bash
git diff --check
git status --short
```

Expected: somente arquivos do dashboard, sua spec e seu plano estão alterados. Não executar `git commit`.

---

### Task 3: Regressão, Docker e verificação visual

**Files:**
- Verify: `app/services/dashboard_service.py`
- Verify: `app/routers/pages.py`
- Verify: `app/templates_web/index.html`
- Verify: `app/templates_web/base.html`
- Verify: `tests/test_dashboard_service.py`
- Verify: `tests/test_dashboard_routes.py`

**Interfaces:**
- Consumes: dashboard concluído pelas Tasks 1 e 2.
- Produces: evidência de compatibilidade com o projeto e lista explícita de qualquer validação indisponível.

- [ ] **Step 1: Executar a suíte completa local**

Run:

```bash
python3 -m pytest -q
```

Expected: todos os testes passam, incluindo os módulos de quadro e financeiro existentes.

- [ ] **Step 2: Compilar e validar o diff**

Run:

```bash
python3 -m compileall -q app tests
git diff --check
```

Expected: ambos terminam com exit code zero.

- [ ] **Step 3: Reconstruir o ambiente Docker**

Run:

```bash
docker compose up -d --build
```

Esperar até `propostas_app` e `propostas_db` aparecerem como `healthy` em `docker compose ps`.

- [ ] **Step 4: Executar a suíte com as versões fixadas no container**

Run:

```bash
docker compose exec -T app pip install -q -r requirements-dev.txt
docker compose exec -T app python -m pytest -q
```

Expected: suíte completa aprovada em Python 3.12.

- [ ] **Step 5: Verificar rotas sem mutar dados operacionais**

Fazer requisições GET e confirmar HTTP 200 para:

```text
/
/web/board
/web/contas-a-receber
/web/contas-a-pagar
/web/proposals
```

No HTML de `/`, confirmar nove `kpi-card`, `layout-grid full-width`, ausência de “Últimas propostas” e presença das três seções. Não criar, editar ou excluir registros reais durante esta verificação.

- [ ] **Step 6: Inspecionar visualmente desktop e mobile**

Em navegador conectado, validar:

- leitura clara das três seções;
- quatro KPIs financeiros sem colisão em desktop;
- empilhamento pelos breakpoints existentes em telas estreitas;
- contraste do estado `is-danger`;
- ausência de scroll horizontal causado pelo dashboard;
- item “Início” ativo.

Se um navegador conectado não estiver disponível, registrar essa limitação explicitamente em vez de declarar a inspeção visual concluída.

- [ ] **Step 7: Entregar sem commit**

Run:

```bash
git status --short
git diff --stat
```

Relatar arquivos alterados, resultados dos testes e validações indisponíveis. Não executar commit, push, merge ou alteração de histórico sem autorização explícita.
