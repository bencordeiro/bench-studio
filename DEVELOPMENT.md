# Development

## Layout

```
backend/
  app/
    api/            FastAPI routers (health, endpoints, benchmarks, runs, leaderboards)
    core/           config, security/sanitization, secrets (keyring), URLs, token est.
    db/             SQLAlchemy engine + session
    models/         ORM models + enums
    schemas/        Pydantic request/response models
    services/       OpenAI client, connection testing, CRUD, snapshots
    graders/        deterministic, judge protocol, scoring
    jobs/           execution engine, job runner, event bus (SSE)
    exports/        benchmark JSON format, run JSON/CSV/HTML export
    seed/           removable example benchmark + bundled suites/*.json (auto-loaded)
    main.py         app factory + lifespan
  alembic/          migrations
  tests/            pytest suite (no real LLM)
frontend/
  src/
    api/            typed API client
    components/     shared UI + PromptEditor
    pages/          route pages
    types/          TypeScript domain types
    lib/            formatting helpers
    store/          toast context
scripts/           (root) setup/run scripts + docs
```

## Backend dev

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Run (auto-reload):
uvicorn app.main:app --reload --port 8765

# Tests:
pytest
```

Migrations are applied automatically on startup. To create a new migration after changing models:

```bash
cd backend
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

## Frontend dev

```bash
cd frontend
npm install
npm run dev        # Vite dev server on :5173, proxies /api -> :8765
```

Run the backend on :8765 in a separate terminal; open the Vite URL during development. The production build is what FastAPI serves.

```bash
npm run typecheck   # tsc --noEmit
npm run test        # vitest
npm run build       # tsc -b && vite build -> dist/
```

## Adding a grader

1. Add the grading function in `app/graders/deterministic.py` and register it in `GRADER_FUNCS`.
2. Cover it with tests in `tests/test_deterministic.py`.
3. Add a config branch in the prompt editor (`PromptEditor.tsx` → `DeterministicConfig`).
4. Document it in `BENCHMARK_FORMAT.md` and `SCORING.md`.

## Adding a bundled suite

Drop a `*.json` file (localbench-benchmark format, see `BENCHMARK_FORMAT.md`) into
`app/seed/suites/`. It is auto-loaded at startup by `seed_bundled_suites`, keyed by
suite **name** (idempotent — editing/deleting a seeded suite won't resurrect it), and
gated by `LOCALBENCH_NO_SEED=1`. For deterministic suites, never hand-write an expected
answer: execute the code/logic to get ground truth, then assert it scores 100 through
`run_deterministic` (see `tests/test_seed_suites.py`).

## Conventions

- All timestamps are UTC internally.
- All list endpoints that may grow support pagination (run/benchmark lists).
- API paths are consistent: `/api/{resource}` and `/api/{resource}/{id}`; the OpenAPI doc is at `/api/docs`.
- Never log or return secret values; route all error messages through `sanitize()`.
- The architecture leaves room for future grader plugins, but the current implementation is complete without them.
