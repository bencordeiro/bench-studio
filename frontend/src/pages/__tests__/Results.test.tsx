import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import Results from "@/pages/Results";
import type { RunResults } from "@/types";

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useParams: () => ({ id: "r1" }) };
});

const { mockResults, mockManual } = vi.hoisted(() => ({
  mockResults: vi.fn(),
  mockManual: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  api: {
    getResults: () => mockResults(),
    addManualGrade: (id: string, data: unknown) => mockManual(id, data),
    exportRunUrl: () => "/export",
  },
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Results />
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

const sample: RunResults = {
  run: {
    id: "r1", name: "Run 1", notes: "", status: "completed", benchmark_id: "b1",
    target_endpoint_id: "e1", target_endpoint_name: "Local", target_model: "demo",
    judge_endpoint_id: null, judge_endpoint_name: "", judge_model: "", judge_enabled: false,
    verifier_enabled: false, run_config: { repetitions: 1 } as never, summary: {},
    error_message: "", total_prompts: 2, completed_prompts: 2, failed_prompts: 0,
    created_at: "2026-01-01T00:00:00Z", started_at: null, completed_at: null,
  },
  summary: {
    quality_score: 75, reliability_score: 90, performance_index: 80, composite_score: 77,
    scoring_coverage: "2 of 2 prompts",
  },
  coverage: { scored: 2, total: 2, label: "2 of 2 prompts" },
  charts: { score_by_category: { general: 75 }, prompt_scores: [{ label: "p1", score: 80 }], score_vs_latency: [], ttft_distribution: [] },
  executions: [
    {
      id: "x1", run_id: "r1", prompt_snapshot_id: "p1", position: 0, repetition: 1,
      status: "awaiting_manual", final_score: null, max_score: 100, error_message: "",
      title: "Manual prompt", category: "writing", grading_mode: "manual", importance_weight: 1,
      messages: [{ role: "user", content: "be creative" }], candidate_response: "a haiku",
      reference_answer: "", finish_reason: "stop", timing: {}, deterministics: [],
      judge: null, verifier: null, manual: null, raw_meta: { http_status: 200, retry_count: 0, tokens_estimated: false },
    },
  ],
};

describe("Results summary and manual override", () => {
  it("shows summary scores and coverage", async () => {
    mockResults.mockResolvedValue(sample);
    renderPage();
    await waitFor(() => expect(screen.getByText("75.0")).toBeInTheDocument());
    expect(screen.getByText("2 of 2 prompts")).toBeInTheDocument();
  });

  it("allows a manual score override", async () => {
    mockResults.mockResolvedValue(sample);
    mockManual.mockResolvedValue({});
    renderPage();
    await waitFor(() => expect(screen.getByText("Manual prompt")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Manual prompt"));
    await waitFor(() => expect(screen.getByText("Manual override")).toBeInTheDocument());
    const saveButtons = screen.getAllByText("Save");
    await userEvent.click(saveButtons[saveButtons.length - 1]);
    // Save calls mutation; mockManual invoked with execution id.
    await waitFor(() => expect(mockManual).toHaveBeenCalled());
  });
  it("shows reasoning separately when no final answer was returned", async () => {
    mockResults.mockResolvedValue({ ...sample, executions: [{ ...sample.executions[0],
      candidate_response: "", reasoning_response: "retained model thought",
      generation_diagnostics: { no_final_answer: true, possible_repetition: true },
    }] });
    renderPage();
    await waitFor(() => expect(screen.getByText("Manual prompt")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Manual prompt"));
    expect(screen.getByText(/No final answer was returned/)).toBeInTheDocument();
    expect(screen.getByText("retained model thought")).toBeInTheDocument();
    expect(screen.getByText("(empty)")).toBeInTheDocument();
  });

  it("shows an incomplete endpoint stream separately from an empty answer", async () => {
    mockResults.mockResolvedValue({ ...sample, executions: [{ ...sample.executions[0],
      candidate_response: "partial answer",
      generation_diagnostics: { incomplete_stream: true },
      error_message: "Endpoint stream ended without a finish_reason or [DONE]",
    }] });
    renderPage();
    await waitFor(() => expect(screen.getByText("Manual prompt")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Manual prompt"));
    expect(screen.getByText(/endpoint stream ended without a completion marker/)).toBeInTheDocument();
    expect(screen.getByText("partial answer")).toBeInTheDocument();
  });

  it("identifies normalized native calls without claiming Hermes format was tested", async () => {
    mockResults.mockResolvedValue({ ...sample, executions: [{ ...sample.executions[0], tool_call_protocol: "native" }] });
    renderPage();
    await waitFor(() => expect(screen.getByText("Manual prompt")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Manual prompt"));
    expect(screen.getByText(/Hermes text formatting was not tested/)).toBeInTheDocument();
  });

});
