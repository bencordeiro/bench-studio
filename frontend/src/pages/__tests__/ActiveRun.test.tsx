import { describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import ActiveRun from "@/pages/ActiveRun";
import type { RunResponse } from "@/types";

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useParams: () => ({ id: "r1" }) };
});

const { mockGet, mockChain } = vi.hoisted(() => ({ mockGet: vi.fn(), mockChain: vi.fn() }));

vi.mock("@/api/client", () => ({
  api: { getRun: () => mockGet(), getRunChain: () => mockChain() },
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <ActiveRun />
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

const run: RunResponse = {
  id: "r1", name: "My Run", notes: "", status: "running_target", benchmark_id: "b1",
  target_endpoint_id: "e1", target_endpoint_name: "Local", target_model: "demo-model",
  judge_endpoint_id: null, judge_endpoint_name: "", judge_model: "", judge_enabled: false,
  verifier_enabled: false, run_config: { repetitions: 1 } as never, summary: {},
  error_message: "", total_prompts: 10, completed_prompts: 4, failed_prompts: 1,
  created_at: "2026-01-01T00:00:00Z", started_at: "2026-01-01T00:00:00Z", completed_at: null,
};

describe("Active Run progress display", () => {
  it("shows sequence progress and links to the next benchmark", async () => {
    mockGet.mockResolvedValue({ ...run, status: "completed", run_config: { ...run.run_config, chain_id: "c1" } });
    mockChain.mockResolvedValue([
      { ...run, benchmark_name: "Python", status: "completed" },
      { ...run, id: "r2", benchmark_name: "Mini Master", status: "running_target" },
    ]);
    renderPage();
    await waitFor(() => expect(screen.getByText("Benchmark sequence")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "2. Mini Master" })).toHaveAttribute("href", "/runs/r2");
    expect(screen.getByRole("link", { name: "1. Python" })).toHaveAttribute("aria-current", "page");
  });

  it("shows saved total time when a finished run is reopened", async () => {
    mockGet.mockResolvedValue({ ...run, status: "completed", completed_prompts: 10,
      completed_at: "2026-01-01T00:25:46Z",
    });
    renderPage();
    await waitFor(() => expect(screen.getByText("Total time")).toBeInTheDocument());
    expect(screen.getByText("25m 46s")).toBeInTheDocument();
  });

  it("retains an inconclusive tool compatibility warning", async () => {
    mockGet.mockResolvedValue({ ...run, text_tool_compatibility: {
      status: "inconclusive", message: "Text tool-call compatibility could not be confirmed; benchmark questions will still run.",
    } });
    renderPage();
    await waitFor(() => expect(screen.getByText(/Text tool-call compatibility could not be confirmed/)).toBeInTheDocument());
  });
  it("shows current progress percentage and prompt counts", async () => {
    mockGet.mockResolvedValue(run);
    renderPage();
    await waitFor(() => expect(screen.getByText("My Run")).toBeInTheDocument());
    expect(screen.getByText(/4 \/ 10 prompts/)).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
    expect(screen.getByText("Errors")).toBeInTheDocument();
  });
  it("shows generation warnings and clears them for the next question", async () => {
    mockGet.mockResolvedValue(run);
    renderPage();
    await waitFor(() => expect(screen.getByText("My Run")).toBeInTheDocument());
    const instances = (EventSource as unknown as { instances: { onmessage: ((event: MessageEvent) => void) | null }[] }).instances;
    const source = instances[instances.length - 1];
    act(() => source.onmessage?.(new MessageEvent("message", { data: JSON.stringify({
      event: "generation", elapsed_seconds: 90, answer_chars: 0, reasoning_chars: 5000,
      possible_repetition: true, retry_count: 0,
    }) })));
    expect(screen.getByText(/Possible repetitive generation detected/)).toBeInTheDocument();
    expect(screen.getByText(/Reasoning: 5,000 characters/)).toBeInTheDocument();
    act(() => source.onmessage?.(new MessageEvent("message", { data: JSON.stringify({
      event: "prompt_started", current_prompt: "Next question",
    }) })));
    expect(screen.queryByText(/Possible repetitive generation detected/)).not.toBeInTheDocument();
  });

});
