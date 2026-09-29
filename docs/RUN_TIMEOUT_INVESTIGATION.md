# Slow benchmark runs: findings and fix

The client previously passed the configured timeout only to HTTPX. That bounds
network inactivity, not the total duration of generation. Tokens, reasoning
chunks, or SSE keepalives arriving regularly could keep a request alive
indefinitely. The default output-token setting is zero (server default), so
there was also no application-specified generation cap. Requests run sequentially.

The locally available historical Master run (qwen27b, 59-question older snapshot)
took about 93 minutes despite a 60-second configured timeout. The slowest question
was `ms-cs-minimal-dfa` at 269.65 seconds; several others took 256–258 seconds.
Those responses reported 8,192 completion tokens and zero retries. Their server
reported `stop`, so token count alone does not prove truncation. These measurements
show generation exceeded the requested timeout; retries were not the cause of
those particular delays. No Python-suite run was present in the inspected history,
so its reported multi-hour behavior could not be verified directly.

Both current suites use the same request path. Master has 55 deterministic
questions. Python has 30 deterministic questions and 20 execution questions;
each execution test already has a three-second subprocess timeout. No judge is
needed for either suite. Master contains long-context and difficult reasoning
questions, which can increase prefill and generation time.

The request timeout now bounds the entire call, including connection, generation,
stream consumption, compatibility fallback, retries and backoff. Deadline expiry
returns an explicit failure without restarting the request. The runner records
that failure and proceeds to the next question. This applies to target, judge,
verifier and warm-up calls. Cancelling the parent job also cancels and drains its
in-flight request instead of leaving an orphaned task.

The UI describes this as a request time budget and announces the current question
before generation starts. Previously the displayed question updated only after
its response had arrived.

At 60 seconds per request and one repetition, target generation for 50/55
questions has a budget of about 50/55 minutes, plus local processing overhead.
This is a ceiling, not an expected duration. Python execution grading can add
roughly one minute if all 20 programs time out. Larger budgets and repetitions
can still intentionally produce multi-hour runs. A short budget can reject a
model that would eventually answer correctly; use identical budgets when
comparing models and increase the budget for slower hardware as appropriate.
Restart the backend to load the fix. Existing historical results are preserved.

Regression tests cover endless content, reasoning and keepalive streams; a hung
nonstreaming response; backoff exceeding the budget; parent cancellation; and a
complete run that fails a timed-out question then successfully grades the next.

Validation: 74 backend tests passed across the client, job engine, execution
grader, connection and metrics tests; six relevant frontend tests passed;
production frontend build, Ruff on touched Python files, and whitespace checks
passed. No live model requests were needed for the reproductions.
