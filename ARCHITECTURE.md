# Architecture

LocalBench Studio is a single-process local application: one FastAPI backend serves a compiled React SPA **and** runs benchmark jobs. All state lives in SQLite. There is no Docker, Redis, Celery, or separate worker service.

## Component overview

```
┌─────────────────────────────────────────────────────────────┐
│                       Browser (SPA)                          │
│   React + TS + Tailwind + TanStack Query + Recharts          │
│         (control & reporting only — never runs prompts)      │
└───────────────┬─────────────────────────────────────────────┘
                │  HTTP /api/*   +   SSE /api/runs/{id}/progress
┌───────────────▼─────────────────────────────────────────────┐
│                    FastAPI backend process                   │
│  ┌────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │ REST API   │  │  SPA static  │  │  Background asyncio   │ │
│  │ routers    │  │  file mount  │  │  JobRunner (1 job)    │ │
│  └─────┬──────┘  └──────────────┘  └──────────┬────────────┘ │
│        │                                      │              │
│        │           ┌──────────────────────────▼──────────┐   │
│        │           │   Execution engine (engine.py)      │   │
│        │           │   target → deterministic → judge →  │   │
│        │           │   verifier → finalize/summary       │   │
│        │           └──────────┬──────────────────────────┘   │
│        │                      │                              │
│  ┌─────▼──────────────────────▼─────────────────────────┐    │
│  │   SQLAlchemy 2  →  SQLite (WAL)                       │    │
│  │   Alembic migrations  ·  OS keyring (secrets)         │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
                │  HTTPX (streaming + retries)
        ┌───────▼────────┐
        │ OpenAI-        │  (target model)
        │ compatible     │
        │ endpoint       │
        └────────────────┘   + optional judge endpoint (same or different)
```

## Browser-independent execution

The browser is **only a control and reporting interface**. Benchmark execution happens entirely inside the backend process:

1. A run is created as a row in SQLite with status `queued`.
2. A single background asyncio task (`JobRunner`) polls for queued jobs and executes them sequentially.
3. The execution engine (`app/jobs/engine.py`) walks prompts, calls the target endpoint via HTTPX, runs graders, persists results **after every prompt**, and recomputes the summary.
4. Closing, refreshing, or navigating away from the browser does nothing to the job — it cannot, because the job runs in the backend's event loop, not the browser.
5. Live progress is delivered via Server-Sent Events (`/api/runs/{id}/progress`) with a 1-second polling fallback that re-reads SQLite. Reconnecting replays recent history.

**Stopping the backend process** (closing the terminal) interrupts the active run. On the next startup, `mark_interrupted_active_runs()` sets any non-terminal run to `interrupted`; the user can **Resume**, which resets only in-flight executions to `pending` — completed target prompts are never rerun.

The job queue is the SQLite `benchmark_runs` table (status column) plus the backend process. No Redis or separate worker is required.

## Job lifecycle

```
queued → preparing → warming_up (optional) → running_target
  → running_deterministic → running_judge (optional) → running_verifier (optional)
  → completed | completed_with_errors | cancelled | interrupted | failed
```

- **Completed with errors** — some prompts failed but the run finished.
- **Interrupted** — backend stopped mid-run; resumable.
- **Cancelled** — safe cancellation after the current in-flight request finishes.

## Grading pipeline

Per prompt, the engine decides grading by the prompt's `grading_mode`:

| Mode | Target request | Deterministic check | Judge | Verifier | Final score |
|------|---------------|--------------------|-------|----------|-------------|
| `deterministic` | yes | yes (one or more) | no | no | deterministic normalized 0–100 |
| `judge` | yes | no | yes (optional) | optional | judge `final_score` |
| `hybrid` | yes | yes | yes (optional) | optional | weighted merge of det + judge; critical-fail caps |
| `manual` | yes | no | no | no | none — "awaiting manual review" |

Judge output is validated against a strict Pydantic schema. On failure, exactly one repair request is attempted (including the validation error); if that fails the judgment is marked invalid and the prompt becomes "awaiting manual review" — **no score is ever fabricated**. Raw judge output is preserved for inspection.

If judge-required prompts exist but no judge is configured, target responses still run; those prompts are marked `awaiting_judge` and can be judged later without rerunning the target.

## Secret handling

- API keys are stored via Python's `keyring` when an OS backend is available (Windows Credential Manager, GNOME Keyring/KWallet, macOS Keychain). When unavailable, the only options are session keys, environment variables, or explicit plaintext fallback (off by default).
- The frontend only ever receives `has_api_key` + a masked indicator + the profile ID — never the key value.
- The backend injects credentials into outgoing requests; the browser never contacts the LLM endpoint.
- A sanitizing logging filter redacts `Bearer …`, `sk-…`, and any key whose name matches a secret pattern, before anything is written to logs or error storage.
- Run exports pass through the same sanitizer; tests assert that a known API key never appears in JSON/CSV/HTML exports.

## Database

SQLAlchemy 2 declarative models over SQLite (WAL mode, foreign keys on). JSON columns store flexible config (grader configs, rubrics, generation overrides, run summaries). Run snapshots are **immutable** copies of the benchmark, prompts, rubrics, and endpoint settings (minus secrets) taken at run creation, so editing or deleting a benchmark/endpoint never mutates historical runs. Alembic provides batch-mode migrations friendly to SQLite ALTER.

## Frontend

Vite + React 18 + TypeScript (strict). Tailwind for styling, Recharts for analytics, TanStack Query for server state, React Router for navigation, React Hook Form + Zod for validation. The production build (`frontend/dist/`) is served by FastAPI so the user runs one process and opens one URL. In development, Vite runs separately and proxies `/api` to the backend.

## Retry and error handling

Transient errors (connection reset, timeouts, HTTP 408/425/429/500/502/503/504) are retried with bounded exponential backoff. Permanent errors (e.g. 400) are not retried. A failed prompt is recorded with a sanitized error and **does not destroy the run** — the run continues and completes as "completed with errors".
