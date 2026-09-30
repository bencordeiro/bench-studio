# Benchmark sequences

In **New Run**, check the benchmarks to run and use the up/down controls to
choose their order. Select one target endpoint/model and the shared generation,
judge and repetition settings, then start the sequence. Global token limits
and inactivity timeout apply to every member.

The server creates all selected runs in one transaction. An unavailable or
empty benchmark rejects the whole selection before anything is queued. Each
benchmark has its own immutable snapshot, prompts, history row, scores, total
time and exports. Suites are not merged into one scoring denominator.

The runner processes an independent persistent queue for each target endpoint.
Runs on different target URLs execute concurrently. Runs sharing a target URL
start in creation order, one after another, without a polling gap between runs.
Duplicate profiles and different models pointing to the same URL share a queue;
equivalent URLs such as `http://host` and `http://host:80/v1/` also share it.
Endpoint identity is based on the target request destination, not the judge.
A failed or cancelled member does
not cancel later members. Deferred judge/manual grading also does not block
the next benchmark. Closing the browser leaves the queue running.

A **Benchmark sequence** card on each member's run page shows the ordered runs,
status and prompt counts, with links to every member. Cancel a queued member
from its run page to remove that member from execution; cancellation finishes
immediately. Active requests retain the existing immediate-abort behavior.
An application restart retains the sequence metadata; interrupted members use
the existing manual Resume behavior. The sequence is not a promise to bypass
that restart recovery step.

API: `POST /api/runs/chain` accepts the usual shared creation settings plus
`benchmark_ids` (ordered, unique, 1–50 IDs) and returns the separate run records.
`GET /api/runs/{run_id}/chain` returns the saved members in selection order.
No database migration is needed; group ID, position and size are saved in each
run's configuration. Single-benchmark creation continues to use `POST /api/runs`.
