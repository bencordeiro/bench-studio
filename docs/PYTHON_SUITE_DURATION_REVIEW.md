# Python suite duration review — September 30, 2026

Code Reasoning & Correctness (Python) 7.0.0 contains **45 questions**:
29 output traces and 16 complete-function tasks. This review used the prompt
contracts, actual CPython outputs, and local execution graders. **No endpoint
requests were made.** The removals below are static duration-risk judgments,
not measured Qwen Flash failures.

## Removed questions

| Stable ID | Reason for removal |
|---|---|
| `cr3-super-kwargs-chain` | Cooperative constructor order plus argument consumption invites repeated MRO analysis; a shorter diamond MRO item retains inheritance coverage. |
| `cr-fn-dependency-batches` | Graph layers, deduplication, cycle detection and partial progress combine several algorithmic decisions. |
| `cr-fn-apply-patch` | Recursive type replacement and deletion, with nested non-mutation, invite lengthy defensive implementations. |
| `cr-fn-allocate-cents` | Exact arithmetic, large integers, ranking and ties encourage extensive proof and precision checking. |
| `cr-fn-first-conflict` | Lexicographically earliest indices versus chronological order invites unnecessary scheduling optimization. |

## Remaining workload

Every trace prints a single bounded line and uses small explicit inputs. There
are no exception-group, singledispatch ambiguity, class/comprehension scope,
async scheduling, large combinatorial enumeration, or nondeterministic ordering
questions. The remaining descriptor, reflected-operator, generator and mutation
items retain Python-specific difficulty with short traces.

Each function has a single executable contract. Correct implementations in
`scripts/python_tasks.py` are compact and are validated against the shipped
edge cases and input non-mutation checks. Prompts request only the function,
without explanations, alternative solutions or a test harness, and explicitly
say malformed-input validation is unnecessary. Only the standard library is
needed. The retry-schedule contract bounds its budget at 10,000; nested
flattening assumes finite acyclic dictionaries with depth at most eight.
Missing-ranges deliberately retains a large numeric domain, since the task is
to process sorted observed IDs without enumerating that domain.

Generated-code grading has a three-second subprocess timeout per function;
this is separate from model generation. Suite prompts do not override global
token budgets. They also do not impose a new generation time limit.

## What still needs endpoint validation

Concise answer contracts reduce requested output but cannot force a reasoning
model to stop thinking. Global reasoning effort, token budgets and endpoint
throughput still control duration. Qwen Flash may continue generating until
its token limit, and that exhausted attempt counts as zero under scoring
revision 2. There is no guaranteed whole-suite duration yet.

When the user releases the endpoint for testing, measure per-question duration,
completion/reasoning tokens, finish reason, and total suite time under the
actual global settings. Start with a small targeted sample before spending
calls on all 45 questions. Retest only outliers or changed prompts. Preserve
question difficulty: an incorrect but finished answer is a useful result;
repeated token exhaustion or excessive duration is the issue to investigate.

## Upgrade behavior

The bundled version increases from 6.0.0 to 7.0.0. Startup replaces the existing
suite in place, preserving its ID. Saved runs retain their original snapshots;
the question removals affect new runs only. The builder's `--check` mode guards
against restoring retired workloads or stale contracts.
