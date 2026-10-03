# AD Balanças Redesign — Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the approved design to Tarefas, Serviços, E-mails e mensagens, and Assistente while preserving every operational workflow.

**Architecture:** Reuse the shell and components from plan 01. Keep status changes on existing endpoints, add client-side filtering only for already-rendered records, and isolate testable Kanban behavior in a vanilla JavaScript module.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Jinja2, vanilla JavaScript/CSS, pytest, Node test runner.

## Global Constraints

- Complete plan 01 first.
- Preserve current task free-text client fields and assistant/e-mail changes already in the working tree.
- Do not modify service append-only history or assistant confirmation contracts.
- Yahoo remains read-only; do not mark, send, move, or delete messages.
- Do not add model columns or heavy dependencies.
- Do not commit, push, merge, or deploy.

## File map

- `app/static/kanban_ui.js` — drag, accessible status move, filtering, and rollback.
- `app/templates_web/_kanban_drag.html` — module bootstrap only.
- `app/templates_web/board.html`, `board_form.html` — task UI.
- `app/routers/services.py`, `services.html`, `service_detail.html` — services presentation.
- `app/routers/pages.py`, `messages.html` — inbox summaries and filters.
- `app/templates_web/assistant.html`, `app/static/assistant_chat.js`, `assistant_voice_bootstrap.js` — conversation presentation only.
- `tests/test_board_statuses.py`, `test_service_routes.py`, `test_today_routes.py`, `tests/js/kanban_ui.test.mjs`, `assistant_chat.test.mjs`, `assistant_voice.test.mjs` — contracts.

---

### Task 1: Make Kanban movement reusable and accessible

**Files:**
- Create: `app/static/kanban_ui.js`
- Modify: `app/templates_web/_kanban_drag.html`
- Create: `tests/js/kanban_ui.test.mjs`

**Interfaces:**
- Consumes: board element attributes `data-endpoint-template`, `data-ordered`, cards with `data-id`, and columns with `data-status`.
- Produces: `postMove({id, payload, endpointTemplate, fetchImpl})`, `filterCards(cards, filters)`, and `bootstrapKanban(root)` exports.

- [ ] **Step 1: Write failing JavaScript tests**

Cover endpoint substitution, JSON payload, rollback on non-OK response, status filter, text search, and cards with free-text clients:

```javascript
test("postMove sends the caller's exact payload to the existing endpoint", async () => {
  const calls = [];
  await postMove({ id: 12, payload: { status: "em_andamento", ordem: 2 },
    endpointTemplate: "/api/tasks/{id}/move",
    fetchImpl: async (url, options) => { calls.push([url, JSON.parse(options.body)]); return { ok: true }; } });
  assert.deepEqual(calls, [["/api/tasks/12/move", { status: "em_andamento", ordem: 2 }]]);
});
```

- [ ] **Step 2: Run and confirm failure**

Run `node --test tests/js/kanban_ui.test.mjs`.

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Extract the existing behavior**

Move the logic from `_kanban_drag.html` into ES module exports. On failure, restore the card to its captured parent and index, update column counts, and set the existing `[data-kanban-error]` region. Status menu and drag must call the same `postMove` function with `{status, ordem}`.

- [ ] **Step 4: Bootstrap from the partial**

Replace the partial body with:

```html
<script type="module">
  import { bootstrapKanban } from "/assets/kanban_ui.js";
  document.querySelectorAll("[data-kanban-board]").forEach(bootstrapKanban);
</script>
```

- [ ] **Step 5: Run JavaScript tests**

Run `node --test tests/js/kanban_ui.test.mjs tests/js/assistant_chat.test.mjs tests/js/assistant_voice.test.mjs`.

Expected: PASS.

### Task 2: Redesign Tarefas without losing current client work

**Files:**
- Modify: `app/templates_web/board.html`
- Modify: `app/templates_web/board_form.html`
- Modify: `app/routers/board.py`
- Modify: `tests/test_board_statuses.py`
- Modify: `tests/test_board_assistant_validation.py`

