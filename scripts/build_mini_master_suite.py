"""Build the standalone 25-question sampler from seven current source suites."""
import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITES = ROOT / "backend/app/seed/suites"
OUT = SUITES / "mini_master.json"

# Curated for compositional reasoning and useful edge cases, not measured pass
# rates. Source IDs/versions are retained in tags for exact provenance.
SELECTION = {
    "cyber": ["cy2-iam-intersection", "cy2-jwt-binding", "cy2-gcm-reservation", "cy2-pid-reuse"],
    "terminal_semantics": ["ts-perm-mask", "ts-tb-regex-log", "ts-tb-cancel-async-tasks", "ts-tb-log-summary-date-ranges"],
    "code_reasoning_python": ["cr8-generator-delegation-unwind", "cr3-reflected-operator", "cr-fn-rolling-totals", "cr-fn-flatten-records"],
    "web_dev_js": ["wd6-thenable-jobs", "wd6-proxy-receiver", "wd6-response-clone", "wd6-store-reentrancy"],
    "agentic_tool_use": ["ag5-paginated-join", "ag5-versioned-patch", "ag5-partial-outcomes", "ag5-artifact-frontier"],
    "instruction_following": ["if-lipogram-bounded", "if-bullets-keyword-end", "if-conditional-redaction"],
    "humaneval": ["HumanEval/132", "HumanEval/147"],
}


def build():
    prompts = []
    for source, ids in SELECTION.items():
        suite = json.loads((SUITES / (source + ".json")).read_text())
        by_id = {p["stable_id"]: p for p in suite["prompts"]}
        for sid in ids:
            prompt = copy.deepcopy(by_id[sid])
            prompt["stable_id"] = "mm3-" + sid.replace("/", "-")
            prompt["position"] = len(prompts)
            prompt["description"] = f"Selected from {suite['name']} v{suite['version']}: " + prompt["description"]
            prompt["tags"] = [*prompt["tags"], "mini-master", f"source-suite:{source}",
                              f"source-id:{sid}", f"source-version:{suite['version']}"]
            # Mini Master is a sampler, not another weighting of its sources.
            # Preserve question content and grader; each selected item contributes equally.
            prompt["importance_weight"] = 3.0
            prompts.append(prompt)
    assert len(prompts) == 25
    return {
        "format": "localbench-benchmark", "format_version": "1.0", "exported_at": "",
        "name": "Mini Master", "version": "3.0.0",
        "description": "Standalone 25-question sampler: four selected questions each from Cyber, Terminal, Python, Web Dev and Agentic; three Instruction Following and two HumanEval problems. Uses unchanged source prompts and graders with equal item weights. Independent of the six-suite default Index. Selection difficulty is a design estimate; duration and pass rates are unmeasured. Includes execution grading; terminal implementations require Python 3.11+.",
        "tags": ["mini-master", "standalone", "curated", "hermes", "execution"], "scoring_config": {},
        "performance_thresholds": {"desired_ttft": 1.0, "max_ttft": 15.0, "desired_tps": 25.0,
                                   "min_tps": 3.0, "max_failure_rate": 0.1},
        "composite_weights": {"quality": 0.85, "reliability": 0.1, "performance": 0.05}, "prompts": prompts,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(build(), indent=2, ensure_ascii=True) + "\n"
    if args.check:
        if OUT.read_text() != rendered:
            raise SystemExit("Mini Master bundle is stale")
    else:
        OUT.write_text(rendered)
    print("Verified Mini Master (25 questions)" if args.check else "Wrote Mini Master (25 questions)")
