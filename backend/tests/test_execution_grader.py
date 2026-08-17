"""Behaviour of the execution grader (app/graders/execution.py).

The grader must agree with the HumanEval reference harness: same program
assembly, same pass/timed-out/failed classification, no repair of the
completion text.
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.graders.execution import build_check_program, run_execution

PROMPT = 'def add_one(n):\n    """Return n plus one."""\n'
TEST = "\n\ndef check(candidate):\n    assert candidate(1) == 2\n    assert candidate(0) == 1\n"
ENTRY = "add_one"

GC = {"language": "python", "test_code": TEST, "entry_point": ENTRY, "timeout_seconds": 3.0}


def test_program_assembly_matches_reference_harness():
    """Byte-identical to openai/human-eval: no spacing or repairs added."""
    prompt, completion = "def f():\n", "    return 1"
    test, entry = "\n\ndef check(c):\n    assert c() == 1\n", "f"
    assert build_check_program(prompt, completion, test, entry) == (
        prompt + completion + "\n" + test + "\n" + "check(f)"
    )


def test_correct_completion_passes():
    r = run_execution(GC, "    return n + 1\n", PROMPT)
    assert r["passed"] is True
    assert r["score"] == 100.0
    assert r["details"]["status"] == "passed"


def test_wrong_completion_fails():
    r = run_execution(GC, "    return n + 2\n", PROMPT)
    assert r["passed"] is False
    assert r["score"] == 0.0
    assert r["details"]["status"].startswith("failed:")


def test_empty_completion_fails():
    r = run_execution(GC, "", PROMPT)
    assert r["passed"] is False and r["score"] == 0.0


def test_infinite_loop_times_out():
    r = run_execution(
        {**GC, "timeout_seconds": 1.0},
        "    while True:\n        pass\n",
        PROMPT,
    )
    assert r["passed"] is False
    assert r["details"]["status"] == "timed out"


def test_early_exit_is_not_a_pass():
    """sys.exit(0) before the tests run must fail, matching the reference
    harness (where SystemExit is caught and scored as a failure)."""
    r = run_execution(GC, "    import sys\n    sys.exit(0)\n", PROMPT)
    assert r["passed"] is False
    assert r["details"]["status"].startswith("failed:")


def test_fenced_completion_fails():
    """Parity with the reference harness: the completion is used as-is, so a
    markdown-fenced reply is a SyntaxError, not silently unwrapped code."""
    r = run_execution(GC, "```python\n    return n + 1\n```\n", PROMPT)
    assert r["passed"] is False
    assert r["details"]["status"].startswith("failed:")


def test_guard_neutralizes_destructive_calls():
    marker = Path("/tmp/opencode/localbench-guard-marker")
    if marker.exists():
        marker.unlink()
    r = run_execution(
        GC,
        "    import os\n    os.system('touch " + str(marker) + "')\n    return n + 1\n",
        PROMPT,
    )
    assert r["passed"] is False
    assert not marker.exists(), "os.system was not neutralised in the child"


def test_incomplete_config_fails_cleanly():
    r = run_execution({"test_code": TEST}, "    return n + 1\n", PROMPT)
    assert r["passed"] is False
    assert r["details"]["status"].startswith("failed:")
    r = run_execution(GC, "    return n + 1\n", "")
    assert r["passed"] is False
