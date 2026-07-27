import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import Leaderboards from "@/pages/Leaderboards";
import type { LeaderboardResponse, LeaderboardSuiteSummary } from "@/types";

const { mockSuites, mockBoard } = vi.hoisted(() => ({
  mockSuites: vi.fn(),
  mockBoard: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  api: {
    listLeaderboardSuites: () => mockSuites(),
    getLeaderboard: (suiteId: string, basis: string, sort: string) => mockBoard(suiteId, basis, sort),
  },
}));

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/leaderboards" element={<Leaderboards />} />
          <Route path="/leaderboards/:suiteId" element={<Leaderboards />} />
          <Route path="/compare" element={<div>Compare Page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const suites: LeaderboardSuiteSummary[] = [
  {
    suite_id: "s1",
    suite_name: "Reasoning Suite",
    suite_version: "1.0.0",
    run_count: 3,
    model_count: 2,
    top_model: "gpt-smart",
    top_quality_score: 92,
    last_run_at: "2026-07-16T00:00:00Z",
  },
];

const board: LeaderboardResponse = {
  suite_id: "s1",
  suite_name: "Reasoning Suite",
  suite_version: "1.0.0",
  scoring_basis: "best",
  sort_metric: "quality",
  total_runs: 3,
  warnings: [],
  entries: [
    {
      rank: 1,
      model: "gpt-smart",
      run_count: 2,
      run_ids: ["run-a", "run-a2"],
      representative_run_id: "run-a",
      target_endpoint_names: ["Local"],
      quality_score: 92,
      reliability_score: 88,
      performance_index: 40,
      composite_score: 87,
      last_run_at: "2026-07-16T00:00:00Z",
    },
    {
      rank: 2,
      model: "gpt-fast",
      run_count: 1,
      run_ids: ["run-b"],
      representative_run_id: "run-b",
      target_endpoint_names: ["Local"],
      quality_score: 55,
      reliability_score: 70,
      performance_index: 95,
      composite_score: 60,
      last_run_at: "2026-07-15T00:00:00Z",
    },
  ],
};

describe("Leaderboards picker", () => {
  beforeEach(() => {
    mockSuites.mockReset();
    mockBoard.mockReset();
  });

  it("lists opted-in suites with top model", async () => {
    mockSuites.mockResolvedValue(suites);
    renderAt("/leaderboards");
    await waitFor(() => expect(screen.getByText("Reasoning Suite")).toBeInTheDocument());
    expect(screen.getByText("gpt-smart")).toBeInTheDocument();
    expect(screen.getByText("92.0")).toBeInTheDocument();
  });

  it("shows an empty state when no suites are enabled", async () => {
    mockSuites.mockResolvedValue([]);
    renderAt("/leaderboards");
    await waitFor(() =>
      expect(screen.getByText(/No suites enabled for leaderboards/i)).toBeInTheDocument(),
    );
  });
});

describe("Leaderboards table", () => {
  beforeEach(() => {
    mockSuites.mockReset();
    mockBoard.mockReset();
  });

  it("renders ranked models and default basis/sort", async () => {
    mockBoard.mockResolvedValue(board);
    renderAt("/leaderboards/s1");
    await waitFor(() => expect(screen.getByText("gpt-smart")).toBeInTheDocument());
    expect(screen.getByText("gpt-fast")).toBeInTheDocument();
    // Default query is best/quality.
    expect(mockBoard).toHaveBeenCalledWith("s1", "best", "quality");
  });

  it("refetches with a new sort when a column header is clicked", async () => {
    mockBoard.mockResolvedValue(board);
    renderAt("/leaderboards/s1");
    await waitFor(() => expect(screen.getByText("gpt-smart")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /Performance/i }));
    await waitFor(() => expect(mockBoard).toHaveBeenCalledWith("s1", "best", "performance"));
  });

  it("refetches with a new basis when the basis toggle is clicked", async () => {
    mockBoard.mockResolvedValue(board);
    renderAt("/leaderboards/s1");
    await waitFor(() => expect(screen.getByText("gpt-smart")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /Latest run/i }));
    await waitFor(() => expect(mockBoard).toHaveBeenCalledWith("s1", "latest", "quality"));
  });

  it("enables comparing two selected models", async () => {
    mockBoard.mockResolvedValue(board);
    renderAt("/leaderboards/s1");
    await waitFor(() => expect(screen.getByText("gpt-smart")).toBeInTheDocument());
    await userEvent.click(screen.getByLabelText("Select gpt-smart for comparison"));
    await userEvent.click(screen.getByLabelText("Select gpt-fast for comparison"));
    const compareBtn = await screen.findByRole("button", { name: /Compare 2 models/i });
    await userEvent.click(compareBtn);
    await waitFor(() => expect(screen.getByText("Compare Page")).toBeInTheDocument());
  });

  it("shows version-mismatch warnings", async () => {
    mockBoard.mockResolvedValue({
      ...board,
      warnings: ["Runs span different benchmark versions; cross-model comparability is limited."],
    });
    renderAt("/leaderboards/s1");
    await waitFor(() =>
      expect(screen.getByText(/different benchmark versions/i)).toBeInTheDocument(),
    );
  });
});
