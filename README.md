# LocalBench Studio

LocalBench Studio is a **desktop-hosted web application for benchmarking one LLM at a time** through an OpenAI-compatible API endpoint. It runs locally on Windows or Ubuntu, stores all data locally, executes benchmark jobs independently of the browser connection, automatically grades responses, and presents detailed analytics.

> **What it is not:** not a cloud service, not a multi-user system, not a distributed benchmarking farm, and not a universal "intelligence score." It is a serious local engineering tool for measuring one model's quality, reliability, and latency against rubrics you define.

## What it does

- Save one or more OpenAI-compatible endpoint profiles (with optional API keys stored in the OS credential store).
- Start from four bundled, execution-verified suites (135 original prompts), or author your own.
- Grade each prompt one of four ways: **deterministic**, **LLM judge**, **hybrid**, or **manual review**. Deterministic graders cover exact/numeric/regex/concept/JSON/multiple-choice/count and parsed **tool calls**.
- Run a benchmark against one target model; close/refresh the browser without stopping the run.
- Reopen later and see live progress, resume interrupted runs.
- View detailed analytics: quality, reliability, performance, per-prompt scores, latency distributions.
- Compare completed runs. Per-suite leaderboards ranking every tested model. Export JSON / CSV / standalone HTML reports.
- Keep a separate judge endpoint so the model under test is not grading itself (with a clear warning when it is).

## Bundled benchmark suites

Four suites ship with the app and load on first run (135 prompts). They are **original items, never published anywhere**, so they cannot be present in any model's training data — the usual problem with scoring local models against public leaderboards.

| Suite | Prompts | What it measures |
|---|---|---|
| Code Reasoning (Python) | 59 | Output prediction over closures, mutation/aliasing, the data model, generator lifecycle, evaluation order |
| Web Dev Correctness (JS) | 50 | Coercion, the event loop and microtask ordering, prototypes, async semantics, JSON edge cases |
| Agentic Tool-Use (Hermes) | 14 | Function calling in BFCL categories: simple, tool selection, parallel, argument precision, relevance |
| Instruction-Following | 12 | IFEval-style stacked constraints: exact counts, forbidden vocabulary, strict JSON, custom markup |

Design rules every item follows:

- **Answers are produced by execution, never written by hand.** Each code prompt's expected output comes from actually running the snippet under CPython 3 / Node.
- **Graded deterministically.** No judge is required for any bundled suite, so results are reproducible.
- **No item pays out for a non-answer.** Prohibitions ("do not use the letter 'e'") are trivially satisfied by silence, so every such item is gated on a separate check proving the task was attempted.
- **Difficulty comes from depth, not obscurity.** Items chain several inferences rather than testing trivia, and answers are kept short so the score measures reasoning rather than transcription.

`backend/tests/test_suite_quality.py` enforces these as executable invariants, so a new or edited item cannot quietly break them.

### Calibrating difficulty to your own models

A benchmark only informs you over the range where models actually differ. If most items pass, everything scores in the high 80s and the ranking is noise. `scripts/calibrate_suite.py` measures which items separate two models and re-weights accordingly:

```bash
python scripts/calibrate_suite.py measure --base-url http://localhost:8000/v1 \
    --model small-model --api-key KEY --out calib-small.json
python scripts/calibrate_suite.py measure --base-url http://localhost:8000/v1 \
    --model large-model --api-key KEY --out calib-large.json
python scripts/calibrate_suite.py compare calib-small.json calib-large.json --apply
```

It sorts every item into **separating** (carries the ranking), **ceiling** (everything passes — no information) and **floor** (nothing passes — possibly too hard or broken), then weights them so the score is driven by the items that discriminate. See [SCORING.md](SCORING.md).

## Screenshots

