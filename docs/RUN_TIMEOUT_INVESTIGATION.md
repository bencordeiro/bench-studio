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
Master suite has 55 deterministic questions; Python has 30 deterministic and 20
execution questions. Each Python execution test already has a three-second
subprocess timeout. Neither suite needs a judge. Streaming keepalives also count
as network activity; an inactivity timeout does not detect a model stuck thinking
while its server continues sending bytes.

Cancellation cleanup and the current-question progress fix are retained. Restart
the backend to load changes. Tests cover active streams exceeding the inactivity
interval, inactivity failures, cancellation, progression after a failed request,
and global-limit snapshots that reject per-run overrides.
