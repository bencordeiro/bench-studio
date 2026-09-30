# LocalBench Studio

LocalBench Studio is a **desktop-hosted web application for benchmarking one LLM at a time** through an OpenAI-compatible API endpoint. It runs locally on Windows or Ubuntu, stores all data locally, executes benchmark jobs independently of the browser connection, automatically grades responses, and presents detailed analytics.

> **What it is not:** not a cloud service, not a multi-user system, not a distributed benchmarking farm, and not a universal "intelligence score." It is a serious local engineering tool for measuring one model's quality, reliability, and latency against rubrics you define.

## What it does

- Save one or more OpenAI-compatible endpoint profiles (with optional API keys stored in the OS credential store).
- Start from nine bundled suites (389 prompts): eight custom suites with automated validation plus the public **HumanEval** benchmark, or author your own.
- Grade each prompt one of five ways: **deterministic**, **LLM judge**, **hybrid**, **manual review**, or **execution** (run the generated code against unit tests). Deterministic graders cover exact/numeric/regex/concept/JSON/multiple-choice/count and parsed **tool calls**.
- Run a benchmark against one target model; close/refresh the browser without stopping the run.
- Reopen later and see live progress, resume interrupted runs.
- See **Total time** for each finished run in the Runs history, run detail and Results summary. It uses saved start/finish timestamps, including warm-up, grading, retries and pauses in resumed runs; existing history works too. Runs without both timestamps show “—”.
- View detailed analytics: quality, reliability, performance, per-prompt scores, latency distributions.
- Compare completed runs. Per-suite leaderboards ranking every tested model. Export JSON / CSV / standalone HTML reports.
- Keep a separate judge endpoint so the model under test is not grading itself (with a clear warning when it is).

## Endpoint setup

Choose **Endpoint Profiles → New Endpoint → Provider preset** to fill the API URL and key environment variable. Presets include OpenAI, Alibaba/Qwen (Singapore and Beijing), DeepSeek, Z.ai, xAI, Anthropic, Gemini, Groq, Mistral, OpenRouter, and local Ollama. Enter a model ID and a key (or set the environment variable), save, then use **Test** and **Models**. Model availability and supported generation parameters depend on your provider account; presets do not pin models or prices. Alibaba workspace URLs require replacing `{WorkspaceId}`. Each preset links to its official documentation.

## Bundled benchmark suites

Nine suites ship with the app and load on first run (389 prompts). Eight contain custom items designed to reduce reliance on familiar public benchmark questions. Mini Master intentionally shares some questions with Master. Originality does not guarantee freedom from training-data contamination. The ninth is the public **HumanEval** benchmark, included for numbers that stay comparable to the published literature.

| Suite | Prompts | What it measures |
|---|---|---|
| Code Reasoning (Python) | 50 | 30 output-reasoning questions and 20 original executable function tasks covering practical data processing and edge cases |
| Web Dev Correctness (JS) | 45 | Coercion, the event loop and microtask ordering, prototypes, async semantics, JSON edge cases |
| Agentic Tool-Use (Hermes) | 15 | Function calling in BFCL categories: simple, tool selection, parallel, argument precision, relevance |
| Instruction-Following | 15 | IFEval-style stacked constraints: exact counts, forbidden vocabulary, strict JSON, custom markup |
| **Master Suite** | 45 | Cross-domain reasoning with concise answer contracts — see below |
| **Mini Master** | 25 | Selected Master code/tool questions plus compact math, systems, engineering, false-premise and context variants |
| **Cyber** | 18 | Defensive security: vulnerability identification, access controls, hardening, alert analysis, containment and patch triage; strict JSON answers |
| Terminal Semantics & System Gotchas | 12 | Linux shell/permissions, git reachability, date normalization, log aggregation, text processing, SQLite WAL, cron, bash pipefail, packaging, locale sort, filesystem, iptables |
| **HumanEval (OpenAI)** | 164 | Code generation: complete the function, executed against its unit tests — see below |

See [the suite audit](docs/SUITE_AUDIT.md) for revisions, validation evidence, and limitations. Updated bundles upgrade in place on startup; historical runs retain their snapshots. The retired example suite is removed by migration.

