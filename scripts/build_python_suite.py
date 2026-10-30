"""Rebuild the 40-question Python suite and its original execution contracts."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from textwrap import indent

from hardening_tasks import PYTHON_REASONING
from python_tasks import TASKS

RETIRED_FUNCTIONS = {
    "dependency_batches",
    "apply_patch",
    "allocate_cents",
    "first_conflict",
    "latest_records",
    "missing_ranges",
}
ACTIVE_TASKS = [t for t in TASKS if t["name"] not in RETIRED_FUNCTIONS]

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend/app/seed/suites/code_reasoning_python.json"
RETAIN = [
    "cr-closure-late-binding",
    "cr-list-mult-aliasing",
    "cr-decorator-attr-target",
    "cr-floordiv-negatives",
    "cr-try-else",
    "cr-chained-aug-assign",
    "cr-yield-from-sum",
    "cr-mro-diamond",
    "cr-slice-assign-step",
    "cr-nonlocal-counter",
    "cr-sort-key-stability",
    "cr-dict-view-live",
    "cr-default-dict-vs-setdefault",
    "cr-generator-finally-close",
    "cr-chained-comparison",
    "cr-class-var-shadow",
    "cr-tuple-mutation-error",
    "cr3-descriptor-protocol",
    "cr3-context-suppress",
    "cr3-reflected-operator",
    "cr3-generator-send",
    "cr3-shallow-vs-deep",
    "cr3-iter-self-exhaust",
    "cr3-closure-cell-rebind",
    "cr3-dict-mutation-order",
]


def execution_prompt(t):
    prefix = (
        f"def {t['name']}({t['signature']}):\n"
        + indent(
            '"""'
            + t["contract"]
            + '\nDo not mutate any input. Use only the Python standard library.\nInputs satisfy the stated preconditions; no malformed-input validation is required.\n"""',
            "    ",
        )
        + "\n"
    )
    test = "def check(candidate):\n    from copy import deepcopy\n"
    for args, expected in t["cases"]:
        test += f'    args = {args!a}\n    original = deepcopy(args)\n    assert candidate(*args) == {expected!a}\n    assert args == original, "inputs mutated"\n'
    return {
        "stable_id": "cr-fn-" + t["name"].replace("_", "-"),
        "title": t["title"],
        "description": t["contract"],
        "category": "code-generation/python",
        "tags": ["python", "execution-graded", "original", "unmeasured"],
        "difficulty": "hard",
        "importance_weight": 3.0,
        "enabled": True,
        "grading_mode": "execution",
        "generation_overrides": {"temperature": 0.0},
        "grader_config": {
            "language": "python",
            "completion_mode": "full_function",
            "entry_point": t["name"],
            "timeout_seconds": 3.0,
            "test_code": test,
        },
        "messages": [
            {
                "role": "system",
                "content": "Implement the Python function below. Return the complete function definition, including its def line, as raw Python. Do not use Markdown fences or explanations. Preserve the requested function name and signature. A compact implementation that satisfies the contract is sufficient; do not add a test harness, commentary, or alternative implementations.",
            },
            {"role": "user", "content": prefix},
        ],
    }


def build():
    suite = json.loads(OUT.read_text())
    suite["prompts"] = [p for p in suite["prompts"] if p["stable_id"] in RETAIN]
    assert len(suite["prompts"]) == 25
    for p in suite["prompts"]:
        p["messages"][0]["content"] = (
            "Determine the exact single line printed by this self-contained Python 3 program. "
            "Reply only with ANSWER: <output>, using the literal printed output. "
            "Do not include an explanation, quotes around the output, or Markdown fences."
        )
    code = PYTHON_REASONING["code"]
    output = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                            check=True, timeout=5).stdout.strip()
    suite["prompts"].append({
        "stable_id": PYTHON_REASONING["stable_id"], "title": PYTHON_REASONING["title"],
        "description": PYTHON_REASONING["description"], "category": "code-reasoning/python",
        "tags": ["python", "original", "unmeasured", "execution-verified"],
        "difficulty": "hard", "importance_weight": 3.0, "enabled": True,
        "grading_mode": "deterministic", "generation_overrides": {"temperature": 0.0},
        "grader_config": {"type": "exact", "canonical_answer": output, "accepted_aliases": [],
                          "case_sensitive": True, "trim_whitespace": True,
                          "normalize_punctuation": False, "points": 100.0},
        "messages": [{"role": "system", "content": suite["prompts"][0]["messages"][0]["content"]},
                     {"role": "user", "content": code}],
    })
    suite["prompts"].extend(execution_prompt(t) for t in ACTIVE_TASKS)
    assert len(suite["prompts"]) == 40
    for i, p in enumerate(suite["prompts"]):
        p["position"] = i
        for j, m in enumerate(p["messages"]):
            m["position"] = j
    suite["version"] = "8.0.0"
    suite["description"] = (
        "40 Python questions: 26 output-reasoning items and 14 original complete-function tasks. Covers mutation, scope, descriptors, reflected operators, delegated-generator throw/return/cleanup, rolling event windows, caches, parsing and nested data. Output keys are executed locally; function checks cover edge cases and non-mutation. Difficulty and duration are unmeasured for this revision. Python 3.10+; no third-party packages or network required."
    )
    return suite


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(build(), indent=2, ensure_ascii=True) + "\n"
    if args.check:
        if OUT.read_text() != rendered:
            raise SystemExit("Python suite is stale")
        print("Python suite is up to date (40 questions)")
    else:
        OUT.write_text(rendered)
        print("Wrote Python suite (40 questions)")
