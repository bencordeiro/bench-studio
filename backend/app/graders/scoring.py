"""Scoring: quality, reliability, performance index, composite.

All public functions are pure and tested in isolation.
"""
from __future__ import annotations

import statistics
from typing import Any

DEFAULT_COMPOSITE_WEIGHTS = {"quality": 0.85, "reliability": 0.10, "performance": 0.05}
QUALITY_SCORING_VERSION = 2

# Reliability factor weights (documented in SCORING.md).
RELIABILITY_WEIGHTS = {
    "completion": 0.30,   # request finished without erroring out
    "valid_response": 0.20,  # a non-empty body actually came back
    "structure": 0.15,    # delivered cleanly: no truncation, no retries needed
    "grade_parsed": 0.15, # grader produced a score without parse failure
    "no_truncation": 0.10,  # proportion of responses that were not cut off
    "consistency": 0.10,  # consistency across repetitions (1.0 when n=1)
}


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def category_quality_score(scores: list[tuple[float, float]]) -> float | None:
    """sum(prompt score * prompt weight) / sum(prompt weight).

    ``scores`` is a list of (score_0_100, weight). Returns None if no weight.
    """
    total_w = sum(w for _, w in scores)
    if total_w <= 0:
        return None
    earned = sum(s * w for s, w in scores)
    return clamp(earned / total_w)


def prompt_quality_score(prompt: dict[str, Any]) -> float | None:
    """A failed attempt is zero; an unfinished/ungraded task is still unknown."""
    if prompt.get("excluded", False):
        return None
    status = prompt.get("status")
    if status == "failed":
        return 0.0
    if status in {"completed", "awaiting_manual", "awaiting_judge"} and (
        prompt.get("truncated") or prompt.get("finish_reason") == "length"
    ):
        return 0.0
    if status in {"completed", "awaiting_manual"} and prompt.get("score") is not None:
        return float(prompt["score"])
    return None


def overall_quality_score(
    prompts: list[dict[str, Any]],
) -> tuple[float | None, int, int]:
    """Weighted overall quality across all auto-scored prompts.

    Each prompt dict must include: score (0..100 or None), weight (float),
    status (str). Failed/token-exhausted attempts count as zero with full weight.
    Pending and ungraded manual/judge prompts are excluded from the denominator.

    Returns (quality_score_or_None, scored_count, total_count).
    """
    scored = [
        (value, float(p.get("weight", 1.0)))
        for p in prompts
        if (value := prompt_quality_score(p)) is not None
    ]
    total = len(prompts)
    if not scored:
        return None, 0, total
    total_w = sum(w for _, w in scored)
    if total_w <= 0:
        return None, len(scored), total
    earned = sum(s * w for s, w in scored)
    return clamp(earned / total_w), len(scored), total


def reliability_score(factors: dict[str, float | None], repetitions: int = 1,
                      repetition_scores: list[float] | None = None) -> float:
    """0..100 reliability score from observed factors.

    Missing factors default to their weight * 0.5 (neutral). Consistency is
    computed from repetition_scores when repetitions > 1, else 1.0.
    """
    parts = 0.0
    for key, weight in RELIABILITY_WEIGHTS.items():
        if key == "consistency":
            continue
        val = factors.get(key)
        if val is None:
            val = 0.5
        # values may be bool or 0/1 or 0..1.
        if isinstance(val, bool):
            val = 1.0 if val else 0.0
        val = float(val)
        val = clamp(val, 0.0, 1.0)
        parts += val * weight
    # Consistency.
    cons_w = RELIABILITY_WEIGHTS["consistency"]
    if repetitions > 1 and repetition_scores and len(repetition_scores) >= 2:
        cons = consistency_score(repetition_scores)
    else:
        cons = 1.0
    parts += cons * cons_w
    return clamp(parts * 100.0)


def consistency_score(scores: list[float]) -> float:
    """0..1 consistency across repetitions based on coefficient of variation.

    CV = stdev/mean. Maps CV=0 -> 1.0 (perfectly consistent), CV>=0.25 -> 0.0.
    Documented in SCORING.md.
    """
    if len(scores) < 2:
        return 1.0
    mean = statistics.fmean(scores)
    if mean == 0:
        return 0.0
    stdev = statistics.pstdev(scores)
    cv = stdev / (abs(mean) + 1e-9)  # coefficient of variation
    return clamp(1.0 - cv / 0.25, 0.0, 1.0)


