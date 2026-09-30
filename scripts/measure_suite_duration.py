"""Sequential duration diagnostics using the app's client and real graders.

Reports are resumable and retain answers/reasoning locally. The observation
ceiling bounds this diagnostic only; it does not change application settings.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.graders.deterministic import run_deterministic  # noqa: E402
from app.graders.execution import run_execution  # noqa: E402
from app.services.openai_client import chat_completion  # noqa: E402
from app.services.tool_compatibility import requires_text_tool_calls  # noqa: E402


def grade_attempt(prompt: dict, result) -> dict:
    if result.error or result.truncated or result.finish_reason == "length":
        return {"score": 0.0, "passed": False, "error": result.error or "Token limit exhausted"}
    if prompt["grading_mode"] == "execution":
        return run_execution(prompt["grader_config"], result.content, prompt["messages"][-1]["content"])
    if prompt["grading_mode"] == "deterministic":
        return run_deterministic(prompt["grader_config"], result.content)
    raise ValueError("Duration diagnostics support deterministic/execution suites only")


def save(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(path)


def summarize(report: dict) -> dict:
    records = report["records"]
    durations = [r["elapsed_seconds"] for r in records.values()]
    prompts = {p["stable_id"]: p for p in report["suite_snapshot"]["prompts"]}
    weight = sum(prompts[sid].get("importance_weight", 1) for sid in records)
    earned = sum(
        prompts[sid].get("importance_weight", 1) * r["grade"].get("score", 0) for sid, r in records.items()
    )
    return {
        "recorded_questions": len(records),
        "normal_finishes": sum(r["finish_reason"] == "stop" and not r.get("error") for r in records.values()),
        "token_exhaustions": sum(r["finish_reason"] == "length" for r in records.values()),
        "observation_ceilings": sum(r["finish_reason"] == "observation_ceiling" for r in records.values()),
        "transport_or_answer_errors": sum(
            bool(r.get("error")) and r["finish_reason"] != "observation_ceiling" for r in records.values()
        ),
        "grader_passes": sum(bool(r["grade"].get("passed")) for r in records.values()),
        "weighted_quality": round(earned / weight, 2) if weight else None,
        "request_seconds": round(sum(durations), 3),
        "grading_seconds": round(sum(r.get("grader_seconds", 0) for r in records.values()), 3),
        "median_request_seconds": round(statistics.median(durations), 3) if durations else None,
        "maximum_request_seconds": max(durations, default=None),
        "completion_tokens": sum(r["usage"].get("completion_tokens", 0) for r in records.values()),
        "prompt_tokens": sum(r["usage"].get("prompt_tokens", 0) for r in records.values()),
    }


async def measure(args) -> None:
    suite_path = ROOT / "backend/app/seed/suites" / f"{args.suite}.json"
    source = suite_path.read_bytes()
    suite = json.loads(source)
    config = {
        "base_url": args.base_url.rstrip("/"),
        "model": args.model,
        "max_tokens": args.max_tokens,
        "reasoning_effort": args.reasoning_effort,
        "inactivity_timeout": args.inactivity_timeout,
        "observation_ceiling": args.observation_ceiling,
        "temperature": 0.0,
        "top_p": 1.0,
        "stream": True,
        "max_retries": 0,
    }
    prompts = [p for p in suite["prompts"] if p.get("enabled", True)]
    if any(
        p["grading_mode"] not in {"deterministic", "execution"} or requires_text_tool_calls(p)
        for p in prompts
    ):
        raise ValueError(
            "Choose a deterministic/execution suite; Hermes transport adaptation is not implemented here"
        )
    digest = hashlib.sha256(source).hexdigest()
    out = Path(args.out)
    if out.exists():
        if not args.resume:
            raise ValueError("Output already exists; use --resume or a new output file")
        report = json.loads(out.read_text())
        if report["config"] != config or report["suite_sha256"] != digest:
            raise ValueError("Cannot resume with changed settings or suite; choose a new output file")
    else:
        report = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "config": config,
            "suite_sha256": digest,
            "suite_snapshot": suite,
            "records": {},
            "sessions": [],
        }
    wanted = set(args.ids or [p["stable_id"] for p in prompts])
    unknown = wanted - {p["stable_id"] for p in prompts}
    if unknown:
        raise ValueError(f"Unknown prompt IDs: {sorted(unknown)}")
    pending = [p for p in prompts if p["stable_id"] in wanted and p["stable_id"] not in report["records"]]
    pending = pending[: args.max_requests]
    session = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "requested_ids": [p["stable_id"] for p in pending],
    }
    report["sessions"].append(session)
    save(out, report)
    started = time.monotonic()
    for prompt in pending:
        sid = prompt["stable_id"]
        request_start = time.monotonic()
        last_notice = request_start
        print(f"START {sid}", flush=True)

        async def progress(fields, prompt_id=sid, started_at=request_start):
            nonlocal last_notice
            now = time.monotonic()
            if now - last_notice >= 20:
                print(
                    f"  {prompt_id}: {now - started_at:.0f}s; answer={fields.get('answer_chars', 0)} chars; "
                    f"reasoning={fields.get('reasoning_chars', 0)} chars",
                    flush=True,
                )
                last_notice = now

        extra = (
            {}
            if args.reasoning_effort == "default"
            else {"chat_template_kwargs": {"reasoning_effort": args.reasoning_effort}}
        )
        try:
            result = await asyncio.wait_for(
                chat_completion(
                    args.base_url,
                    api_key=None,
                    model=args.model,
                    messages=[{"role": m["role"], "content": m["content"]} for m in prompt["messages"]],
                    temperature=0.0,
                    top_p=1.0,
                    max_tokens=args.max_tokens,
                    extra_body=extra,
                    stream=True,
                    timeout=args.inactivity_timeout,
                    max_retries=0,
                    on_progress=progress,
                ),
                timeout=args.observation_ceiling,
            )
            elapsed = time.monotonic() - request_start
            grading_start = time.monotonic()
            grade = await asyncio.to_thread(grade_attempt, prompt, result)
            record = {
                "title": prompt["title"],
                "elapsed_seconds": round(elapsed, 3),
                "grader_seconds": round(time.monotonic() - grading_start, 3),
                "finish_reason": result.finish_reason,
                "truncated": result.truncated,
                "error": result.error,
                "usage": result.usage,
                "time_to_first_token": result.time_to_first_token,
                "content": result.content,
                "reasoning": result.reasoning,
                "grade": grade,
            }
        except TimeoutError:
            record = {
                "title": prompt["title"],
                "elapsed_seconds": round(time.monotonic() - request_start, 3),
                "finish_reason": "observation_ceiling",
                "error": "Diagnostic observation ceiling reached",
                "usage": {},
                "grade": {"score": 0, "passed": False},
                "content": "",
                "reasoning": "",
            }
        report["records"][sid] = record
        report["summary"] = summarize(report)
        session["elapsed_seconds"] = round(time.monotonic() - started, 3)
        save(out, report)
        print(
            f"END {sid}: {record['elapsed_seconds']}s; {record['finish_reason']}; "
            f"tokens={record['usage'].get('completion_tokens')}; score={record['grade'].get('score')}",
            flush=True,
        )
        if record["finish_reason"] in {"observation_ceiling", "length"} or record.get("error"):
            print(
                "Stopping sample after incomplete/errored request; investigate before more calls.", flush=True
            )
            break
    session["elapsed_seconds"] = round(time.monotonic() - started, 3)
    session["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["summary"] = summarize(report)
    save(out, report)
    print(f"Recorded {len(report['records'])}/{len(prompts)} questions in {out}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--suite", default="code_reasoning_python")
    parser.add_argument("--out", required=True)
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-requests", type=int, default=45)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument(
        "--reasoning-effort", choices=["default", "low", "medium", "high", "xhigh"], default="default"
    )
    parser.add_argument("--inactivity-timeout", type=float, default=60)
    parser.add_argument("--observation-ceiling", type=float, default=180)
    args = parser.parse_args()
    if (
        args.max_requests < 1
        or args.max_tokens < 1
        or args.inactivity_timeout <= 0
        or args.observation_ceiling <= 0
    ):
        parser.error("Request counts, token caps and timeouts must be positive")
    try:
        asyncio.run(measure(args))
    except KeyboardInterrupt:
        print("Interrupted; completed records were preserved. No further requests submitted.", flush=True)