**Interfaces:**
- Consumes: five current statuses, `Task.client`, `Task.client_name`, `Task.client_link_status`, `Task.user`, `Task.proposal`, and `/api/tasks/{id}/move`.
- Produces: filter controls with `data-filter-*` and an accessible per-card move menu.

- [ ] **Step 1: Add failing route assertions**

Assert the rendered board includes total task count, search, status/responsible/client/deadline filters, `Cliente a identificar`, e-mail origin marker when linked, and one `Mover tarefa` control per card.

- [ ] **Step 2: Run focused Python tests**

Run `pytest tests/test_board_statuses.py tests/test_board_assistant_validation.py tests/test_board_delete.py -q`.

Expected: new presentation assertions FAIL; existing persistence assertions PASS.

- [ ] **Step 3: Implement the board toolbar and card data**

Use only current fields:

```html
<input type="search" data-filter-search aria-label="Buscar tarefas">
<select data-filter-status aria-label="Filtrar por status">…cinco estados…</select>
<select data-filter-owner aria-label="Filtrar por responsável">…usuários presentes…</select>
<select data-filter-client aria-label="Filtrar por cliente">…clientes e “a identificar”…</select>
<select data-filter-deadline aria-label="Filtrar por prazo">todos · atrasadas · hoje · sem prazo</select>
```

Set normalized searchable values in `data-*` attributes. Render `task.client.razao_social`, else `task.client_name`, else `Cliente a identificar`. Keep `A confirmar` and `Revisar vínculo` from the user’s current changes. Pass a timezone-aware `today` date from `board_page` for deadline labels; do not compare against the browser clock.

- [ ] **Step 4: Add semantic deadline labels and move menu**

Derive visual labels in Jinja from `today`: `Atrasada`, `Hoje`, date, or `Sem prazo`. Each card gets a labeled `<select>` or menu containing the other real statuses and calling `moveCard`; drag remains available.

- [ ] **Step 5: Restyle the task form**

Preserve names and submission routes exactly. Keep both `client_id` and `client_name`, with copy that free text does not create a client. Remove inline layout styles in favor of shared classes.

- [ ] **Step 6: Run board tests**

Run `pytest tests/test_board_statuses.py tests/test_board_assistant_validation.py tests/test_board_delete.py -q && node --test tests/js/kanban_ui.test.mjs`.

Expected: PASS.

### Task 3: Recompose service list and detail

**Files:**
- Modify: `app/routers/services.py`
- Modify: `app/templates_web/services.html`
- Modify: `app/templates_web/service_detail.html`
- Modify: `tests/test_service_routes.py`
- Modify: `tests/test_service_history_immutability.py`

**Interfaces:**
- Consumes: `service_record_service.list_calls`, `get_call_detail`, current labels, immutable events, transitions, and task links.
- Produces: optional `service_rows` presentation dictionaries containing only existing values.

- [ ] **Step 1: Add failing presentation tests**

Require list headings `Cliente`, `Execução`, `Administrativo`, `Próxima etapa`, `Último evento`; require detail landmarks `data-service-summary`, `data-service-next-step`, and `data-service-timeline`.

- [ ] **Step 2: Run focused tests**

Run `pytest tests/test_service_routes.py tests/test_service_history_immutability.py -q`.

Expected: new landmark assertions FAIL; immutability tests PASS.

- [ ] **Step 3: Build read-only presentation rows**

In the router, derive the last event and first pending workflow step without modifying records. Do not invent a responsible person because service records do not persist one.

- [ ] **Step 4: Implement the list and detail hierarchy**

Use a responsive table/list for service rows. On detail, place summary and next pending step first, followed by separate execution and administration sections, then the chronological timeline, transition history, and reminders. Keep original events and corrections visible and label the effective correction.

- [ ] **Step 5: Run tests**

Run `pytest tests/test_service_routes.py tests/test_service_record_service.py tests/test_service_history_immutability.py -q`.

Expected: PASS.

### Task 4: Turn E-mails e mensagens into a work queue

