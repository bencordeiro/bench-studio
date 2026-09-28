"""Rebuild the original execution tasks in the 50-question Python suite."""

import argparse
import json
from pathlib import Path
from textwrap import indent

from python_tasks import TASKS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend/app/seed/suites/code_reasoning_python.json"
RETAIN = """cr-closure-late-binding cr-mutable-default cr-list-mult-aliasing cr-decorator-attr-target cr-floordiv-negatives cr-try-else cr-chained-aug-assign cr-yield-from-sum cr-mro-diamond cr-slice-assign-step cr-nonlocal-counter cr-sort-key-stability cr-dict-view-live cr-default-dict-vs-setdefault cr-generator-finally-close cr-chained-comparison cr-class-var-shadow cr-tuple-mutation-error cr-zip-strict-uneven cr3-descriptor-protocol cr3-context-suppress cr3-reflected-operator cr3-super-kwargs-chain cr3-generator-send cr3-shallow-vs-deep cr3-iter-self-exhaust cr3-exception-chaining cr3-closure-cell-rebind cr3-dict-mutation-order cr4-accumulator-dict""".split()


def execution_prompt(t):
    prefix = (
        f"def {t['name']}({t['signature']}):\n"
        + indent(
            '"""' + t["contract"] + '\nDo not mutate any input. Use only the Python standard library.\n"""',
            "    ",
        )
        + "\n"
    )
    test = "def check(candidate):\n    from copy import deepcopy\n"
    for args, expected in t["cases"]:
        test += f'    args = {args!a}\n    original = deepcopy(args)\n    assert candidate(*args) == {expected!a}\n    assert args == original, "inputs mutated"\n'
    return dict(
        stable_id="cr-fn-" + t["name"].replace("_", "-"),
        title=t["title"],
        description=t["contract"],
        category="code-generation/python",
        tags=["python", "execution-graded", "original", "unmeasured"],
        difficulty="hard",
        importance_weight=3.0,
        enabled=True,
        grading_mode="execution",
        generation_overrides={"temperature": 0.0},
        grader_config={
            "language": "python",
            "entry_point": t["name"],
            "timeout_seconds": 3.0,
            "test_code": test,
        },
        messages=[
            {
                "role": "system",
                "content": "Complete the Python function below. Return only the indented function body as raw Python, with no Markdown, explanation, or repeated signature. Your response is appended directly to the code prefix.",
            },
            {"role": "user", "content": prefix},
        ],
    )


def build():
    suite = json.loads(OUT.read_text())
    suite["prompts"] = [p for p in suite["prompts"] if p["stable_id"] in RETAIN]
    assert len(suite["prompts"]) == 30
    suite["prompts"].extend(execution_prompt(t) for t in TASKS)
    assert len(suite["prompts"]) == 50
    for i, p in enumerate(suite["prompts"]):
        p["position"] = i
        for j, m in enumerate(p["messages"]):
            m["position"] = j
    suite["version"] = "5.0.0"
    suite["description"] = (
        "A compact 50-question Python test: 30 output-reasoning items covering mutation, scoping, iterators, exceptions and the data model, plus 20 original function-completion tasks inspired by HumanEval's executable-contract format. Practical tasks cover scheduling, configuration, logs, caching, pagination and data processing. Execution tests check edge cases and non-mutation. New difficulty weights are predicted, not model-calibrated. Python 3.10+; no third-party packages or network required."
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
        print("Python suite is up to date (50 questions)")
    else:
        OUT.write_text(rendered)
        print("Wrote Python suite (50 questions)")