Cyber uses original, self-contained scenarios with fixed policy assumptions and deterministic answer keys. It needs no tool calls, code execution or judge. See [its answer-key review and grading contract](docs/CYBER_SUITE.md). Its difficulty estimates have not been measured against models.

Mini Master keeps Master's cross-domain mix in 25 questions: 13 selected items and 12 compact variants. It excludes **Class scope versus comprehension scope**, reduces cache/clock/transaction traces, and replaces long evidence corpora with short precedence and reconciliation exercises. Every question is graded deterministically and uses global generation limits. See [the selection and reference controls](docs/MINI_MASTER_SUITE.md). Duration is unmeasured; no endpoint tokens were used to validate this addition.

Tool questions support Hermes text and native API function calling. The app automatically selects native `tools` / `tool_calls` when a server rejects literal Hermes blocks, converts supplied call/result histories, and grades the same tool names and argument values. The server's tool-call parser can remain enabled. The selected protocol is recorded with each run; comparisons warn when protocols differ. A tool transport failure affects that question while the rest of a mixed suite continues. See [the compatibility notes and live validation](docs/HERMES_ENDPOINT_COMPATIBILITY.md).

Design rules the original items follow (HumanEval keeps the upstream problems as-is):

- **Code answers are checked by execution.** Output predictions are reproduced with CPython / Node; function tasks run reference solutions against edge-case tests. Structured-output items have compliant and violating response controls.
- **Graded without a judge.** No judge is required for any bundled suite — the deterministic graders or test execution decide — so results are reproducible.
- **No item pays out for a non-answer.** Prohibitions ("do not use the letter 'e'") are trivially satisfied by silence, so every such item is gated on a separate check proving the task was attempted.
- **Difficulty comes from depth, not obscurity.** Items chain several inferences rather than testing trivia, and answers are kept short so the score measures reasoning rather than transcription.

`backend/tests/test_suite_quality.py` enforces these as executable invariants, so a new or edited item cannot quietly break them.

### The Master Suite

The four base suites measure one competence each, and a strong model saturates them. The Master Suite exists for the other question: **given two models that both look good, which is actually better?** It is cross-domain, deterministically graded, and built to stay unsaturated.

| Domain | Items | Sample of what it covers |
|---|---|---|
| Code reasoning (Python / JS) | 18 | `ExitStack` unwinding, `Symbol.toPrimitive` hints, field initialization vs `super()`, thenable microtask cost |
| Quantitative reasoning | 5 | Multiset counting, a pattern race, posterior probability, GCD triple sums, circumradius |
| Algorithms & distributed systems | 3 | Segmented-LRU simulation, vector clocks, transaction replay with rollback and retries |
| Physics | 1 | Rolling-transition dynamics |
| Automotive engineering | 1 | Intercooler charge temperature |
| Abstention & false premises | 4 | Planted falsehoods the model must refuse rather than elaborate |
| Multi-turn stateful tool use | 5 | Id propagation past a decoy, error recovery, withholding an unsafe action |
| Long-context synthesis | 4 | 3.5k–6.4k token corpora with conflicting facts and precedence rules |
| Anchors from the base suites | 4 | Lowest-weighted, so a run still says something about a model that scores near zero |

Master 5.0.0 removes five lengthy manual calculations/simulations and asks for concise final answers, with existing numeric tolerances stated explicitly. The [Qwen Flash duration investigation](docs/CALIBRATION_QWENFLASH_MASTER_2026_09_29.md) records the 50-question baseline and two successful prompt trials. The revised 45-question suite has not been retested end to end; the 15–30 minute target is not a guaranteed duration. Global token budgets and the model's reasoning behavior still affect timing.

Three properties make it different from the base suites:

- **Nothing is hand-written — including the answer key.** `scripts/build_master_suite.py` re-executes every snippet, recomputes every quantity (several against a second independent method), and generates each long-context corpus together with its ground truth. Rebuild and the JSON regenerates byte-identically, or an item was wrong. `python scripts/build_master_suite.py --check` verifies the committed file is current.
- **Every item is proven winnable.** The base suites verify that a non-answer scores zero. That is half a guarantee: a required pattern with a typo produces an item that scores zero for *everyone*, which is invisible because it looks like difficulty. The builder grades each item against a model answer that must earn 100.
- **The items built to catch a mistake are proven to catch it.** Each false-premise and agentic item is also graded against the confident wrong answer — swallowing the premise, reusing the decoy id, acting despite a failed precondition — which must stay below 35.

