"""Rebuild Terminal, Web Dev and Agentic refreshes; retained questions live in JSON.

python3 scripts/build_refreshed_suites.py [--check]
New questions are defined in terminal_tasks, hardening_tasks and agentic_tasks.
"""
import argparse
import json
import subprocess
from pathlib import Path

from agentic_tasks import RETIRED_IDS, build_prompts
from hardening_tasks import RETIRED_WEB_IDS, WEB_TASKS
from terminal_tasks import prompts as terminal_prompts

ROOT = Path(__file__).resolve().parents[1]
SUITES = ROOT / "backend/app/seed/suites"


def load(name):
    return json.loads((SUITES / (name + ".json")).read_text())


def build():
    terminal = load("terminal_semantics")
    terminal["prompts"] = [p for p in terminal["prompts"] if not p["stable_id"].startswith("ts-tb-")]
    terminal["prompts"].extend(terminal_prompts())
    terminal["version"] = "3.0.0"
    terminal["description"] = (
        "15 terminal and systems questions: 12 explicit-environment reasoning items plus 3 functional "
        "adaptations of official Terminal-Bench 2.0 tasks (regex-log, cancel-async-tasks, log-summary-date-ranges). "
        "The adaptations use original fixtures and in-memory Python artifacts instead of container files; "
        "they are not official Terminal-Bench scores. "
        "No network or judge required. Implementation questions require Python 3.11+. Difficulty is unmeasured."
    )

    web = load("web_dev_js")
    web["prompts"] = [p for p in web["prompts"]
                      if p["stable_id"] not in RETIRED_WEB_IDS and not p["stable_id"].startswith("wd6-")]
    for sid, title, topic, code in WEB_TASKS:
        code = code.strip() + "\n"
        output = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True,
                                timeout=10).stdout.strip()
        assert output and len(output.splitlines()) == 1
        web["prompts"].append({
            "stable_id": "wd6-" + sid, "title": title, "description": "Original executable web-platform scenario: " + title,
            "category": "web-js/" + topic, "tags": ["web", "javascript", "original", "execution-verified", "unmeasured"],
            "difficulty": "hard", "importance_weight": 3.0, "enabled": True,
            "grading_mode": "deterministic", "generation_overrides": {"temperature": 0.0},
            "grader_config": {"type": "exact", "canonical_answer": output, "accepted_aliases": [],
                              "case_sensitive": True, "trim_whitespace": True, "normalize_punctuation": False, "points": 100.0},
            "messages": [{"role": "system", "content": "Determine the exact single console output line under Node.js 22+ with standard web APIs. Reply only ANSWER: <output>, with no explanation or Markdown. The program has no network access or external packages."},
                         {"role": "user", "content": code}],
        })
    web["version"] = "6.0.0"
    web["description"] = (
        "45 JavaScript correctness questions covering language semantics and original web-platform scenarios: "
        "URLSearchParams, response consumption/cloning, cancellation, "
        "thenable jobs, proxy receivers, transferred buffers, serialization, async cleanup, reentrant state "
        "and cache age. Every output is verified under Node.js; new tasks require Node.js 22+. No judge or network. "
        "New difficulty and weights are design estimates, not calibrated model results."
    )

    agentic = load("agentic_tool_use")
    agentic["prompts"] = [p for p in agentic["prompts"]
                          if p["stable_id"] not in RETIRED_IDS and not p["stable_id"].startswith("ag5-")]
    agentic["prompts"].extend(build_prompts())
    agentic["version"] = "5.0.0"
    agentic["description"] = (
        "15 Hermes/native function-calling questions covering tool selection, structured arguments and "
        "original fixed-history tasks: paginated revision joins, optimistic locking, "
        "partial outcomes, capped refunds, immutable ownership and artifact-dependent workflow frontiers. "
        "Grading checks next-action names, exact arguments and types, rejects extras, and supports native API histories. "
        "These are supplied-state decisions, not live multi-turn rollouts. Difficulty is unmeasured."
    )
    suites = {"terminal_semantics": terminal, "web_dev_js": web, "agentic_tool_use": agentic}
    for name, suite in suites.items():
        assert len(suite["prompts"]) == {"terminal_semantics": 15, "web_dev_js": 45, "agentic_tool_use": 15}[name]
        for i, prompt in enumerate(suite["prompts"]):
            prompt["position"] = i
            for j, message in enumerate(prompt["messages"]):
                message["position"] = j
    return suites


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, suite in build().items():
        path = SUITES / (name + ".json")
        rendered = json.dumps(suite, indent=2, ensure_ascii=True) + "\n"
        if args.check:
            if path.read_text() != rendered:
                raise SystemExit(name + " bundle is stale")
        else:
            path.write_text(rendered)
        print(f"{'Verified' if args.check else 'Wrote'} {name}: {len(suite['prompts'])} questions")
