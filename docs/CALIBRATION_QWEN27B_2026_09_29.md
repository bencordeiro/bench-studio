# Python and Master calibration: qwen27b, 2026-09-29

A targeted diagnostic pilot identified three distinct causes of poor or lengthy
runs: a brittle Python completion format, repetitive model reasoning, and valid
but expensive numerical questions. This is not a full-suite difficulty ranking.

## Method and limits

Requests ran sequentially against the user-provided llama.cpp endpoint, model
alias `qwen27b`. Discovery reported approximately 27.3 billion parameters and
`Q4_K - Small`. The exact upstream model revision and server hardware were not
identified. Both suites were sampled deliberately around suspected problem items,
with easy anchors for comparison. Webdev and the smaller suites were not tested.

Baseline requests used temperature 0, streaming, a 60-second network inactivity
timeout and no explicit token cap, matching the saved global limits. Server props
reported default temperature 0.8, max_tokens=-1 and n_predict=-1. All tested
requests used temperature 0; the proposed sampling comparison was not run before
the endpoint went offline. No causal claim about temperature is established.

Final content and reasoning were captured separately. Completed answers were
checked with the application's graders. A five-minute observation ceiling was
introduced for the experiment after the initial slow observation; unfinished
observations are censored, not scored as wrong. This ceiling was never added to
application settings. The initial class-creation observation retained counts but
not its partial text. Twelve original items and six controlled variants have
saved records. Another short request was interrupted during the handoff and is
excluded from the table.

## Observations

| Item | Original outcome | Controlled diagnostic or variant |
|---|---|---|
| Python closure binding | Passed, 8.2 s | — |
| Python tuple mutation | Passed, 9.4 s | — |
| Python reflected operators | Wrong, 8.7 s | Missed reflected-operator subclass priority |
| Python merge windows | Indentation failure, 46.0 s | First-line indentation repair passes; complete-function prompt passes in 14.0 s |
| Python dependency batches | Indentation failure, 22.3 s | First-line indentation repair passes; complete-function prompt passes in 19.5 s |
| Python recursive patch | Indentation failure, 56.7 s | First-line indentation repair passes; complete-function variant unfinished at 300 s |
| Master generator anchor | Passed, 6.6 s | — |
| Master class creation | Unfinished after at least 271 s | Neutral wording passes in 91.9 s; original-wording repeat unfinished at 300 s |
| Master ExitStack | Wrong, 28.5 s | Incorrectly predicted an escaping exception |
| Master minimal DFA | Unfinished at 300 s | Reasoning manually constructed and refined an automaton |
| Master weak-acid mixture | Passed, 188.5 s, 11,353 tokens | Neutral wording passes in 120.1 s |
| Master entropy cycle | Passed, 131.2 s, 7,892 tokens | — |

Neutral Master variants removed the invitation to reason as long as needed,
while preserving problem statements, answer requirements and graders. These are
single paired observations, except that the original class-creation wording was
observed twice. They support a targeted wording revision, not a general promised
speedup.

## What the evidence establishes

**Python formatting failures obscure correctness.** All three sampled function
answers lacked the first line's required four spaces, although later lines were
indented. Adding four spaces only to that first line made each pass every existing
test. The delivered output establishes the missing whitespace; the experiment
cannot determine whether it originated in the model, chat template or server.
Complete-function output avoids this specific dependency. It must still be
execution-graded strictly; diagnostic repairs are not official benchmark scores.

**Long generation includes real repetition loops.** The repeated class-creation
observation reproduced `if (type->tp_dict == NULL)` at least 250 times while
fabricating an outline of CPython internals. The complete-function patch variant
repeated and expanded hypothetical hidden-test cases for five minutes without
producing an answer. These are stronger signs of degeneration than merely a
large reasoning-token count. Changing Python output format alone does not solve
this behavior.

**Some Master questions are expensive but valid.** The two numerical items passed
after substantial manual calculation. The minimal-DFA item required lengthy
state construction and minimization. The easy anchor passed in under seven
seconds. Difficulty and duration vary greatly within the suite.

**Global server-default tokens do not bound reasoning.** The saved app limit was
zero and the server generation defaults were unlimited. Active streams therefore
had neither an application nor server token ceiling. This explains how a
repetition loop can extend a run indefinitely while the intended inactivity
timeout remains satisfied.

## Recommended changes

1. Change the 20 custom Python execution tasks to request complete raw function
   definitions, with an explicit grader mode for that contract. Keep HumanEval's
   upstream completion contract separate. Version the custom suite and keep old
   snapshots gradeable.
2. Remove open-ended deliberation invitations from Master prompts. Preserve the
   tasks and reference answers; do not lower weights based on this single model.
3. Preserve reasoning separately and surface repeated-generation diagnostics.
   Distinguish no final answer, invalid code shape, wrong answer, execution timeout
   and transport failure in results.
4. Use an explicit global token budget when comparing models. Report capped or
   unfinished answers separately. Retain inactivity-only timeouts.
5. Test sampler settings separately before selecting a model-compatible global
   profile. The observed server default of 0.8 is a candidate for an experiment,
   not a demonstrated remedy.
6. Measure additional models and a representative/full sweep before setting
   empirical difficulty tiers, predicted suite duration or calibrated weights.

Raw prompts, final responses, reasoning and grader details are retained locally
under `data/calibration/qwen27b-2026-09-29/` (ignored runtime data). The bundled
suites and application settings were not modified during this pilot.