A four-tier ladder does the separating: **anchor** (weight 1.5) from the base suites, **hard** (2.0), **extreme** (3.0), and **frontier** (4.0) for items expected to break current frontier models, leaving headroom as models improve.

> **The weights are predictions, not measurements.** Every item is tagged `unmeasured`. Guessed difficulty is unreliable — that lesson is what produced `calibrate_suite.py` in the first place. Run the calibration below against two models of different capability before trusting any ranking this suite produces.

### HumanEval (OpenAI)

The 164 hand-written Python function-completion problems from OpenAI's Codex paper (Chen et al., 2021, ["Evaluating Large Language Models Trained on Code"](https://arxiv.org/abs/2107.03374)). The dataset is **MIT-licensed** and vendored under `data/humaneval/` (source: [openai/human-eval](https://github.com/openai/human-eval); see `data/humaneval/ATTRIBUTION.md`).

It is the one bundled suite that is *not* original — deliberately. The custom suites provide complementary tasks; HumanEval is included so your scores stay **comparable to the published literature**, and it is wrapped for strict parity with the reference harness:

- Each prompt is the dataset's problem text, **byte-for-byte** (verified by `backend/tests/test_humaneval_suite.py`).
- The model's completion is executed as `prompt + completion + test + check(entry_point)` in a fresh `python -I` subprocess with the reference harness's **3.0-second timeout**, its reliability guard, and its `passed / timed out / failed` classification — no partial credit, no markdown-fence stripping.
- Every item carries the **same weight**, so the suite's Quality score is exactly the unweighted pass rate — standard **pass@1**.
- `scripts/build_humaneval_suite.py` regenerates the suite and re-executes all 164 canonical solutions before writing; `--check` verifies the committed file is current.

> **Security note.** This suite's grader executes untrusted model-generated code. The child process is isolated (throwaway cwd, stdin closed, isolated Python mode) and runs under a reliability guard that removes destructive builtins — but that is a guard, not a sandbox, and the reference harness says the same. Run execution-graded suites on a machine you can afford to have poked at.

```bibtex
@article{chen2021codex,
  title={Evaluating Large Language Models Trained on Code},
  author={Mark Chen and Jerry Tworek and Heewoo Jun and Qiming Yuan and Henrique Ponde de Oliveira Pinto and Jared Kaplan and Harri Edwards and Yuri Burda and Nicholas Joseph and Greg Brockman and Alex Ray and Raul Puri and Gretchen Krueger and Michael Petrov and Heidy Khlaaf and Girish Sastry and Pamela Mishkin and Brooke Chan and Scott Gray and Nick Ryder and Mikhail Pavlov and Alethea Power and Lukasz Kaiser and Mohammad Bavarian and Clemens Winter and Philippe Tillet and Felipe Petroski Such and Dave Cummings and Matthias Plappert and Fotios Chantzis and Elizabeth Barnes and Ariel Herbert-Voss and William Hebgen Guss and Alex Nichol and Alex Paino and Nikolas Tezak and Jie Tang and Igor Babuschkin and Suchir Balaji and Shantanu Jain and William Saunders and Christopher Hesse and Andrew N. Carr and Jan Leike and Josh Achiam and Vedant Misra and Evan Morikawa and Alec Radford and Matthew Knight and Miles Brundage and Mira Murati and Katie Mayer and Peter Welinder and Bob McGrew and Dario Amodei and Sam McCandlish and Ilya Sutskever and Wojciech Zaremba},
  year={2021},
  eprint={2107.03374},
  archivePrefix={arXiv},
  primaryClass={cs.LG}
}
```

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
- When the keyring is unavailable, entered keys stay in server memory for Test, Models and benchmark runs. Re-enter them after restarting Bench Studio, or reference an environment variable for use across restarts. Keys are not stored in SQLite; the legacy plaintext-fallback option does not provide durable storage.
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
- API keys use the OS keyring or server memory; environment variables also work. Keys held in memory must be re-entered after an app restart.
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
