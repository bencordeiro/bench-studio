# Qwen Flash Python duration validation — September 30, 2026

The revised **Code Reasoning & Correctness (Python) 7.0.0** contains 45
questions. All 45 completed normally in the authorized medium/8k diagnostic:
**about 10 minutes 38 seconds** of sequential test time, **34.10 seconds** for
the slowest question, and **no token exhaustion or endpoint errors**. The model
passed 43/45, for a weighted quality score of **91.01**.

No further question removals or easier replacements were needed. The earlier
five removals and compact output contracts remain in place. All 16 function
implementations passed the app's execution grader. The two incorrect output
traces finished quickly and were retained as useful benchmark failures.

## Method

Endpoint: `http://10.0.0.10:8000/v1`; discovered alias: `qwenflash`. Actual model
revision, parameter count and hardware were not independently verified.
Requests used the app's streaming chat client, temperature 0, top-p 1, maximum
completion tokens **8,192**, a 60-second **inactivity** timeout, and zero retries.
Reasoning effort was sent through `chat_template_kwargs.reasoning_effort`, the
same field used by the app.

Six medium prompts formed the pilot; the remaining 39 were then measured with
identical settings, skipping the six saved records. Each request was sequential
and independent. Thus the reported duration is the sum of two diagnostic
sessions, excluding the idle gap between them, rather than a single app-history
run. Sum of request durations was 636.926 seconds; grading added 0.534 seconds;
total recorded session wall time was 637.570 seconds. No warm-up or judge ran.

A 300-second observation ceiling bounded each diagnostic request. **None
reached it**, so that ceiling did not affect the measured answers or timings.
It is not a new app timeout. Global settings and suite weights were unchanged.
Correctness used the real deterministic or execution grader; reasoning stayed
separate from the graded final answer. Failed generation/token exhaustion would
have counted as zero with full question weight, rather than being omitted.

A preliminary server-default/4,096-token sample completed two trace questions
before the user supplied medium/xhigh and the 8k limit. A third preliminary
request was cancelled when switching profiles. These preliminary requests are
excluded from the 45-question medium statistics.

## Full medium/8k results

| Metric | Observed result |
|---|---:|
| Questions | 45 |
| Normal `stop` finishes | 45 |
| Token-limit finishes | 0 |
| Transport/empty-answer errors | 0 |
| Observation ceilings | 0 |
| Grader passes | 43 |
| Function-task passes | 16/16 |
| Weighted quality | 91.01 |
| Sequential diagnostic wall time | 637.570 s (~10m 38s) |
| Median request | 12.688 s |
| Maximum request | 34.097 s |
| Reported completion tokens | 20,527 |
| Maximum completion tokens for one question | 1,157 |
| Reported prompt tokens | 6,565 |

The 8k cap did not make this run fast by cutting answers short: every response
finished normally, and even the largest used only 1,157 reported completion
tokens. Token figures are the endpoint's total completion usage; it did not
provide a separate reasoning-token breakdown.

| Slowest question | Time | Completion tokens |
|---|---:|---:|
| Match a URL path against named route segments | 34.097 s | 1,157 |
| Compute event-time rolling totals at exact boundaries | 33.349 s | 1,061 |
| Find a longest run of consecutive observed days | 27.429 s | 874 |
| Compress missing IDs into inclusive ranges | 24.068 s | 833 |
| Group and aggregate in one pass | 22.030 s | 818 |
| Simulate a bounded LRU cache | 20.529 s | 633 |

## Incorrect answers are not stalled generations

- `cr-zip-strict-uneven`: returned remaining iterator values `[3, 4, 5]`
  instead of `[4, 5]`, overlooking the extra value consumed while discovering
  that the second iterable is exhausted. Finished in 9.598 seconds.
- `cr3-reflected-operator`: returned `A.add` for the first addition instead of
  `B.radd`, overlooking reflected-operator priority for a right-hand subclass.
  Finished in 9.516 seconds.

The canonical outputs were already reproduced with CPython during local
validation. Both questions have short deterministic answer contracts and are
retained; failing them does not indicate a duration or grading defect.

## xhigh/8k follow-up

The first six questions covered the four slowest function tasks above and the
two incorrect medium traces. The resumed pass completed 12 additional traces
before the user requested that testing stop and the rest be extrapolated. The
in-flight 19th xhigh request was cancelled; no further endpoint calls followed.

All **18 completed xhigh/8k responses** finished normally, without token caps,
transport errors or observation ceilings. The maximum was **56.461 seconds**
for `match_route`, using **1,924 completion tokens**. Seventeen answers passed;
`zip` remained incorrect, while reflected-operator priority was corrected.
This selected subset is not an overall xhigh score or full-suite duration.

| Slow function | Medium observed | Xhigh observed | Planning allowance (2× medium) |
|---|---:|---:|---:|
| `match_route` | 34.097 s | 56.461 s | 68.194 s |
| `rolling_totals` | 33.349 s | 23.084 s | 66.698 s |
| `longest_streak` | 27.429 s | 29.401 s | 54.858 s |
| `missing_ranges` | 24.068 s | 19.516 s | 48.136 s |

Using the user's **2× duration assumption** across the entire medium baseline,
the conservative planning estimate is **1,275.14 seconds (~21m 15s)** for all
45 xhigh questions. Budget roughly **20–25 minutes**, with the slowest question
around **one minute eight seconds** under that assumption. This is an educated
estimate, not an observed upper bound: hardware/load and individual reasoning
traces can vary. The completed xhigh sample shows no evidence of runaway
questions, and no further removals or repairs are indicated by these results.

## Reproduction and saved observations

The resumable harness is `scripts/measure_suite_duration.py`:

```bash
backend/.venv/bin/python scripts/measure_suite_duration.py \
  --base-url http://10.0.0.10:8000/v1 --model qwenflash \
  --suite code_reasoning_python --reasoning-effort medium \
  --max-tokens 8192 --observation-ceiling 300 \
  --out data/calibration/python-medium.json
```

`--ids` selects a small sample; `--resume` skips completed questions and rejects
changed settings or suite contents. It stops after an incomplete/errored
request rather than burning more calls. A report includes the exact suite
snapshot, requested settings, timing, usage, answer, reasoning, grade and summary.
No benchmark database is modified. Only deterministic/execution suites without
Hermes tool-call transport are supported by this diagnostic harness.

Raw reports are retained locally in the ignored directory
`data/calibration/qwenflash-python-2026-09-30/`. They are not committed:
`medium-8192.json`, `xhigh-8192-sample.json`, and the preliminary
`default-4096.json`. Tested suite SHA-256:
`40315e0f2cfa27de303e373ec7f5e70456ab7dfc7fad8d1f0d3b5e3ffa9c6960`.

This confirms practical duration on this endpoint under the measured profile;
it is not cross-model difficulty calibration or a guarantee at 16k tokens,
server-default settings, different hardware, or different endpoint load. No
full-suite xhigh or 16k-token run was completed. Further testing was stopped
at the user's request.