def performance_index(
    *,
    metrics: list[dict[str, float | None]],
    thresholds: dict[str, float],
) -> float:
    """0..100 performance index from user-configurable thresholds.

    thresholds keys:
      desired_ttft, max_ttft (seconds)
      desired_tps, min_tps (tokens/sec)
      max_failure_rate (0..1)
    """
    if not metrics:
        return 0.0
    # TTFT: lower is better. Score from desired..max -> 100..0.
    ttfts = [m.get("time_to_first_token") for m in metrics if m.get("time_to_first_token") is not None]
    tps_vals = [m.get("output_tokens_per_second") for m in metrics if m.get("output_tokens_per_second") is not None]
    failures = sum(1 for m in metrics if m.get("failed"))
    failure_rate = failures / len(metrics)

    desired_ttft = thresholds.get("desired_ttft", 0.5)
    max_ttft = thresholds.get("max_ttft", 5.0)
    desired_tps = thresholds.get("desired_tps", 40.0)
    min_tps = thresholds.get("min_tps", 5.0)
    max_failure_rate = thresholds.get("max_failure_rate", 0.1)

    # Components are scored only when measured. A component that was never
    # observed (e.g. TTFT on a non-streaming run) is dropped and its weight is
    # redistributed -- scoring it as zero would penalise a flawless run by 30
    # points for a metric the transport simply cannot report.
    components: list[tuple[float, float]] = []  # (score, weight)

    if ttfts:
        avg_ttft = statistics.fmean(ttfts)
        if avg_ttft <= desired_ttft:
            ttft_score = 100.0
        elif avg_ttft >= max_ttft:
            ttft_score = 0.0
        else:
            ttft_score = 100.0 * (max_ttft - avg_ttft) / (max_ttft - desired_ttft)
        components.append((ttft_score, 0.30))

    if tps_vals:
        avg_tps = statistics.fmean(tps_vals)
        if avg_tps >= desired_tps:
            tps_score = 100.0
        elif avg_tps <= min_tps:
            tps_score = 0.0
        else:
            tps_score = 100.0 * (avg_tps - min_tps) / (desired_tps - min_tps)
        components.append((tps_score, 0.40))

    # Failure rate is always measurable: 100 at 0 failures, 0 at >= max rate.
    if failure_rate <= 0:
        fail_score = 100.0
    elif failure_rate >= max_failure_rate:
        fail_score = 0.0
    else:
        fail_score = 100.0 * (1.0 - failure_rate / max_failure_rate)
    components.append((fail_score, 0.30))

    total_w = sum(w for _, w in components)
    if total_w <= 0:
        return 0.0
    return clamp(sum(s * w for s, w in components) / total_w)


def composite_score(
    *,
    quality: float | None,
    reliability: float | None,
    performance: float | None,
    weights: dict[str, float] | None = None,
) -> float | None:
    weights = weights or DEFAULT_COMPOSITE_WEIGHTS
    q_w = weights.get("quality", DEFAULT_COMPOSITE_WEIGHTS["quality"])
    r_w = weights.get("reliability", DEFAULT_COMPOSITE_WEIGHTS["reliability"])
    p_w = weights.get("performance", DEFAULT_COMPOSITE_WEIGHTS["performance"])
    total_w = q_w + r_w + p_w
    if total_w <= 0:
        return None
    parts = 0.0
    contributed = 0.0
    for val, w in ((quality, q_w), (reliability, r_w), (performance, p_w)):
        if val is None:
            continue
        parts += val * w
        contributed += w
    if contributed <= 0:
        return None
    return clamp(parts / contributed)


def repetition_stats(scores: list[float]) -> dict[str, float | None]:
    if not scores:
        return {"mean": None, "min": None, "max": None, "std": None, "consistency": None}
    if len(scores) == 1:
        return {"mean": scores[0], "min": scores[0], "max": scores[0], "std": 0.0,
                "consistency": 1.0}
    return {
        "mean": statistics.fmean(scores),
        "min": min(scores),
        "max": max(scores),
        "std": statistics.pstdev(scores),
        "consistency": consistency_score(scores),
    }


def hybrid_score(
    *,
    deterministic_fraction: float,
    judge_fraction: float,
    deterministic_weight: float,
    judge_weight: float,
) -> float:
    """Combine deterministic and judge fractions (each 0..1) by weights."""
    total_w = deterministic_weight + judge_weight
    if total_w <= 0:
        return 0.0
    det = clamp(deterministic_fraction, 0.0, 1.0)
    jud = clamp(judge_fraction, 0.0, 1.0)
    return clamp(100.0 * (det * deterministic_weight + jud * judge_weight) / total_w)


def apply_score_cap(score: float, cap: float | None) -> tuple[float, float | None]:
    """Apply a critical-error cap, returning (new_score, effective_cap)."""
    if cap is None:
        return score, None
    return min(score, cap), cap
