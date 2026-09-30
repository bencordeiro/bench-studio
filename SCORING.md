# Scoring

This document explains exactly how LocalBench Studio computes every score. All formulas are also visible in the application UI. They apply uniformly to all bundled suites — including **Terminal Semantics & System Gotchas** — and to any custom benchmark you author.

## Prompt scores

Every automatically graded prompt receives a **0–100** score.

- **Deterministic** — each check produces `score`/`max_score`; the prompt's normalized score is the average of `(score / max_score)` across all its checks, × 100.
- **LLM Judge** — the judge's `final_score` (0–100), already reflecting any score cap it applied.
- **Hybrid** — `100 × (det_fraction × det_weight + judge_fraction × judge_weight) / (det_weight + judge_weight)`, where each fraction is 0–1. Weights must total 100%. Critical deterministic failures may cap the result (e.g. "invalid JSON caps at 40").
- **Execution** — the model's code completion is executed against the problem's unit tests (HumanEval reference-harness semantics, 3-second timeout, no partial credit): **100** if every test passes, **0** otherwise (passed / timed out / failed).
- **Manual** — no automatic score. Shown as "Awaiting manual review," **not** zero.

## Quality Score

Weighted across prompts by each prompt's `importance_weight`:

```
Overall Quality = Σ(prompt_score × prompt_weight) / Σ(prompt_weight)
```

over all **concluded prompt attempts**, including failures. Failed generations and token-limit exhaustion are **zero scores with full question weight**; they cannot disappear from the denominator and inflate a model's result. Token-limit exhaustion is a failed attempt even if a partial answer was retained. Pending tasks and ungraded manual/judge answers remain **excluded from the denominator** until scored. The UI shows coverage, e.g. `18 of 22 prompts`, with failures included as evaluated zero scores.

Scoring revision 2 automatically corrects saved run summaries and failed/exhausted attempt scores when the backend starts. It uses existing responses, finish reasons, metrics and question weights; it makes no model requests. Historical prompt snapshots and retained answers/reasoning are preserved. Corrected quality, category, repetition and composite scores propagate to history, comparisons, leaderboards and exports. Stored completed summaries without any execution data are preserved because there is nothing to recalculate.

Category scores use the same weighted formula scoped to prompts in a category.

**Execution suites are weighted uniformly, on purpose.** The HumanEval suite gives every problem the same weight, so its Quality score is exactly the unweighted pass rate — standard **pass@1** — and stays directly comparable to published HumanEval numbers. Re-weighting a canonical benchmark would drift the headline from the number the literature reports.

### Choosing `importance_weight` — calibrate, don't guess

A benchmark is only useful over the range where it separates models. If most items pass, every model scores in the high 80s and the ranking is noise.

Guessed difficulty is unreliable. When the bundled suites were calibrated against a real model, several items labelled "hard" were passed first try, while event-loop ordering — which looked routine — failed at every difficulty tier attempted. Weight is therefore assigned from **measured** results:

| Observed against a reference model | Weight | Role |
|---|---|---|
| Failed | 3.0 | Discriminator — carries the score |
| Passed | 1.5 | Anchor — still catches a weaker model |

This also fixes score compression arithmetically. With ~30% of items failing at double weight, a model at that capability lands near 50 rather than 85, leaving room above it — without stuffing the suite with obscure trivia, which would narrow what it measures rather than deepen it.

Two cautions learned from doing this:

- **Re-measure after editing an item.** A weight derived from an older version of the snippet is a guess again.
- **Separate reasoning failures from transcription failures.** Two items were initially recorded as discriminators when the model had traced them correctly and then written `[1, 2, 3, 4, 5 6` — a dropped bracket. Weighting those rewards typing accuracy. Prefer items whose answer is a short scalar so depth stays in the reasoning, and check the actual response before trusting a zero.

## Reliability Score

A 0–100 composite from six factors:

| Factor | Weight | Meaning |
|--------|--------|---------|
| completion | 0.30 | fraction of prompts whose request finished without erroring |
| valid_response | 0.20 | fraction that returned a non-empty body |
| structure | 0.15 | fraction delivered cleanly — not truncated, and needing no retry |
| grade_parsed | 0.15 | fraction where the grader produced a score without parse failure |
| no_truncation | 0.10 | fraction of responses that were not cut off by the token limit |
| consistency | 0.10 | consistency across repetitions (1.0 when repetitions = 1) |

Each factor is in 0–1. Consistency is `1 − CV/0.25` clamped to 0–1, where `CV = pstdev(scores)/mean(scores)`. Missing factors default to 0.5 (neutral). The weighted sum is multiplied by 100.

Every factor must measure something the others do not. An earlier version computed `structure` with the same expression as `completion`, which quietly gave completion 0.45 of the total weight and let a run full of truncated answers score as if it were clean.

## Performance Index

A 0–100 index from **user-configurable thresholds** (per benchmark), so scores stay stable when new models are added — they are not normalized against other tested models.

| Component | Mapping |
|-----------|---------|
| Time to first token (TTFT) | 100 at ≤ `desired_ttft`, 0 at ≥ `max_ttft`, linear between |
| Output tokens/sec | 100 at ≥ `desired_tps`, 0 at ≤ `min_tps`, linear between |
| Failure rate | 100 at 0 failures, 0 at ≥ `max_failure_rate`, linear between |

Final index = `0.30 × ttft_score + 0.40 × tps_score + 0.30 × failure_score`. Performance is **kept separate from quality** by default.

**Unmeasurable components are dropped, not zeroed.** A non-streaming run cannot report TTFT, so its 0.30 weight is redistributed across the remaining components rather than scored as 0 — otherwise a flawless non-streaming run would be capped at 70 for a metric the transport simply cannot produce.

Latency is measured **per attempt**. When a request is retried, the failed attempts and the backoff sleep between them are excluded from TTFT and total response time (they remain available as `wall_time`), so a transient server hiccup never makes the model look slower than it is.

## Composite Score (optional)

A user-configurable utility score, **not** a universal intelligence score:

```
Composite = (quality×Q + reliability×R + performance×P) / (Q + R + P)
```

Default weights: **Quality 85% / Reliability 10% / Performance 5%**. Missing components are excluded (their weight is dropped from the denominator). Adjust weights on the Settings page; they must total 100%.

## Repetitions

When `repetitions > 1`, each prompt runs N times and the UI shows **mean / min / max / std / consistency**. Consistency feeds the reliability score as described above.
