"""Build the HumanEval suite from the vendored OpenAI dataset.

Why this file exists
--------------------
The HumanEval suite wraps OpenAI's reference dataset (164 hand-written
Python function-completion problems, "Evaluating Large Language Models
Trained on Code", MIT license -- see data/humaneval/ATTRIBUTION.md) in the
localbench-benchmark format. The wrap has two non-negotiable properties:

  1. Parity. Each prompt's user message is the dataset's `prompt` field,
     byte-for-byte, and grading executes
         prompt + completion + "\\n" + test + "\\n" + check(entry_point)
     in a fresh process with the reference harness's 3.0-second timeout and
     its pass/timed-out/failed classification (app/graders/execution.py).
     Nothing is stripped, repaired or reworded: a completion that fails
     under the reference harness fails here, and one that passes passes.
  2. Winnability. Before the suite is written, every canonical solution is
     actually executed and must pass, and a planted broken solution must
     fail. A problem whose tests were mangled in translation would otherwise
     score zero for every model -- indistinguishable from difficulty.

Weighting: every item carries the same weight, on purpose. The reference
metric is the unweighted pass rate (pass@1); re-weighting items would make
the suite's Quality score drift from the published number. Uniform weight
also satisfies the bundled-suite invariants in test_suite_quality.py
(>=10% of a large suite's weight on items weighted >= 3.0).

Usage
-----
    python scripts/build_humaneval_suite.py            # verify + write the suite
    python scripts/build_humaneval_suite.py --check    # verify it is up to date
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "data" / "humaneval" / "human-eval.jsonl"
OUT = REPO / "backend" / "app" / "seed" / "suites" / "humaneval.json"

EXPECTED_PROBLEMS = 164
TIMEOUT_SECONDS = 3.0
IMPORTANCE_WEIGHT = 3.0

SUITE_NAME = "HumanEval (OpenAI)"
SUITE_VERSION = "1.0.0"


def _load_grader():
    """Import the execution grader without the DB dependency stack.

    app.graders.execution is pure stdlib, but importing it through the `app`
    package pulls in SQLAlchemy and pydantic. Loading the file directly keeps
    this script runnable anywhere Python 3 is.
    """
    spec = importlib.util.spec_from_file_location(
        "_he_execution", REPO / "backend" / "app" / "graders" / "execution.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GRADER = _load_grader()


def load_problems() -> list[dict]:
    rows = [json.loads(line) for line in SRC.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != EXPECTED_PROBLEMS:
        raise SystemExit(f"expected {EXPECTED_PROBLEMS} problems in {SRC.name}, found {len(rows)}")
    ids = [r["task_id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise SystemExit("duplicate task_id in dataset")
    for r in rows:
        for field in ("task_id", "prompt", "canonical_solution", "test", "entry_point"):
            if not r.get(field):
                raise SystemExit(f"{r.get('task_id')}: missing field {field!r}")
    return rows


def docstring_of(prompt: str, entry_point: str) -> str:
    m = re.search(r"def\s+%s\b.*" % re.escape(entry_point), prompt, re.S)
    body = m.group(0) if m else prompt
    for q in ('"""', "'''"):
        m = re.search(re.escape(q) + r"(.*?)" + re.escape(q), body, re.S)
        if m:
            return m.group(1).strip()
    return ""


def build_prompts(problems: list[dict]) -> list[dict]:
    prompts = []
    for i, r in enumerate(problems):
        entry = r["entry_point"]
        doc = docstring_of(r["prompt"], entry)
        grader_config = {
            "language": "python",
            "test_code": r["test"],
            "entry_point": entry,
            "timeout_seconds": TIMEOUT_SECONDS,
        }
        # The suite-quality invariants require every grader_config string to
        # be ASCII; the prompt text (which may contain unicode in docstrings)
        # lives in the message, not here.
        for v in grader_config.values():
            if isinstance(v, str) and any(ord(c) > 127 for c in v):
                raise SystemExit(f"{r['task_id']}: non-ASCII in grader_config")
        prompts.append(
            {
                "stable_id": r["task_id"],
                "title": entry,
                "description": doc or f"Complete the function {entry}.",
                "category": "code-generation",
                "tags": ["humaneval", "code-generation", "execution-graded"],
                "difficulty": "medium",
                "importance_weight": IMPORTANCE_WEIGHT,
                "position": i,
                "enabled": True,
                "grading_mode": "execution",
                "generation_overrides": {"temperature": 0.0},
                "grader_config": grader_config,
                "messages": [{"role": "user", "content": r["prompt"], "position": 0}],
            }
        )
    return prompts