**Files:**
- Modify: `app/routers/pages.py:204-297`
- Modify: `app/templates_web/messages.html`
- Modify: `tests/test_today_routes.py`
- Modify: `tests/test_assistant_email_sync.py`

**Interfaces:**
- Consumes: the existing 100-message bounded projection, real sync state, `message.task_id`, categories, priorities, and review states.
- Produces: `message_summary` counts and local filter data attributes; no provider mutation.

- [ ] **Step 1: Add failing inbox assertions**

Require three counts, four filter controls, expandable classification evidence, and links only for actual `task_id`. Retain assertions that `Enviar`, `Excluir`, and provider flag mutations are absent.

- [ ] **Step 2: Derive summary counts in the router**

Pass:

```python
message_summary = {
    "new": sum(not message.seen for message in messages),
    "priority": sum(message.priority in {"high", "urgent"} for message in messages),
    "review": sum(message.review_status == "pending" for message in messages),
}
```

- [ ] **Step 3: Implement filters and compact rows**

Add period, category, priority, review-state, and text controls that hide already-rendered rows only. Use `<details>` for summary, classification evidence, and the existing local review form. Show the real sync state in a quiet status panel; errors must remain distinct from empty inbox.

- [ ] **Step 4: Run inbox and sync tests**

Run `pytest tests/test_today_routes.py tests/test_assistant_email.py tests/test_assistant_email_sync.py tests/test_assistant_email_service.py -q`.

Expected: PASS.

### Task 5: Refine Assistente presentation only

**Files:**
- Modify: `app/templates_web/assistant.html`
- Modify: `app/static/assistant_chat.js`
- Modify only for labels/states: `app/static/assistant_voice_bootstrap.js`
- Modify: `tests/js/assistant_chat.test.mjs`
- Modify: `tests/js/assistant_voice.test.mjs`
- Modify: `tests/test_assistant_routes.py`

**Interfaces:**
- Consumes: existing assistant response kinds, confirmation controls, e-mail items, task/service links, and voice states.
- Produces: semantic classes and structured rendering; API payloads remain unchanged.

- [ ] **Step 1: Add failing semantic rendering tests**

Assert message elements receive `data-message-role`, confirmation/cancellation receive `data-response-kind`, and structured result cards keep real links only. Add voice assertions for listening, transcribing, reviewing, processing, speaking, and error labels.

- [ ] **Step 2: Run current assistant tests**

Run `node --test tests/js/assistant_chat.test.mjs tests/js/assistant_voice.test.mjs && pytest tests/test_assistant_routes.py tests/test_assistant_voice_routes.py -q`.

Expected: only new semantic assertions FAIL.

- [ ] **Step 3: Recompose the template**

Use a centered readable column, quiet user/assistant distinction, sticky composer inside the content area, explicit voice state region, and separate confirmation/cancel controls. Do not add unsupported actions.

- [ ] **Step 4: Attach semantic data in render functions**

Set `data-message-role` and `data-response-kind` while retaining all existing text, fetch, retry, idempotency, confirmation, cancel, and link behavior.

- [ ] **Step 5: Run all assistant UI tests**

Run `node --test tests/js/assistant_chat.test.mjs tests/js/assistant_voice.test.mjs && pytest tests/test_assistant_routes.py tests/test_assistant_voice_routes.py -q`.

Expected: PASS.

### Task 6: Verify operational pages

**Files:**
- Modify only when defects are found: files listed above.

- [ ] **Step 1: Run automated verification**

```bash
pytest -q
node --test tests/js/*.test.mjs
git diff --check
```

Expected: PASS with no whitespace errors.

- [ ] **Step 2: Inspect synthetic desktop and mobile states**

At 1440 and 390 pixels inspect `/web/board`, one task form, `/web/services`, one service detail, `/web/mensagens`, and `/web/assistente`. Test search, every filter, drag, keyboard move, rollback error, drawer, forms, details expansion, confirmation/cancel, and voice state labels.

- [ ] **Step 3: Report without committing**

Record pages, checks, and limitations. Do not alter unrelated working-tree changes.
