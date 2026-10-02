# Yahoo Local Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare a Git-ignored credential file and a dedicated launcher for the isolated port 8011 instance.

**Architecture:** Keep Yahoo credentials in `.env.yahoo.local`, which is never tracked. A dedicated shell launcher points Pydantic at that file only in its child process, then supplies the existing isolated database, document, Ollama, voice, and port 8011 settings without printing environment values.

**Tech Stack:** POSIX shell, Pydantic Settings, FastAPI/Uvicorn.

## Global Constraints

- Do not read or alter the existing `.env`.
- Do not restart port 8011 until the user confirms credentials were filled.
- Do not alter port 8000 or operational data.
- Never enable shell tracing or print credentials.

---

### Task 1: Local Yahoo environment and isolated launcher

**Files:**
- Modify: `.gitignore`
- Create locally (ignored): `.env.yahoo.local`
- Create: `scripts/run_assistant_8011_yahoo.sh`

**Interfaces:**
- Consumes: existing `Settings` environment variables and isolated files under `/tmp/ad-balancas-conversational.xFP65K`.
- Produces: a launcher that makes Pydantic load `.env.yahoo.local` only for the 8011 child process.

- [x] **Step 1: Add `.env.yahoo.local` to `.gitignore` and verify Git reports it ignored.**
- [x] **Step 2: Create the ignored file with `EMAIL_PROVIDER=imap_yahoo` and empty credential fields.**
- [x] **Step 3: Add a launcher that validates non-empty credentials without echoing them, exposes only its path to the child process, and starts port 8011 with the isolated database and document directory.**
- [x] **Step 4: Run shell syntax validation and confirm the current listeners on ports 8000 and 8011 were not changed.**
- [x] **Step 5: Do not commit or restart; wait for the user to fill the local file.**
