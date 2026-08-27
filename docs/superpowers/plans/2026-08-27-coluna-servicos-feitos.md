# Coluna Servicos Feitos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar ao Kanban a coluna "Servicos Feitos - Falta Nota/Pedido" entre Em Andamento e Aguardando Cliente.

**Architecture:** O novo estado usa o campo textual `Task.status` existente, sem migration. O router passa a agrupar o novo valor, os dois templates o exibem na ordem aprovada e a API de movimentacao continua inalterada.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Jinja2, JavaScript puro, pytest e HTTPX.

## Global Constraints

- Usar o status `servico_feito_falta_nota_pedido`.
- Exibir o titulo `Servicos Feitos - Falta Nota/Pedido`.
- Nao alterar banco, propostas, clientes ou financeiro.
- Reutilizar o Kanban e o drag-and-drop existentes.
- Nao criar commit sem autorizacao do usuario.

---

### Task 1: Adicionar e validar a quinta etapa do Kanban

**Files:**
- Create: `tests/test_board_statuses.py`
- Modify: `app/routers/board.py:22-28`
- Modify: `app/templates_web/board.html:16-24`
- Modify: `app/templates_web/board_form.html:23-28`

**Interfaces:**
- Consumes: `POST /api/tasks/{task_id}/move` e `TaskMove(status: str, ordem: int)` existentes.
- Produces: grupo `board_data["servico_feito_falta_nota_pedido"]`, quinta coluna e opcao de formulario com o mesmo valor.

- [ ] **Step 1: Escrever testes de renderizacao, formulario e movimentacao**

Criar `tests/test_board_statuses.py` com testes que:

```python
def test_board_shows_service_done_column_in_approved_order():
    # GET /web/board; conferir os cinco data-status e sua ordem.

def test_task_form_offers_service_done_status():
    # GET /web/board/new; conferir value e texto da opcao.

def test_move_task_to_service_done_status_persists(db):
    # Criar Task, POST na API e conferir resposta e valor persistido.
```

- [ ] **Step 2: Executar os testes e confirmar a falha esperada**

Run: `python3 -m pytest tests/test_board_statuses.py -q`

Expected: falha porque a nova coluna e a opcao ainda nao existem.

- [ ] **Step 3: Implementar o agrupamento e as duas superficies visuais**

Adicionar `"servico_feito_falta_nota_pedido": []` depois de `em_andamento` em `board_data`. Em `board.html`, adicionar a tupla:

```python
('servico_feito_falta_nota_pedido', 'Servicos Feitos - Falta Nota/Pedido', 'primary')
```

e alterar `--kanban-columns` de 4 para 5. Em `board_form.html`, adicionar a opcao equivalente depois de Em Andamento.

- [ ] **Step 4: Executar o teste focado e a suite completa**

Run: `python3 -m pytest tests/test_board_statuses.py -q`

Expected: `3 passed`.

Run: `python3 -m pytest -q`

Expected: todos os testes aprovados.

- [ ] **Step 5: Validar no Docker sem commit**

Run: `docker compose up -d --build`

Run: `docker compose exec -T app pip install -q -r requirements-dev.txt && docker compose exec -T app python -m pytest -q`

Expected: container saudavel e suite completa aprovada. Nao executar `git commit`.
