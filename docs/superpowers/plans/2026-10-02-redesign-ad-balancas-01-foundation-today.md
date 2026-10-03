# AD Balanças Redesign — Foundation and Today Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the approved light application shell and redesign the Hoje page without changing business behavior.

**Architecture:** Keep FastAPI and Jinja2 server rendering as the source of page structure. Centralize shared visual tokens and shell behavior in `base.html`, keep operational data in the existing services, and pass view-only Today groupings from the page router.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Jinja2, vanilla CSS/JavaScript, pytest 8.4, Node test runner.

## Global Constraints

- Preserve all current routes, data, permissions, and business rules.
- Bind review instances only to `127.0.0.1`.
- Do not add authentication, WhatsApp, Alembic, or heavy dependencies.
- Do not alter proposal creation, cloning, duplication, revision, or DOCX/PDF generation behavior.
- Use only synthetic data for tests and screenshots.
- Preserve all pre-existing working-tree changes, especially the task free-text client and e-mail activation work.
- Do not commit, push, merge, or deploy.

## File map

- `app/templates_web/base.html` — tokens, shell, grouped navigation, breadcrumbs, shared components, responsive rules.
- `app/routers/pages.py` — Today view-only grouping and existing page contexts.
- `app/templates_web/index.html` — approved Hoje composition.
- `tests/test_today_routes.py` — shell, navigation, safety copy, and Today contracts.
- `tests/test_dashboard_routes.py` — dashboard data remains visible after the composition changes.
- `tests/test_today_service.py` — priority and read-only behavior remain unchanged.

---

### Task 1: Lock the shell and Today contracts

**Files:**
- Modify: `tests/test_today_routes.py`
- Modify: `tests/test_dashboard_routes.py`

**Interfaces:**
- Consumes: existing `GET /`, `GET /web/mensagens`, and template output.
- Produces: regression contracts for the shell and the new Today regions.

- [ ] **Step 1: Add failing shell assertions**

Extend `test_today_is_home_and_shell_has_keyboard_navigation` with exact structural contracts:

```python
assert 'data-app-shell' in response.text
assert 'data-sidebar' in response.text
assert 'data-sidebar-toggle' in response.text
assert 'data-nav-group="operacao"' in response.text
assert 'data-nav-group="comunicacao"' in response.text
assert response.text.index('aria-label="E-mails e mensagens"') < response.text.index('aria-label="Assistente"')
assert 'localStorage.getItem("adbalancas-nav-collapsed")' in response.text
```

- [ ] **Step 2: Add failing Today composition assertions**

Replace count-by-class assertions in `test_index_renders_dashboard_contract_and_danger_states` with semantic region assertions:

```python
assert 'aria-label="Resumo operacional do dia"' in response.text
assert 'data-today-section="attention"' in response.text
assert 'data-today-section="agenda"' in response.text
assert 'data-today-section="services"' in response.text
assert 'data-today-section="finance"' in response.text
assert "Tarefa atrasada" in response.text
assert "R$ 100,00" in response.text
assert "R$ 250,00" in response.text
```

Update the empty-state test to require `Nenhuma pendência encontrada nesta janela` and retain all five monthly zero-value totals.

- [ ] **Step 3: Run the focused tests and confirm failure**

Run:

```bash
pytest tests/test_today_routes.py tests/test_dashboard_routes.py tests/test_today_service.py -q
```

Expected: failures for missing `data-app-shell`, grouped navigation, and Today section markers; the service tests remain green.

- [ ] **Step 4: Record the pre-edit state without changing it**

Run:

```bash
git status --short
git diff -- app/templates_web/base.html app/templates_web/index.html app/routers/pages.py
```

Expected: any user changes are visible and preserved; no reset or checkout command is used.

### Task 2: Implement the approved application shell

**Files:**
- Modify: `app/templates_web/base.html`
- Test: `tests/test_today_routes.py`

**Interfaces:**
- Consumes: `request.url.path`, `title`, `full_width`, `content`, `side_actions`, and `scripts` template values.
- Produces: the same Jinja blocks plus `data-app-shell`, `data-sidebar`, and grouped navigation landmarks used by all pages.

- [ ] **Step 1: Replace the root tokens with the approved system**

Use these exact primitives as the base, then map existing component selectors to them:

```css
:root {
  --canvas: #f3f4f5;
  --surface: #ffffff;
  --surface-subtle: #f7f8f9;
  --surface-active: #edf1f4;
  --line: #e1e5e8;
  --line-strong: #cbd2d8;
  --ink: #18232d;
  --ink-muted: #66727d;
  --ink-faint: #87919a;
  --instrument-blue: #183f62;
  --instrument-blue-hover: #102f4a;
  --instrument-blue-soft: #e8f0f6;
  --verified: #277355;
  --verified-soft: #e9f5ef;
  --attention: #986515;
  --attention-soft: #fff2d9;
  --critical: #b83c3c;
  --critical-soft: #fdeaea;
  --focus-ring: #2b76ae;
  --radius-control: 8px;
  --radius-card: 10px;
  --radius-shell: 14px;
  --shadow-lift: 0 0 0 1px rgba(21, 31, 40, .04), 0 2px 5px rgba(21, 31, 40, .04);
}
```

Remove radial backgrounds, gradients, pill navigation, heavy active shadows, and `transition: all`. Retain `prefers-reduced-motion`.

- [ ] **Step 2: Build the grouped sidebar markup**

Keep every current destination and use this group order:

```html
<aside class="sidebar" id="siteNav" data-sidebar aria-label="Navegação principal">
  <div class="sidebar-brand">AD Balanças <span>Engenharia</span></div>
  <nav>
    <section data-nav-group="operacao">Hoje · Tarefas · Serviços</section>
    <section data-nav-group="comunicacao">E-mails e mensagens · Assistente</section>
    <section data-nav-group="comercial">Propostas · Clientes</section>
    <section data-nav-group="financeiro">Contas a receber · Contas a pagar</section>
    <section data-nav-group="administracao">Importar documentos · Usuários</section>
  </nav>
</aside>
```

Implement each textual item as the existing real `<a>` route with inline SVG, `aria-label`, `title`, and conditional `aria-current="page"`. Do not use emoji or invent routes.

- [ ] **Step 3: Recompose the shell and header**

Add `data-app-shell` to the outer grid, retain `#mainContent`, and keep the existing Jinja blocks. The desktop sidebar is 238px expanded and 72px collapsed; content has a maximum readable width without constraining Kanban pages. Breadcrumbs remain absent on `/` and appear before the page content elsewhere.

- [ ] **Step 4: Preserve and refine sidebar behavior**

Keep the current storage key exactly:

```javascript
const collapsed = localStorage.getItem("adbalancas-nav-collapsed") === "true";
localStorage.setItem("adbalancas-nav-collapsed", String(collapsed));
```

Desktop toggles collapsed state. At `max-width: 1024px`, the same button opens a modal drawer, focuses the first link, traps `Tab`, closes on overlay or `Escape`, and restores focus to the trigger. Add `data-sidebar-toggle` to the button and retain its changing accessible label.

- [ ] **Step 5: Standardize shared components**

Update existing `.page-header`, `.card`, `.btn`, `.badge`, `.table-wrap`, form controls, alerts, empty states, and focus selectors to use the new tokens. Use moderate radii, no decorative gradients, and shadows only on the outer shell or lifted overlays.

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest tests/test_today_routes.py -q
```

Expected: PASS.

### Task 3: Recompose Hoje around real operational sections

**Files:**
- Modify: `app/routers/pages.py:187-201`
- Modify: `app/templates_web/index.html`
- Test: `tests/test_dashboard_routes.py`
- Test: `tests/test_today_service.py`

**Interfaces:**
- Consumes: `TodayAgenda.items`, `TodayAgenda.summary`, and `DashboardSummary` unchanged.
- Produces: `today_sections: dict[str, list[TodayItem]]` in the template context.

- [ ] **Step 1: Add view-only grouping in the home route**

After obtaining `agenda`, derive these lists without database writes:

```python
today_sections = {
    "attention": [item for item in agenda.items if item.rank <= 1][:6],
    "agenda": [item for item in agenda.items if item.source_type == "task"],
    "services": [item for item in agenda.items if item.source_type == "service"],
    "finance": [item for item in agenda.items if item.source_type == "finance"],
}
```

Pass `today_sections` beside `summary` and `agenda`. Do not change `get_today_agenda` ordering or persistence behavior.

- [ ] **Step 2: Implement the approved Today hierarchy**

Create this semantic order in `index.html`:

```html
<section class="page-heading">saudação, data, resumo e ação real “Nova tarefa”</section>
<section class="summary-grid" aria-label="Resumo operacional do dia">quatro KPIs</section>
<section data-today-section="attention">itens rank 0–1</section>
<section data-today-section="agenda">tarefas abertas ordenadas</section>
<section data-today-section="services">serviços e próxima etapa</section>
<section data-today-section="finance">contas e datas existentes</section>
<details>indicadores mensais existentes</details>
```

The four primary KPIs are overdue, due today, ongoing services, and e-mail review. Render `item.reason` beside every prioritized item. Show dates only when `item.due_date` is not `None`.

- [ ] **Step 3: Implement empty and secondary states**

The empty attention copy is exactly `Nenhuma pendência encontrada nesta janela`. Keep links only to `/web/board`, `/web/services`, `/web/mensagens`, and the two real finance routes. Monthly proposal and finance metrics stay inside the secondary `<details>`.

- [ ] **Step 4: Run all Today and dashboard tests**

Run:

```bash
pytest tests/test_today_service.py tests/test_today_routes.py tests/test_dashboard_service.py tests/test_dashboard_routes.py -q
```

Expected: PASS.

### Task 4: Verify the foundation visually and mechanically

**Files:**
- Review: `app/templates_web/base.html`
- Review: `app/templates_web/index.html`

**Interfaces:**
- Consumes: completed shell and Today page.
- Produces: a stable visual foundation for plans 02 and 03.

- [ ] **Step 1: Run the full automated baseline**

Run:

```bash
pytest -q
node --test tests/js/*.test.mjs
git diff --check
```

Expected: all tests PASS and `git diff --check` prints nothing.

- [ ] **Step 2: Start the safe local review instance**

Run:

```bash
APP_HOST=127.0.0.1 APP_PORT=8000 python run.py
```

Expected: application available only at `http://127.0.0.1:8000/`.

- [ ] **Step 3: Inspect four widths with synthetic data**

Inspect `/` at 1440, 1024, 768, and 390 pixels. Verify expanded/collapsed sidebar, mobile drawer, focus order, no horizontal page scroll, readable KPIs, visible attention items, and the monthly section.

- [ ] **Step 4: Stop and report without committing**

Record test output, inspected widths, defects fixed, and remaining limitations. Do not commit or modify unrelated dirty files.