> The UI is a professional dark interface. Capture screenshots of: the Dashboard, the Benchmark Editor with the Prompt Editor open, an Active Run with a live progress bar, and the Results page charts. Drop them under `docs/screenshots/`.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md). In short: a single FastAPI backend process serves a compiled React SPA and runs benchmark jobs in a background asyncio task. State lives in SQLite. No Docker, Redis, or external services are required.

## Requirements

- **Python 3.11+** (3.12 targeted; 3.11 works)
- **Node.js 18+** (for building the frontend)
- Windows 10/11 or a modern Ubuntu release

## Windows installation

```powershell
# From the repository root
.\setup-windows.ps1
```

This creates `backend\.venv`, installs Python dependencies, installs npm packages, and builds the frontend.

## Ubuntu installation

```bash
# Install system prerequisites (Ubuntu 22.04+)
sudo apt update
sudo apt install -y python3 python3-venv nodejs npm

# From the repository root
chmod +x setup-linux.sh run-linux.sh
./setup-linux.sh
```

## Starting and stopping

```powershell
# Windows
.\run-windows.ps1
```

```bash
# Linux
./run-linux.sh
```

Then open the printed URL. Stop the application with `Ctrl+C` in the terminal.

> **Important:** closing the **browser tab** does **not** stop a benchmark — the job runs in the backend process. Stopping the **backend process** (closing the terminal) interrupts the active run, which you can resume later. See [ARCHITECTURE.md](ARCHITECTURE.md#browser-independent-execution).

### Binding to another interface (advanced)

By default the app binds to `127.0.0.1` (localhost only). To bind elsewhere:

```bash
LOCALBENCH_HOST=0.0.0.0 ./run-linux.sh          # Linux
.\run-windows.ps1 -Host_ 0.0.0.0                 # Windows
```

⚠️ The application has **no multi-user authentication**. Only bind to another interface on a trusted private network.

## Local data locations

All data stays local:

- **Windows:** `%LOCALAPPDATA%\LocalBenchStudio`
- **Linux:** `~/.local/share/localbench-studio`

Contents: SQLite database, application logs, optional backups, and the directory where exports are written. Override with `LOCALBENCH_DATA_DIR`.

## Endpoint configuration

1. Open **Endpoints** → **+ New Endpoint**.
2. Enter a display name and base URL. Both `http://host` and `http://host/v1` are accepted; the app normalizes and never produces `/v1/v1`.
3. Optionally enter an API key (stored in the OS keyring when available) or an environment-variable name.
4. Click **Test** to verify reachability and model discovery, or **Models** to fetch available model names.

## API-key storage behavior

- API keys are **never returned to the frontend** after being saved. The UI only shows `••••••••` and whether a key exists.
- When the OS credential store is available, keys are stored via Python's `keyring` (Windows Credential Manager / GNOME Keyring / KWallet).
- When the keyring is unavailable you may: provide a key per session, reference an environment variable, or (with explicit opt-in) fall back to plaintext. The app never silently stores keys in SQLite.
- Keys are never written to logs, exports, or error reports. See [ARCHITECTURE.md](ARCHITECTURE.md#secret-handling).

## Creating a benchmark

1. Open **Benchmarks** → **+ New Benchmark**.
2. Open the benchmark and use **+ Add Prompt**.
3. In the prompt editor, set the category, difficulty, importance weight, and messages (system/user/assistant).
4. Choose a grading mode and configure its grader. See [SCORING.md](SCORING.md) and [BENCHMARK_FORMAT.md](BENCHMARK_FORMAT.md).

## Selecting grading modes

- **Deterministic** — exact/alias match, numeric tolerance, regex, concept coverage, JSON schema, multiple choice. Objective, reproducible.
- **LLM Judge** — open-ended answers an LLM evaluates against a rubric.
- **Hybrid** — deterministic checks + an LLM judge, with your chosen weighting (must total 100%). Critical failures can cap the score.
- **Manual review** — no automatic score; a human reviews and scores 0–100 later.

## Configuring an LLM judge

A judge is a separate endpoint + model selection. In **New Run**, pick a judge endpoint and model. You may use the same server with a different model, a separate local model, or a cloud model. If the target and judge are the same model, a warning is shown because self-judging can bias scores. You can start a run without a judge; judge-required prompts are then marked "awaiting judge" and can be judged later without rerunning the target.

## Running a benchmark

1. Open **New Run**.
2. Select benchmark, target endpoint, and target model. Optionally select a judge.
3. Configure generation defaults, repetitions, streaming, warm-up, verification pass.
4. Click **Start run**. The Active Run page shows live progress. You may close the browser; the job continues.

## Understanding scores

- **Quality Score** — weighted average of auto-scored prompt scores (0–100). Manual/pending prompts are excluded from the denominator until scored.
- **Reliability Score** — composite of completion, valid response, structure adherence, grade parse success, no truncation, and consistency across repetitions.
- **Performance Index** — derived from user-configurable TTFT / throughput / failure-rate thresholds. Performance is kept separate from quality by default.
- **Composite Score** — optional utility score; default weights Quality 85% / Reliability 10% / Performance 5%. This is user-configurable, **not** a universal intelligence score.

See [SCORING.md](SCORING.md) for exact formulas.

## Resuming interrupted runs

If the backend process stops mid-run, the run is marked **interrupted** on the next startup. Open it and click **Resume** — the run continues from the first incomplete prompt. Already-completed target prompts are never rerun unless you explicitly start a fresh run.

## Importing and exporting benchmarks

- **Export:** open a benchmark → **Export** to download a versioned JSON file (see [BENCHMARK_FORMAT.md](BENCHMARK_FORMAT.md)).
- **Import:** **Benchmarks** → **Import JSON** and select the file. Corrupt files are rejected with a clear error rather than partially imported.

## Exporting reports

Open a completed run → **Results** → choose **JSON**, **CSV**, or **HTML report**. Exports never contain API keys. The HTML report is a single standalone file.

## Backup and restore

Your entire state is the local data directory. Back it up by copying that directory. Restoring is as simple as replacing it (stop the app first).

## Troubleshooting

- **"Connection failed" on endpoint test** — confirm the server URL, that the server is running, and (for remote servers) network reachability. Many local servers need no API key.
- **API key not saving** — the OS keyring backend may be unavailable (common on minimal Linux without a desktop secret service). Use an environment variable or a session key instead.
- **Judge output invalid** — the run marks the prompt "awaiting manual review" and preserves the raw judge output; scores are never fabricated.
- **Run stuck in "queued"** — the backend runner polls every few seconds; ensure the backend process is still running.
- Download a sanitized diagnostics report from **Settings → Diagnostics**.

## Security limitations

- No multi-user authentication. Bind to localhost.
- API keys rely on the OS keyring; if it is unavailable, only session/env/plaintext-fallback options exist.
- The browser never contacts the LLM endpoint directly; all traffic is proxied by the backend, which injects credentials.
- Logs and exports are sanitized but you should still review them before sharing.

## Development setup

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate    # Linux   (.venv\Scripts\activate on Windows)
pip install -e ".[dev]"

# Frontend
cd ../frontend
npm install
npm run dev                   # Vite dev server on :5173, proxies /api to :8765
```

In development, run the backend (`uvicorn app.main:app --reload`) and the Vite dev server separately. See [DEVELOPMENT.md](DEVELOPMENT.md).

## Running tests

```bash
# Backend (pytest)
cd backend && python -m pytest

# Frontend (vitest)
cd frontend && npm run test

# Type checking
cd frontend && npx tsc --noEmit
```

## Building the frontend

```bash
cd frontend && npm run build
```

Output goes to `frontend/dist/`, which the FastAPI backend serves in production mode.

## Database migrations

Migrations are applied automatically on startup. To manage them manually:

```bash
cd backend
alembic upgrade head      # apply
alembic current           # check version
alembic downgrade -1      # roll back one
```

## License

Provided as-is for local benchmarking use.
