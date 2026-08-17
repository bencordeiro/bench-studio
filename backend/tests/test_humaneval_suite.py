"""Guards specific to the HumanEval suite.

The suite wraps OpenAI's reference dataset (data/humaneval/human-eval.jsonl,
MIT). The wrap must stay a faithful wrap: the prompts must be the dataset's
prompts byte-for-byte, the committed JSON must be exactly what the builder
produces, and every canonical solution must pass under the execution grader
-- a problem whose tests were mangled in translation would score zero for
every model and be indistinguishable from difficulty.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.graders.execution import run_execution
from app.graders.scoring import overall_quality_score
from app.seed.suites_loader import SUITES_DIR

REPO = Path(__file__).resolve().parents[2]
BUILDER = REPO / "scripts" / "build_humaneval_suite.py"
DATASET = REPO / "data" / "humaneval" / "human-eval.jsonl"
SUITE = SUITES_DIR / "humaneval.json"


def _suite() -> dict:
    return json.loads(SUITE.read_text(encoding="utf-8"))


def _dataset() -> dict[str, dict]:
    return {
        r["task_id"]: r
        for r in (json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines() if l.strip())
    }


def test_suite_is_present_and_complete():
    suite = _suite()
    prompts = suite["prompts"]
    assert len(prompts) == 164
    assert [p["stable_id"] for p in prompts] == [f"HumanEval/{i}" for i in range(164)]
    for p in prompts:
        assert p["grading_mode"] == "execution"
        assert p["importance_weight"] == 3.0
        assert p["enabled"] is True
        assert p["grader_config"]["timeout_seconds"] == 3.0
        assert p["messages"][0]["role"] == "user"


def test_prompts_are_the_dataset_prompts_byte_for_byte():
    """Any rewording here silently changes what is being measured."""
    dataset = _dataset()
    for p in _suite()["prompts"]:
        assert p["messages"][0]["content"] == dataset[p["stable_id"]]["prompt"], p["stable_id"]
        assert p["grader_config"]["test_code"] == dataset[p["stable_id"]]["test"], p["stable_id"]
        assert p["grader_config"]["entry_point"] == dataset[p["stable_id"]]["entry_point"], p["stable_id"]


def test_committed_suite_matches_a_fresh_build():
    """A hand-edit to the JSON is the failure this catches: it decouples the
    shipped prompts/tests from the vendored dataset without breaking anything
    that runs before grading."""
    proc = subprocess.run(
        [sys.executable, str(BUILDER), "--check"],
        capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, (
        "humaneval.json is stale or hand-edited; re-run "
        f"scripts/build_humaneval_suite.py\n{proc.stdout}\n{proc.stderr}"
    )


def test_every_canonical_solution_passes():
    """Winnability, re-verified at test time: the reference solution must
    earn 100 on every problem under the shipped grader config."""
    dataset = _dataset()
    failing = []
    for p in _suite()["prompts"]:
        row = dataset[p["stable_id"]]
        result = run_execution(
            p["grader_config"], row["canonical_solution"], p["messages"][0]["content"]
        )
        if not result["passed"]:
            failing.append(f"{p['stable_id']}: {result['details']['status']}")
    assert not failing, "canonical solutions that fail their own tests:\n  " + "\n  ".join(failing)


def test_broken_solutions_score_zero():
    dataset = _dataset()
    for sid in ("HumanEval/0", "HumanEval/82", "HumanEval/163"):
        p = next(x for x in _suite()["prompts"] if x["stable_id"] == sid)
        result = run_execution(
            p["grader_config"], "    raise NotImplementedError\n", p["messages"][0]["content"]
        )
        assert result["score"] == 0.0, sid


def test_uniform_weights_make_quality_the_unweighted_pass_rate():
    """Parity property: with every item equally weighted, the suite's Quality
    score is exactly pass@1, so published numbers stay comparable."""
    prompts = [
        {"score": 100.0 if i < 82 else 0.0, "weight": 3.0, "status": "completed"}
        for i in range(164)
    ]
    quality, scored, total = overall_quality_score(prompts)
    assert scored == total == 164
    assert quality == 100.0 * 82 / 164
