# Hermes text tool calls and endpoint compatibility

The Agentic Tool-Use & Structured Output (Hermes) suite asks for literal
`<tool_call>{"name":"...","arguments":{...}}</tool_call>` blocks. Its graders
read final answer text. Tools are described in the messages; this suite does
not implement native function calling through the request's `tools` parameter.

A server-side tool-call parser can reject those blocks or convert them into
native `tool_calls` responses. This prevents end-to-end text grading even if
the model selected the right tool. Configure the server to preserve generated
text, disable its tool-call parser, or use a pass-through endpoint. Parser
settings vary by server; the app does not change server configuration.

## Run preparation

Before warmup or scored questions, any run with enabled `tool_call` checks
performs one non-streaming copy probe. It uses the target model, credentials,
headers, TLS settings and reasoning effort. The probe requests a fixed weather
call so a parser rejection can be reported as a JSON HTTP error rather than a
silently terminated SSE stream.

- Explicit malformed-tool-call/parser errors and native-call conversion mark
  the endpoint **incompatible**. The run ends `failed` with a specific error,
  and no scored questions are sent. Pending questions have no scores.
- Preserved exact text marks the probe **compatible**; scored questions run.
- Timeouts, token exhaustion, ordinary model refusals, unrelated HTTP errors
  and other unexpected answers are **inconclusive**. The UI displays the
  result and questions still run. A model's failure to copy alone cannot prove
  that the server rejected the format.

The probe is unscored, has no retries, requests at most 256 tokens (or a smaller
positive global limit), and has a separate 30-second diagnostic deadline. Its
latency, tokens and cost are excluded from benchmark metrics. Scored questions
still use the snapshotted global token budget and inactivity timeout, with no
total generation deadline. A probe can incur endpoint usage charges.

The compatibility result is stored in the run snapshot and exposed by the run
API and JSON export. Resuming an interrupted run probes the current endpoint
again. If an inconclusive probe is followed by a confirmed rejection on an
actual tool question, that response is retained and the remaining run stops.

## Stream diagnostics

The client records whether a stream received `[DONE]`, a finish reason, usage,
and native tool-call deltas. A finish reason or `[DONE]` is sufficient for
completion, allowing servers that omit one of the two. A stream that ends
without either marker is an **incomplete stream**, even if it contains partial
answer text. Partial answers and reasoning are retained separately and never
graded as completed output.

For text tool-call items, an abrupt empty-answer stream explains that a server
parser **may** have aborted generation. That diagnostic is not proof of the
cause: network interruptions can look identical. Explicit server errors are
preserved, including errors carried inside SSE events. Completed reasoning-only
responses retain the ordinary missing-final-answer error.

## Reproduction and validation (2026-09-29)

At `http://10.0.0.10:8000/v1`, model `qwenflash`, a direct non-streaming literal
Hermes request returned HTTP 400 with `malformed tool call`. The new probe also
returned `incompatible` with `xhigh` reasoning selected. This confirms endpoint
transport incompatibility for this format, not a tool-selection quality score.
A live streaming reproduction retained 235 characters of reasoning, received
no final text, finish reason, usage or `[DONE]`, and ended after about 2.8
seconds. The updated client labeled it an incomplete stream and the item
diagnostic identified a possible server parser abort.
Automated tests cover interrupted SSE, retained partial output, native-call
conversion, parser errors, inconclusive model responses, and stopping before
questions are scored.

Existing historical runs and their errors are preserved. Update and restart
the app, then create a new run to use these checks.
