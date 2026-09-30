# Benchmark duration and global limits

The 60-second timeout is a network inactivity timeout. A model actively
streaming tokens or reasoning may take longer than 60 seconds to answer.
There is no total generation deadline. The temporary wall-clock deadline
introduced during the investigation has been removed.

Global Settings controls max tokens per question and the inactivity timeout.
Every newly created run snapshots these values on the backend, including runs
created through the API. Run, prompt and endpoint token overrides cannot replace
these limits. Target, judge and verifier calls use the saved limits. Warm-up
requests retain their small eight-token budget. A zero token limit means the
provider's default; it does not enforce an identical token cap across providers.

Settings changes apply to subsequent runs. Existing runs keep their saved
configuration so results remain reproducible and a running benchmark does not
change limits halfway through. The New Run screen shows the global values but
has no controls for overriding them.

The locally available historical Master run (qwen27b, 59-question older snapshot)
took about 93 minutes. Its slowest question, `ms-cs-minimal-dfa`, took 269.65
seconds; several others took 256–258 seconds. These responses reported 8,192
completion tokens and zero retries. This is consistent with prolonged generation
under a server-default token budget, not evidence that an inactivity timeout
failed. The server reported `stop`; token counts alone do not prove truncation.
No Python-suite run was present in the inspected history.

Questions execute sequentially, so long generation times accumulate. The current
Master suite now has 45 deterministic questions; Python has 30 deterministic and 20
execution questions. Each Python execution test already has a three-second
subprocess timeout. Neither suite needs a judge. Streaming keepalives also count
as network activity; an inactivity timeout does not detect a model stuck thinking
while its server continues sending bytes.

Cancellation cleanup and the current-question progress fix are retained. Restart
the backend to load changes. Tests cover active streams exceeding the inactivity
interval, inactivity failures, cancellation, progression after a failed request,
and global-limit snapshots that reject per-run overrides.

## Settings persistence and first-question check (2026-09-29)

The settings PUT handler previously returned the edited settings without
committing its database transaction. A subsequent GET returned the defaults,
including `default_max_tokens = 0`; runs created afterward therefore did not
receive the token cap the user thought they had saved. The handler now commits
before returning the stored settings. A regression test reproduces the former
failure and checks refresh, application/database restart, new-run snapshots,
and preservation of existing runs when settings change.

The current first Master item, `ms-py-class-scope-comprehension`, was tested
against `qwenflash` at `http://10.0.0.10:8000/v1` with temperature zero, streaming,
no retries, and a temporary 1,024-token diagnostic cap. With the original prompt
and `xhigh` reasoning effort, it spent 33.14 seconds and the entire budget on
reasoning, repeatedly rechecking an already-correct answer without returning
final content. With `low` effort, the original prompt spent 25.84 seconds and
the entire budget on reasoning plus an explanation, ending before its required
answer line. Neither sample showed a connection failure or retry.

With the same `low` effort and an answer-only introduction, the endpoint returned
the correct answer in 16.25 seconds using 626 completion tokens. Master 4.1.0
uses that concise instruction for its 18 output-prediction questions. The code,
answer keys, weights, and 50-question count are unchanged. This is a single-item
diagnostic, not a full-suite duration estimate or proof of what happened in the
user's separate six-minute run. The experimental time/token caps were not made
application defaults. Inactivity timeout still measures network silence, and
an active stream has no total generation deadline.

## Master 5.0.0 duration follow-up

The [Qwen Flash follow-up](CALIBRATION_QWENFLASH_MASTER_2026_09_29.md) observed
all 50 requests in Master 4.1.0 completing in approximately 25 minutes 46 seconds
under a temporary 2,048-token, low-effort diagnostic profile. Fifteen responses
hit the token cap; request completion therefore did not mean a usable final
answer for every question. Five lengthy manual workloads were retired, leaving
45 questions. Numeric answers now use an answer-only contract and disclose
the existing accepted tolerances. Endpoint testing stopped at the user's request;
the revised full suite's duration is unmeasured. No diagnostic cap or observation
deadline was installed as an application default.
