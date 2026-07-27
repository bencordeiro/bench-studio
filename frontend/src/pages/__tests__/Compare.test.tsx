import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Compare from "@/pages/Compare";
import type { RunSummary } from "@/types";

const { mockRuns, mockCompare } = vi.hoisted(() => ({
  mockRuns: vi.fn(),
  mockCompare: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  api: {
    listRuns: () => mockRuns(),
    compareRuns: (ids: string[]) => mockCompare(ids),
  },
}));

const completedRuns: RunSummary[] = [
  {
    id: "r1", name: "Run One", status: "completed", target_model: "alpha",
    target_endpoint_name: "Local", benchmark_name: "Suite", total_prompts: 4,
    completed_prompts: 4, failed_prompts: 0, created_at: "2026-07-15T00:00:00Z",
    started_at: null, completed_at: null, quality_score: 80, reliability_score: 90,
    performance_index: 70, composite_score: 78,
  },
  {
    id: "r2", name: "Run Two", status: "completed_with_errors", target_model: "beta",
    target_endpoint_name: "Local", benchmark_name: "Suite", total_prompts: 4,
    completed_prompts: 4, failed_prompts: 1, created_at: "2026-07-16T00:00:00Z",
    started_at: null, completed_at: null, quality_score: 60, reliability_score: 70,
    performance_index: 65, composite_score: 62,
  },
];

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/compare" element={<Compare />} />
          <Route path="/runs/:id/results" element={<div>Results Page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Compare error UI", () => {
  beforeEach(() => {
    mockRuns.mockResolvedValue(completedRuns);
  });

  it("surfaces the error card when compareRuns rejects", async () => {
    mockCompare.mockRejectedValue(new Error("boom from server"));
    renderAt("/compare");

    // Select two runs to trigger the compare query.
    await waitFor(() => expect(screen.getByText("Run One")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Run One"));
    await userEvent.click(screen.getByText("Run Two"));

    await waitFor(() =>
      expect(screen.getByText(/Comparison failed: boom from server/i)).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/A selected run may have been deleted/i),
    ).toBeInTheDocument();
  });

  it("renders a removable chip for a preselected id that is no longer in the list", async () => {
    // No compare call needed for this assertion; keep it resolved to avoid noise.
    mockCompare.mockResolvedValue({ runs: [], per_prompt: [], warnings: [] });
    // "ghost-run" is NOT in completedRuns above.
    renderAt("/compare?ids=ghost-run&ids=r1");

    await waitFor(() => expect(screen.getByText("Run One")).toBeInTheDocument());

    // Phantom chip renders with the truncated id.
    const chip = await screen.findByText(/ghost-ru/i);
    expect(chip).toBeInTheDocument();
    expect(
      screen.getByText(/Selected runs not shown in the list above/i),
    ).toBeInTheDocument();

    // Clicking the chip removes it from the selection.
    await userEvent.click(chip);
    await waitFor(() => expect(screen.queryByText(/ghost-ru/i)).not.toBeInTheDocument());
  });
});
