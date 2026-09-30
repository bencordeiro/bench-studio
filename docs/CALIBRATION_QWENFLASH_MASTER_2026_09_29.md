# Qwen Flash Master duration investigation — 2026-09-29

The requested target is 15–30 minutes for a complete Master run, while retaining
difficult questions. The 50-question Master 4.1.0 baseline took approximately
25 minutes 46 seconds to complete its requests, but 15 responses exhausted
their token budget. This is not evidence of 50 completed final answers. Master
5.0.0 now contains 45 questions; its full duration has **not** been measured.
The user stopped endpoint testing to conserve tokens. No further model calls
were made after cancellation. Cyber was reviewed and tested entirely offline.

## Method and observations

Endpoint: `http://10.0.0.10:8000/v1`, model alias `qwenflash`. Actual model
revision, parameter count, hardware and serving configuration were not verified.
Requests used the app's chat client, native function calls for tool items and
the existing deterministic graders. They were sequential, streaming, temperature
0, top-p 1, reasoning effort `low`, maximum completion tokens 2,048, inactivity
timeout 60 seconds, and zero retries. A temporary observation ceiling of 75
seconds per request bounded the diagnostic session; no request reached it.
Neither that ceiling nor the token/effort profile changed app defaults or saved
global settings. This is a duration pilot on one model, not difficulty calibration.

| Observation | Result |
|---|---:|
| Baseline requests | 50 |
| Sum of recorded request times | 1,545.79 seconds |
| Normal `stop` / `tool_calls` finishes | 35 |
| `length` finishes (budget exhausted) | 15 |
| Grader passes | 22 |
| Completed answers failing grading | 13 |
| Transport failures / observation ceilings | 0 / 0 |
| Reported completion tokens | 59,835 |

The traces show two practical causes: lengthy hand calculations/state traces,
and rechecking an answer already found before publishing it. Some responses also
spent their remaining budget on an explanation preceding the answer. Incorrect
completed code answers are normal benchmark failures and were retained. All six
tool-use items passed; server-side tool parsing was not the cause of this sweep's
slow questions. Keep reasoning separate from the graded final answer.

Local raw observations, including prompt snapshots, reasoning and grades, remain
in the ignored directory `data/calibration/qwenflash-master-2026-09-29/`:
`low-2048.json` and `concise-2048.json`. They are not published with the repository.

## Changes and their limits

Five budget-exhausting manual workloads were removed. Selection combines the
observed traces with editorial judgment about redundant work; these are not a
statistical ranking of the five slowest questions.

| Retired stable ID | Reason |
|---|---|
| `ms-math-multiplicative-order` | Repeated modular arithmetic across prime powers; unfinished calculation |
| `ms-math-lcm-matrix-determinant` | Lengthy manual elimination; unfinished calculation |
| `ms-cs-natural-mergesort` | Repeated merge passes with substantial state transcription |
| `ms-cs-dynamic-array-copies` | Long operation-by-operation growth/shrink accounting |
| `ms-abs-false-output-claim` | Extended binary floating-point tracing to refute a planted claim |

The remaining 45 items keep their answer keys, graders and weights. Numeric
prompts require exactly one `ANSWER:` line and ask the model to submit one
derivation rather than explore alternatives after reaching a result. Existing
relative tolerances are now visible in the prompt, so a model need not chase
precision the grader never required. Vector-clock and transaction answers also
request one line; abstention prompts ask for a brief response. The 18 code-output
prompts retain their previously shortened contract.

Two completed trials isolated the numeric answer-only/single-derivation wording
at the same diagnostic settings:

| Question | Original response | Revised trial |
|---|---|---|
| Multiset arrangements | Token cap after 50.66 s | Correct final answer in 34.22 s; 1,452 tokens |
| Second coin posterior | Token cap after 44.84 s | Correct final answer in 37.46 s; 1,822 tokens |

A third trial was interrupted when the user stopped testing; it has no completed
result. No further candidate or revised full-suite run was submitted. These two
successes support the prompt repair but cannot establish a 45-question completion
rate or duration. Some retained questions had capped baseline responses, so
remaining truncation risk is unresolved without additional authorized measurement.

Global settings still control token limits. Reasoning tokens consume the
provider's completion budget on this endpoint. Zero means server default, not
a duration target. The app's 60-second inactivity timeout still measures network
silence; it does not stop an actively streaming model at 60 seconds. No hard
generation deadline was added. Runs with different token limits or reasoning
effort may take substantially longer than this pilot.
