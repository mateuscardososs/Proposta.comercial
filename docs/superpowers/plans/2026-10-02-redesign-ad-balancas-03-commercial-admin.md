# AD Balanças Redesign — Commercial, Documents, Finance, and Administration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the approved redesign across proposals, imports, clients, finance, and users without changing their business workflows.

**Architecture:** Reuse plans 01–02 components. Treat proposal generation and imports as protected workflows: change markup and presentation around existing field names, form actions, and JavaScript hooks, and verify them with route and service regressions.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Jinja2, vanilla CSS/JavaScript, docxtpl/LibreOffice integration, pytest, Node test runner.

## Global Constraints

- Complete plans 01 and 02 first.
- Do not change proposal calculations, numbering, cloning, revision, DOCX/PDF generation, Word upload, or legacy PDF import behavior.
- Do not mark payments, issue invoices, or create client links outside existing authorized flows.
- Do not add model columns, statuses, or heavy dependencies.
- Keep the server bound to `127.0.0.1`; use synthetic data for review.
- Do not commit, push, merge, or deploy.

## File map

- `proposals.html`, `proposal_detail.html`, `proposal_form.html` — commercial UI.
- `import_proposals.html`, `proposal_external_upload.html`, `proposal_word_reupload.html` — document flows.
- `clients.html`, `client_form.html`, `app/routers/pages.py` — clients.
- `lancamentos_board.html`, `lancamento_form.html`, `app/routers/financeiro.py` — finance.
- `users.html`, `user_form.html` — administration.
- Existing proposal, import, finance, and route tests — protected behavior.

---

### Task 1: Redesign proposal list and detail

**Files:**
- Modify: `app/templates_web/proposals.html`
- Modify: `app/templates_web/proposal_detail.html`
- Modify: `tests/test_proposal_origin.py`
- Modify: `tests/test_proposal_file_routes.py`

**Interfaces:**
- Consumes: existing Proposal relationships, `origem`, document URLs, duplicate and revision routes.
- Produces: local search/filter attributes and reorganized detail sections.

- [ ] **Step 1: Add failing list/detail contracts**

Require search, client/date/origin filters, responsive table headings, document region, commercial summary, item table, schedule, and finance region. Assert duplicate/revision forms and DOCX/PDF links retain exact routes.

- [ ] **Step 2: Run proposal route tests**

Run `pytest tests/test_proposal_origin.py tests/test_proposal_file_routes.py -q`.

Expected: new presentation assertions FAIL; existing workflow tests PASS.

- [ ] **Step 3: Implement the proposal list**

Use current data only: number/revision, client, user, generation date, origin, and total. Filters operate on rendered `data-*` values. Do not invent draft/sent/concluded status because Proposal has no such field.

- [ ] **Step 4: Implement the proposal detail hierarchy**

Order: header and real actions; commercial/client summary; documents; items; schedule; financial summary. Keep all existing forms, methods, names, and URLs unchanged.

- [ ] **Step 5: Run tests**

Run `pytest tests/test_proposal_origin.py tests/test_proposal_file_routes.py tests/test_proposal_file_service.py -q`.

Expected: PASS.

### Task 2: Restyle the protected proposal form

**Files:**
- Modify: `app/templates_web/proposal_form.html`
- Modify: `tests/test_dashboard_routes.py`
- Test without changing: proposal service and document tests.

**Interfaces:**
- Consumes: every existing input `name`, DOM id, keyboard shortcut, calculation function, load-last action, and submit route.
- Produces: the same payload and generated documents.

- [ ] **Step 1: Capture protected DOM hooks**

Before editing, list and preserve IDs referenced by the inline script with:

```bash
rg -o 'getElementById\("[^"]+"|querySelector\("[^"]+' app/templates_web/proposal_form.html
```

- [ ] **Step 2: Add a route regression test**

Assert the form still contains `client_id`, `user_id`, dynamic item/schedule names, `create_kanban_card`, `mode`, `base_proposal_id`, and the real submit route.

- [ ] **Step 3: Recompose visual sections only**

Keep five sections: context, services/pricing, schedule, travel/fiscal conditions, final review. Use shared section headers, responsive editable tables, sticky desktop summary, and stacked mobile actions. Do not change calculation JavaScript.

- [ ] **Step 4: Run protected regressions**

```bash
pytest tests/test_document_total_marker.py tests/test_pdf_no_text.py tests/test_proposal_origin.py tests/test_proposal_file_service.py tests/test_proposal_file_routes.py -q
```

Expected: PASS.

### Task 3: Redesign all import and Word flows

**Files:**
- Modify: `app/templates_web/import_proposals.html`
- Modify: `app/templates_web/proposal_external_upload.html`
- Modify: `app/templates_web/proposal_word_reupload.html`
- Modify: `tests/test_proposal_file_routes.py`
- Test without changing: import and document services.

**Interfaces:**
- Consumes: existing file input IDs, preview endpoints, confirmation flags, accepted extensions, warning/status regions, and submit routes.
- Produces: explicit `idle`, `selected`, `analyzing`, `ready`, `submitting`, `success`, and `error` presentation states.

- [ ] **Step 1: Add failing upload-state assertions**

Require accepted-format copy, live status region, preview region, disabled confirmation before analysis, and no unsupported format controls.

- [ ] **Step 2: Preserve hook inventory**

Run:

```bash
rg -n 'getElementById|addEventListener|fetch\(' app/templates_web/import_proposals.html app/templates_web/proposal_external_upload.html app/templates_web/proposal_word_reupload.html
```

