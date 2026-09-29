# Tool-call transport: native API and Hermes text

Bench Studio supports both literal Hermes `<tool_call>` blocks and native API
`tools` / `tool_calls` for the Agentic suite and Master's six tool scenarios.
The model server can keep its tool-call parser enabled.

The previous compatibility gate in `b653759` blocked an entire suite when the
server rejected literal Hermes blocks. That was too broad: rejection of that
text format does not mean the endpoint cannot call tools. The app now selects
a usable transport and continues the benchmark. Tool errors are recorded per
question and do not stop unrelated questions in a mixed suite.

## Transport selection

Before scored questions, runs with tool schemas or tool-call checks perform a
short non-streaming text probe. If the server preserves literal Hermes text,
those questions retain their original text protocol. If the probe rejects the
text or is inconclusive, a second probe sends a native `tools` schema.

A native HTTP 200 response selects the native protocol; actual native calls
confirm compatibility. A refusal, truncated response or failure to choose a
tool belongs in model evaluation rather than a gate that blocks the suite.
If both probes are inconclusive, the app records that uncertainty and proceeds:
native transport when the server explicitly rejected text, otherwise text.

The selected protocol is saved in the run configuration and snapshot, displayed
on the run page, and exported. Resumed runs retain an already selected protocol.
Historical runs remain unchanged. Comparison warns when runs use different
tool-call protocols.

The probes are unscored, use no retries, request at most 256 tokens each (or a
smaller positive global limit), and each has a separate 30-second diagnostic
deadline. Probe latency, tokens and cost are excluded from question metrics;
endpoint usage charges may still apply. Scored questions continue to use the
snapshotted global token budget and inactivity timeout, with no total generation
deadline.

## Native questions and grading

The adapter extracts the supplied function schemas and sends them as API
`tools`, with `tool_choice: auto`. It replaces Hermes envelope instructions
with native calling instructions while preserving task-specific suffix
constraints. Earlier assistant calls become structured `tool_calls`, with
stable IDs, and supplied results become matching `role: tool` messages.
Multi-call histories and the named-result retry scenario are supported. No
real tools are executed: the question's supplied results remain fixed.

The client assembles streamed call names and argument fragments by call index,
retains native calls and final prose separately from reasoning, and records
usage and finish reasons. A completed native call is a valid answer even if
`content` is empty. Interrupted streams remain errors with partial data retained.

Actual native calls are serialized into the existing grader's internal Hermes
representation. Tool selection, argument values/types, extra calls, missing
arguments, refusals and prose constraints are evaluated by the same semantic
checks. Invalid argument JSON and duplicate keys are retained as invalid, not
repaired. The results API and JSON export retain the original native calls and
identify the protocol; the results UI labels the normalized representation.

Native transport does not test the model's ability to spell XML envelopes.
Treat those format scores separately from historical Hermes text runs; the
comparison warning makes this distinction visible.

## Live validation (2026-09-29)

At `http://10.0.0.10:8000/v1`, model `qwenflash`, literal Hermes text returned
HTTP 400 `malformed tool call`, while the native probe returned valid calls.
The automatic selector chose native transport with `xhigh` reasoning selected.

A sequential diagnostic sweep covered all six Master tool scenarios and all
15 Agentic/Hermes scenarios. All 21 completed without transport errors and
scored 100 through the existing graders, taking approximately 5–15 seconds
per question. This included parallel calls, argument precision, error recovery,
ID propagation, idempotency, missing required arguments, and answers requiring
no additional call. The diagnostic used 1,024 tokens and a 60-second experimental
ceiling per request; these are test limits, not new application defaults.
The other 44 Master questions were not included in this targeted sweep.

Raw local observations are retained in the ignored calibration artifact
`data/calibration/qwenflash-native-2026-09-29.json`. Automated tests cover all
21 schema/history conversions, fragmented parallel calls, invalid arguments,
mixed native/chat runs, protocol selection and per-question failure handling.

Pull the latest changes, rebuild/restart Bench Studio and create a new run.
The model server's tool-call parser can remain enabled.
