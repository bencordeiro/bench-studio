# Index

The Index tab sits directly below Leaderboards. It ranks models by the equal-weight average of their selected benchmark quality scores, on a 0–100 scale. Each suite contributes equally regardless of its question count. A model appears only when it has a completed, fully scored run for every selected suite.

Below the ranking table, a colored bar chart compares scores from highest to lowest, with diagonal model labels and a fixed 0–100 scale. Choose the top 10, top 25 (default), or all eligible models. Wide charts scroll horizontally; hover or focus a bar for its full model name and score. The chart follows the selected scoring basis.

The six defaults are:

1. Instruction-Following & Format Adherence
2. Terminal Semantics & System Gotchas
3. Web Dev Correctness & Debugging (JS)
4. Code Reasoning & Correctness (Python)
5. Cyber
6. Agentic Tool-Use & Structured Output (Hermes)

Mini Master is a separate 25-question sampler with its own score. It and HumanEval are excluded from the default Index.

Use **Settings → Index** to change the selected suites, then save. The selection persists across restarts. **Restore six defaults** restores the list above. An empty selection produces no ranking. A deleted or unavailable selected suite remains required until the selection changes; it cannot silently reduce the number of required benchmarks.

By default, each suite uses the model's latest completed, fully scored run. **Best run** uses its highest quality score for each suite; **Mean of runs** averages its eligible runs separately within each suite, then averages those suite scores equally. Models are grouped by their reported model name, consistent with the existing leaderboards. The table shows contributing endpoint names and links to run results.

Completed runs with generation errors remain eligible: failed generations and token exhaustion count as zero in their suite score. Cancelled, running, failed, or explicitly partially graded runs do not qualify. Older completed summaries without coverage counts remain usable when they contain a valid quality score. Historical suite versions remain usable with version warnings; no new model requests or re-benchmarking are needed to aggregate saved results.

The Index refreshes automatically. Its API is `GET /api/index?basis=latest`, with `best` and `mean` also supported. `GET /api/index/config` returns the resolved membership. The existing application settings API stores `index_suite_ids`: `null` means the six defaults, an array selects suite IDs, and `[]` disables the ranking.