def verify_winnable(problems: list[dict], prompts: list[dict]) -> None:
    """The dataset must translate cleanly: canonical solutions pass, a broken
    solution fails. This is what keeps a mangled test from masquerading as a
    hard problem."""
    unwinnable, leaky = [], []
    for p, r in zip(prompts, problems):
        result = GRADER.run_execution(p["grader_config"], r["canonical_solution"], p["messages"][0]["content"])
        if not result["passed"]:
            unwinnable.append(f"{p['stable_id']}: {result['details']['status']}")
    for sid in ("HumanEval/0", "HumanEval/82", "HumanEval/163"):
        p = next(x for x in prompts if x["stable_id"] == sid)
        result = GRADER.run_execution(p["grader_config"], "    raise NotImplementedError\n", p["messages"][0]["content"])
        if result["passed"]:
            leaky.append(f"{sid}: a broken solution passed")
    if unwinnable:
        raise SystemExit("canonical solutions that fail their own tests:\n  " + "\n  ".join(unwinnable))
    if leaky:
        raise SystemExit("tests that pass a broken solution:\n  " + "\n  ".join(leaky))


def build(problems: list[dict], prompts: list[dict]) -> dict:
    total_weight = sum(p["importance_weight"] for p in prompts)
    heavy = sum(p["importance_weight"] for p in prompts if p["importance_weight"] >= 3.0)
    assert heavy / total_weight >= 0.10, heavy / total_weight
    assert max(p["importance_weight"] for p in prompts) / total_weight < 0.25
    assert len({p["stable_id"] for p in prompts}) == len(prompts), "duplicate stable_id"

    return {
        "format": "localbench-benchmark",
        "format_version": "1.0",
        "exported_at": datetime(2026, 8, 15, tzinfo=timezone.utc).isoformat(),
        "name": SUITE_NAME,
        "description": (
            "The 164 hand-written Python function-completion problems from "
            "OpenAI's Codex paper (Chen et al., 2021, MIT license, "
            "data/humaneval/ATTRIBUTION.md). Each prompt is the original "
            "problem text, byte-for-byte; the model's completion is executed "
            "against the problem's unit tests with the reference harness's "
            "semantics (3-second timeout, no partial credit, no fence "
            "stripping). The Quality score is the unweighted pass rate -- "
            "standard pass@1 -- so results are directly comparable to "
            "published HumanEval numbers. No judge endpoint required. This "
            "grader executes untrusted model-generated code in an isolated "
            "subprocess; see the README's security note."
        ),
        "version": SUITE_VERSION,
        "tags": ["humaneval", "code-generation", "execution", "openai", "pass-at-1"],
        "scoring_config": {},
        "performance_thresholds": {
            "desired_ttft": 0.5,
            "max_ttft": 10.0,
            "desired_tps": 40.0,
            "min_tps": 5.0,
            "max_failure_rate": 0.1,
        },
        "composite_weights": {"quality": 0.9, "reliability": 0.07, "performance": 0.03},
        "prompts": prompts,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the committed suite matches a fresh build (no test execution)")
    args = ap.parse_args()

    problems = load_problems()
    prompts = build_prompts(problems)

    if not args.check:
        print(f"verifying winnability: executing {len(prompts)} canonical solutions...")
        verify_winnable(problems, prompts)
        print("  all canonical solutions pass; broken solutions fail")

    suite = build(problems, prompts)
    rendered = json.dumps(suite, indent=2, ensure_ascii=True) + "\n"

    if args.check:
        if not OUT.exists():
            print(f"MISSING: {OUT}", file=sys.stderr)
            return 1
        if OUT.read_text(encoding="utf-8") != rendered:
            print(f"STALE: {OUT} differs from a fresh build", file=sys.stderr)
            return 1
        print(f"up to date: {OUT.relative_to(REPO)} ({len(suite['prompts'])} prompts)")
        return 0

    OUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}: {len(suite['prompts'])} prompts")
    print(f"  total weight: {sum(p['importance_weight'] for p in suite['prompts']):.1f} (uniform)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
