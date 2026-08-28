# Quadro sem lateral e exclusao Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remover a lateral das paginas do Quadro e permitir excluir definitivamente uma atividade pela tela de edicao.

**Architecture:** Uma flag `full_width` no contexto controla a variante de uma coluna em `base.html`, sem afetar as demais paginas. A exclusao usa uma rota POST e um metodo de service que remove a tarefa e compacta a ordem da coluna na mesma transacao.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Jinja2, JavaScript nativo, pytest e HTTPX.

## Global Constraints

- Remover a lateral apenas de `/web/board`, `/web/board/new` e `/web/board/{id}/edit`.
- Manter a lateral das demais paginas.
- Excluir apenas pela tela de edicao, com `window.confirm`.
- Usar `POST /web/board/{id}/delete` e redirect HTTP 303.
- Compactar `ordem` das tarefas posteriores na mesma coluna.
- Nao alterar schema, propostas, clientes ou financeiro.
- Nao criar commit sem autorizacao do usuario.

---

### Task 1: Layout do Quadro em largura total

**Files:**
- Create: `tests/test_board_delete.py`
- Modify: `app/templates_web/base.html:165-182,904-928`
- Modify: `app/routers/board.py:17-112`

**Interfaces:**
- Consumes: `render_template(request, template_name, context)` existente.
- Produces: flag de contexto `full_width: bool` reconhecida por `base.html`.

- [ ] **Step 1: Escrever testes de layout**

Adicionar testes que requisitam as tres paginas do Quadro e confirmam `layout-grid full-width`, ausencia de `aside-stack`, "Criar proposta" e "Padrao de produtividade". Adicionar um controle em `/web/proposals` confirmando que a lateral permanece.

- [ ] **Step 2: Confirmar a falha inicial**

Run: `python3 -m pytest tests/test_board_delete.py -q`

Expected: falhas porque a lateral ainda e renderizada no Quadro.

- [ ] **Step 3: Implementar a variante sem lateral**

Adicionar em `base.html`:

```css
.layout-grid.full-width { grid-template-columns: minmax(0, 1fr); }
```

Usar a flag no HTML:

```jinja2
<div class="layout-grid{% if full_width %} full-width{% endif %}">
...
{% if not full_width %}<aside class="aside-stack">...</aside>{% endif %}
```

Passar `"full_width": True` nos contextos do quadro, criacao e edicao.

- [ ] **Step 4: Confirmar os testes verdes**

Run: `python3 -m pytest tests/test_board_delete.py -q`

Expected: testes de layout aprovados.

---

### Task 2: Exclusao segura e compactacao da coluna

**Files:**
- Modify: `tests/test_board_delete.py`
- Modify: `app/services/board_service.py:25-115`
- Modify: `app/routers/board.py:130-145`
- Modify: `app/templates_web/board_form.html:76-84`

**Interfaces:**
- Produces: `delete_task(db: Session, task_id: int) -> None`.
- Produces: `POST /web/board/{task_id}/delete`.

- [ ] **Step 1: Escrever testes de exclusao**

Adicionar casos que comprovam:

```python
def test_edit_page_shows_confirmed_delete_action(db): ...
def test_delete_task_redirects_removes_and_compacts_order(db): ...
def test_delete_missing_task_returns_404(): ...
```

- [ ] **Step 2: Confirmar a falha inicial**

Run: `python3 -m pytest tests/test_board_delete.py -q`

Expected: falhas por ausencia do botao e da rota de exclusao.

- [ ] **Step 3: Implementar service, rota e formulario**

O service deve localizar a tarefa, guardar status/ordem, excluir, decrementar `Task.ordem` para registros posteriores da mesma coluna e fazer um unico `commit`. A rota chama o service e retorna `RedirectResponse('/web/board', 303)`. O template adiciona, somente quando `task` existe, um formulario separado com:

```html
<form action="/web/board/{{ task.id }}/delete" method="post"
      onsubmit="return window.confirm('Tem certeza que deseja excluir esta atividade? Esta ação não pode ser desfeita.');">
  <button type="submit" class="btn btn-danger">Excluir atividade</button>
</form>
```

- [ ] **Step 4: Executar o teste focado e a suite completa**

Run: `python3 -m pytest tests/test_board_delete.py -q`

Expected: todos os testes do arquivo aprovados.

Run: `python3 -m pytest -q`

Expected: suite completa aprovada.

- [ ] **Step 5: Validar no Docker sem commit**

Run: `docker compose up -d --build`

Run: `docker compose exec -T app pip install -q -r requirements-dev.txt && docker compose exec -T app python -m pytest -q`

Expected: container saudavel e suite completa aprovada. Nao executar `git commit`.
