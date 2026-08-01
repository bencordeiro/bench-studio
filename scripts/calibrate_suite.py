"""Measure which benchmark items actually separate models, and re-weight them.

Why this exists
---------------
Guessed difficulty is unreliable. When these suites were built, several items
labelled "hard" were passed first try by a small model, while event-loop
ordering -- which looked routine -- failed at every difficulty tier attempted.
Weight belongs on items that are *observed* to discriminate.

A benchmark is only informative over the range where models actually differ.
If most items pass, every model lands in the high 80s and the ranking is noise.

Usage
-----
    # Record how one model does on every bundled item
    python scripts/calibrate_suite.py measure \\
        --base-url http://192.0.2.10:8000/v1 --model qwen35b \\
        --api-key KEY --out calib-qwen35b.json

    # ...repeat for a stronger model...
    python scripts/calibrate_suite.py measure \\
        --base-url http://192.0.2.10:8000/v1 --model minimax-m3 \\
        --api-key KEY --out calib-m3.json

    # Compare: which items separate the two, and what should be re-weighted
    python scripts/calibrate_suite.py compare calib-qwen35b.json calib-m3.json

    # Apply the recommendation to the suite JSON files
    python scripts/calibrate_suite.py compare calib-qwen35b.json calib-m3.json --apply

Two models are far more informative than one. With a single model you only
learn what it fails; with two you learn which items lie *between* them, and
those are the ones that carry ranking information.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.graders.deterministic import run_deterministic  # noqa: E402

SUITES_DIR = BACKEND / "app" / "seed" / "suites"

DISCRIMINATOR_WEIGHT = 4.0
ANCHOR_WEIGHT = 1.5
CEILING_WEIGHT = 1.0  # items every model passes: keep, but stop them dominating


def load_prompts(suite_filter: str | None = None) -> list[tuple[str, dict]]:
    """Every bundled prompt, or only those from suites matching ``suite_filter``.

    The filter is a substring of the file name. Sweeping all five suites is a
    long round trip against a local model, and a calibration usually targets one
    suite at a time.
    """
    out = []
    for path in sorted(SUITES_DIR.glob("*.json")):
        if suite_filter and suite_filter not in path.name:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for prompt in data["prompts"]:
            out.append((path.name, prompt))
    if not out:
        raise SystemExit(
            f"no prompts matched --suite {suite_filter!r}; available: "
            + ", ".join(p.name for p in sorted(SUITES_DIR.glob("*.json")))
        )
    return out


def ask(base_url: str, api_key: str | None, model: str, messages: list[dict],
        max_tokens: int, timeout: float) -> str:
    body = json.dumps({
        "model": model, "messages": messages, "stream": False,
        "temperature": 0.0, "max_tokens": max_tokens,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def cmd_measure(args: argparse.Namespace) -> int:
    prompts = load_prompts(getattr(args, "suite", None))
    print(f"measuring {len(prompts)} prompts against {args.model}", file=sys.stderr)

    def one(pair):
        suite, prompt = pair
        messages = [{"role": m["role"], "content": m["content"]} for m in prompt["messages"]]
        try:
            reply = ask(args.base_url, args.api_key, args.model, messages,
                        args.max_tokens, args.timeout)
        except Exception as exc:  # network/timeout: record, do not crash the sweep
            return prompt["stable_id"], {"score": None, "error": str(exc)[:200], "suite": suite}
        result = run_deterministic(prompt["grader_config"], reply)
        return prompt["stable_id"], {
            "score": result["score"], "suite": suite,
            "weight": prompt["importance_weight"],
            "final_line": next(
                (l for l in reversed(reply.strip().splitlines()) if l.strip()), "")[:160],
        }

    scores: dict[str, dict] = {}
    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        for sid, rec in ex.map(one, prompts):
            scores[sid] = rec
            mark = "?" if rec["score"] is None else ("PASS" if rec["score"] == 100 else "fail")
            print(f"  {mark:5} {sid}", file=sys.stderr)

    Path(args.out).write_text(
        json.dumps({"model": args.model, "scores": scores}, indent=2), encoding="utf-8")
    ok = [r for r in scores.values() if r["score"] == 100]
    print(f"\n{len(ok)}/{len(scores)} passed ({len(ok)/len(scores)*100:.0f}%) -> {args.out}",
          file=sys.stderr)
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    runs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.files]
    names = [r["model"] for r in runs]
    all_ids = sorted({sid for r in runs for sid in r["scores"]})

    separating, everyone_passes, everyone_fails = [], [], []
    for sid in all_ids:
        vals = [r["scores"].get(sid, {}).get("score") for r in runs]
        if any(v is None for v in vals):
            continue
        passed = [v == 100 for v in vals]
        if all(passed):
            everyone_passes.append(sid)
        elif not any(passed):
            everyone_fails.append(sid)
        else:
            separating.append(sid)

    print(f"models compared: {', '.join(names)}\n")
    print(f"  separating      : {len(separating):3}  <- these carry the ranking")
    print(f"  everyone passes : {len(everyone_passes):3}  <- ceiling, no information")
    print(f"  everyone fails  : {len(everyone_fails):3}  <- floor, may be too hard or broken")

    if len(runs) == 1:
        print("\nOnly one model supplied. Items it fails are candidates, but you cannot "
              "tell a discriminating item from an impossible one without a second model.")

    if separating:
        print("\nseparating items:")
        for sid in separating:
            marks = " ".join(
                f"{n}={'P' if r['scores'][sid]['score'] == 100 else 'F'}"
                for n, r in zip(names, runs))
            print(f"  {sid:34} {marks}")
    if everyone_fails:
        print("\nfailed by every model (check these are solvable, not broken):")
        for sid in everyone_fails:
            print(f"  {sid}")

    if not args.apply:
        print("\n(re-run with --apply to write the recommended weights)")
        return 0

    plan = ({sid: DISCRIMINATOR_WEIGHT for sid in separating}
            | {sid: CEILING_WEIGHT for sid in everyone_passes}
            | {sid: ANCHOR_WEIGHT for sid in everyone_fails})
    changed = 0
    for path in sorted(SUITES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        touched = False
        for prompt in data["prompts"]:
            new = plan.get(prompt["stable_id"])
            if new is None:
                continue
            # An item whose measurement happens to match its predicted weight is
            # still measured. Skipping it here left it tagged "unmeasured"
            # forever, which is the one thing that tag must never say wrongly.
            if prompt["importance_weight"] == new and "unmeasured" not in prompt.get("tags", []):
                continue
            prompt["importance_weight"] = new
            tags = [t for t in prompt.get("tags", [])
                    if t not in ("discriminator", "anchor", "unmeasured")]
            prompt["tags"] = tags + (
                ["discriminator"] if new >= DISCRIMINATOR_WEIGHT else ["anchor"])
            # Re-label difficulty from the measurement too. Leaving the authored
            # label alone lets a "medium" item that turned out to discriminate
            # outweigh a "hard" one that everybody passes, which is exactly what
            # test_declared_difficulty_matches_weight_ordering forbids -- so
            # applying a calibration would leave the suite failing its own tests.
            # The label now means what the weight means: observed difficulty.
            prompt["difficulty"] = "hard" if new >= DISCRIMINATOR_WEIGHT else "medium"
            touched = True
            changed += 1
        if touched:
            major = int(str(data["version"]).split(".")[0]) + 1
            data["version"] = f"{major}.0.0"
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
            print(f"  updated {path.name} -> v{data['version']}")
    print(f"\nre-weighted {changed} prompts. Re-run the backend tests before benchmarking.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("measure", help="score every bundled prompt against one model")
    m.add_argument("--base-url", required=True)
    m.add_argument("--model", required=True)
    m.add_argument("--api-key", default=None)
    m.add_argument("--out", required=True)
    m.add_argument("--max-tokens", type=int, default=16384)
    m.add_argument("--timeout", type=float, default=900.0)
    m.add_argument("--concurrency", type=int, default=4)
    m.add_argument("--suite", default=None,
                   help="only measure suites whose file name contains this "
                        "substring, e.g. --suite master")
    m.set_defaults(func=cmd_measure)

    c = sub.add_parser("compare", help="find which items separate two or more models")
    c.add_argument("files", nargs="+")
    c.add_argument("--apply", action="store_true", help="write recommended weights")
    c.set_defaults(func=cmd_compare)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
