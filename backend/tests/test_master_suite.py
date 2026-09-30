"""Guards specific to the Master Suite.

The suite's answer key is generated, not written (scripts/build_master_suite.py),
which removes one whole class of mistake and introduces another: the committed
JSON can drift from the generator. These tests pin down the properties that
would otherwise fail silently -- an item nobody can win looks exactly like a hard
item, and a suite that has quietly stopped discriminating still produces
confident-looking scores.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.seed.suites_loader import SUITES_DIR

REPO = Path(__file__).resolve().parents[2]
BUILDER = REPO / "scripts" / "build_master_suite.py"
MASTER = SUITES_DIR / "master_suite.json"


def _suite() -> dict:
    return json.loads(MASTER.read_text(encoding="utf-8"))


def test_master_suite_is_present():
    assert MASTER.exists(), "master_suite.json is missing; run scripts/build_master_suite.py"
    assert len(_suite()["prompts"]) == 45


def test_committed_suite_matches_a_fresh_build():
    """The JSON must be exactly what the generator produces today.

    A hand-edit to the JSON is the failure this catches: it survives every other
    test here while silently decoupling an expected answer from the snippet that
    is supposed to produce it.
    """
    if shutil.which("node") is None:
        pytest.skip("node is required to re-execute the JavaScript items")
    if any("unmeasured" not in p.get("tags", []) for p in _suite()["prompts"]):
        pytest.skip(
            "suite has been calibrated; measured weights legitimately diverge from "
            "the generated defaults"
        )
    proc = subprocess.run(
        [sys.executable, str(BUILDER), "--check"],
        capture_output=True, text=True, timeout=900,
    )
    assert proc.returncode == 0, (
        "master_suite.json is stale or hand-edited; re-run "
        f"scripts/build_master_suite.py\n{proc.stdout}\n{proc.stderr}"
    )


def test_every_item_has_at_least_one_scored_check():
    """A prompt whose only check is a gate can never score above zero.

    run_deterministic treats gates as preconditions worth no points, so an item
    built entirely from them is unwinnable by construction.
    """
    broken = []
    for p in _suite()["prompts"]:
        gc = p["grader_config"]
        checks = gc.get("checks") or ([gc] if "type" in gc else [])
        if not checks:
            broken.append(f"{p['stable_id']}: no checks at all")
        elif all(c.get("gate") for c in checks):
            broken.append(f"{p['stable_id']}: every check is a gate")
    assert not broken, "\n  ".join(broken)


def test_no_regex_check_accepts_everything():
    """A regex check with no patterns passes any text, including silence.

    grade_regex with neither required nor forbidden patterns returns full marks
    unconditionally, so such a check inflates every model's score by exactly the
    same amount and measures nothing.
    """
    vacuous = []
    for p in _suite()["prompts"]:
        gc = p["grader_config"]
        for c in gc.get("checks") or ([gc] if "type" in gc else []):
            if c.get("type") != "regex":
                continue
            if not c.get("required_patterns") and not c.get("forbidden_patterns"):
                vacuous.append(f"{p['stable_id']}: regex check with no patterns")
    assert not vacuous, "\n  ".join(vacuous)


def test_weights_are_marked_unmeasured_until_calibrated():
    """Predicted weights must not be mistaken for observed ones.

    SCORING.md is explicit that weight belongs on items measured to
    discriminate. Everything here is a guess until scripts/calibrate_suite.py
    has been run, and the tag is what says so.
    """
    for p in _suite()["prompts"]:
        tags = p.get("tags", [])
        if "unmeasured" in tags:
            assert "discriminator" not in tags and "anchor" not in tags, (
                f"{p['stable_id']} carries a calibration tag while still marked "
                "unmeasured"
            )


def test_long_context_items_are_actually_long():
    """The long-context items only test long context if they are long."""
    prompts = [p for p in _suite()["prompts"] if p["category"].startswith("long-context")]
    assert prompts, "no long-context items found"
    for p in prompts:
        chars = sum(len(m["content"]) for m in p["messages"])
        assert chars >= 8000, (
            f"{p['stable_id']} is only {chars} characters; that fits in any context "
            "window and measures nothing about retrieval"
        )


def test_duration_problem_items_are_retired():
    retired = {
        "ms-py-class-creation-order", "ms-cs-minimal-dfa",
        "ms-sci-coupled-diprotic-mixture", "ms-sci-cycle-entropy",
        "ms-sci-nested-velocity-legs",
        "ms-math-multiplicative-order", "ms-math-lcm-matrix-determinant",
        "ms-cs-natural-mergesort", "ms-cs-dynamic-array-copies",
        "ms-abs-false-output-claim",
    }
    assert not retired.intersection(p["stable_id"] for p in _suite()["prompts"])