- [ ] **Step 3: Apply shared upload layout**

Use one visual pattern for dropzone, file metadata, progress/status, preview, warnings, and confirmation while retaining each flow’s current endpoints and rules. Never enable confirmation until current analysis succeeds.

- [ ] **Step 4: Run import/document tests**

```bash
pytest tests/test_proposal_file_routes.py tests/test_proposal_file_service.py tests/test_document_total_marker.py tests/test_pdf_no_text.py -q
```

Expected: PASS.

### Task 4: Redesign clients without automatic linking

**Files:**
- Modify: `app/routers/pages.py:300-377`
- Modify: `app/templates_web/clients.html`
- Modify: `app/templates_web/client_form.html`
- Modify: `tests/test_board_assistant_validation.py`
- Modify or create: `tests/test_client_routes.py`

**Interfaces:**
- Consumes: current Client fields, proposals relationship, and confirmed ServiceCall `client_id` links.
- Produces: optional read-only proposal/service counts and confirmed associated service rows.

- [ ] **Step 1: Write failing client page tests**

Create synthetic client, proposal, service, and an unlinked task with `client_name`. Assert list counts only confirmed relationships and the unlinked task does not create or associate a client.

- [ ] **Step 2: Run and confirm failure**

Run `pytest tests/test_client_routes.py tests/test_board_assistant_validation.py -q`.

- [ ] **Step 3: Query confirmed relationships only**

Use SQLAlchemy counts by `Proposal.client_id` and `ServiceCall.client_id`. Never match `Task.client_name` to `Client.razao_social`.

- [ ] **Step 4: Implement list and detail**

List shows search, main registration data, and available confirmed counts. Detail keeps the editable registration form, then associated proposals and services in separate sections.

- [ ] **Step 5: Run tests**

Run `pytest tests/test_client_routes.py tests/test_board_assistant_validation.py -q`.

Expected: PASS.

### Task 5: Replace finance Kanban presentation with accessible tables

**Files:**
- Modify: `app/routers/financeiro.py`
- Modify: `app/templates_web/lancamentos_board.html`
- Modify: `app/templates_web/lancamento_form.html`
- Reuse: `app/static/kanban_ui.js`
- Modify: `tests/test_financeiro_routes.py`
- Test without changing: `tests/test_lancamento_service.py`, `test_lancamento_model.py`

**Interfaces:**
- Consumes: current two statuses, create/edit routes, and `POST /api/lancamentos/{id}/move` with `LancamentoMove`.
- Produces: responsive table rows and explicit accessible status control using the same endpoint.

- [ ] **Step 1: Add failing finance table assertions**

Require headings `Descrição`, `Cliente/fornecedor`, `Valor`, `Vencimento`, `Situação`, textual `Atrasado`/`Vence em breve`, totals from real entries, and a labeled status control.

- [ ] **Step 2: Run finance tests**

Run `pytest tests/test_financeiro_routes.py tests/test_lancamento_service.py tests/test_lancamento_model.py -q`.

Expected: presentation assertions FAIL; service/model tests PASS.

- [ ] **Step 3: Derive view state without mutations**

Pass today and real totals by status/type from the existing query. Derive overdue and near-due text from `data_vencimento`; do not mark anything paid.

- [ ] **Step 4: Implement the table and status control**

Use `postMove` from `kanban_ui.js` with the finance payload `{status}` and the existing move endpoint. On failure restore the previous selection and show `[role="alert"]`. Keep edit links and new-entry routes unchanged. Restyle the form without changing field names or payment-date logic.

- [ ] **Step 5: Run finance tests**

Run `pytest tests/test_financeiro_routes.py tests/test_lancamento_service.py tests/test_lancamento_model.py -q && node --test tests/js/kanban_ui.test.mjs`.

Expected: PASS.

### Task 6: Finish Users and run end-to-end regression

**Files:**
- Modify: `app/templates_web/users.html`
- Modify: `app/templates_web/user_form.html`
- Modify or create: `tests/test_user_routes.py`

**Interfaces:**
- Consumes: existing list/new routes and fields.
- Produces: shared table/form presentation; no authentication claim.

- [ ] **Step 1: Add user page assertions**

Require search, name, role, e-mail, active state, and the existing new-user action. Ensure copy says internal records, not authenticated accounts.

- [ ] **Step 2: Apply shared list and form patterns**

Preserve `nome`, `cargo`, `email`, `senha`, and `ativo`; keep password toggle behavior and current POST route.

- [ ] **Step 3: Run complete automation**

```bash
pytest -q
node --test tests/js/*.test.mjs
git diff --check
```

Expected: all tests PASS; no whitespace errors.

- [ ] **Step 4: Perform final visual inspection**

At 1440 and 390 pixels inspect proposals list/detail/form, three import flows, clients list/detail, both finance pages/forms, and users list/form. Test every search/filter, upload state, form action, status control, drawer, empty state, and long-content wrapping.

- [ ] **Step 5: Verify protected workflows**

With synthetic records, create a proposal, clone/duplicate it, begin a revision, generate/download DOCX/PDF where the local dependency exists, preview imports without committing, and confirm finance changes occur only through the current explicit flow.

- [ ] **Step 6: Deliver the final report without committing**

Report redesigned pages, visual decisions, preserved workflows, automated tests, inspected widths, remaining environment limitations, and the safe command `APP_HOST=127.0.0.1 APP_PORT=8000 python run.py`.
