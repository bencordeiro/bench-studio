"""Mock OpenAI-compatible server for LocalBench Studio integration testing.

Not part of the application; used only to exercise the full pipeline without a
real LLM. Serves GET /v1/models and POST /v1/chat/completions (stream + non-stream).
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _read_body(self):
        length = int(self.headers.get("content-length", 0))
        return self.rfile.read(length).decode("utf-8", "ignore")

    def do_GET(self):
        # Model discovery.
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"data": [{"id": "mock-model"}, {"id": "judge-model"}]}).encode())

    def do_POST(self):
        try:
            data = json.loads(self._read_body())
        except Exception:
            data = {}
        msgs = data.get("messages", [])
        sys_content = msgs[0]["content"] if msgs else ""
        is_stream = data.get("stream", False)
        # Judge requests: the system prompt says "evaluator".
        if "evaluator" in sys_content.lower() or "verifier" in sys_content.lower():
            content = json.dumps({
                "dimension_scores": {
                    "correctness": {"score": 36, "maximum": 40, "reason": "sound diagnosis"},
                    "completeness": {"score": 20, "maximum": 25, "reason": "covers required steps"},
                },
                "raw_total": 56, "critical_error": False, "score_cap": None,
                "final_score": 82, "confidence": 0.9,
                "strengths": ["correct approach"], "deductions": [],
            })
            if "verifier" in sys_content.lower():
                content = json.dumps({
                    "confirmed": True, "verified_score": 82, "adjusted": False,
                    "adjustment_reason": "", "confidence": 0.92, "problems_found": [],
                })
        else:
            content = "The answer is C. Ottawa is the capital of Canada."

        if is_stream:
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            half = content[: len(content) // 2]
            rest = content[len(content) // 2:]
            for text, finish in [(half, None), (rest, None), ("", "stop")]:
                payload = {"choices": [{"delta": {"content": text}, "finish_reason": finish}]}
                self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
            # Real servers only report usage when the client asks for it. Emitting
            # it unconditionally would hide a client that forgot to request it.
            if (data.get("stream_options") or {}).get("include_usage"):
                usage_chunk = {
                    "choices": [],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
                }
                self.wfile.write(f"data: {json.dumps(usage_chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
            }).encode())


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8770), Handler).serve_forever()
