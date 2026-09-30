import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import App from "@/App";
import type { IndexLeaderboard } from "@/types";

const { mockIndex } = vi.hoisted(() => ({ mockIndex: vi.fn() }));
vi.mock("@/api/client", () => ({ api: {
  health: async () => ({ version: "1.0.0", data_dir: "/data", frontend_built: true }),
  getIndex: (basis: string) => mockIndex(basis),
} }));

const board: IndexLeaderboard = {
  uses_defaults: true, default_suite_ids: ["py", "cy"],
  suites: [{ id: "py", name: "Python", version: "7.0.0", missing: false },
           { id: "cy", name: "Cyber", version: "1.0.0", missing: false }],
  scoring_basis: "latest", warnings: [], incomplete_model_count: 1,
  entries: [{ rank: 1, model: "complete-model", index_score: 80, completed_suites: 2, required_suites: 2,
    run_count: 2, last_run_at: null, target_endpoint_names: ["Local"],
    suite_scores: [{ suite_id: "py", score: 100, run_count: 1, representative_run_id: "r1" },
                   { suite_id: "cy", score: 60, run_count: 1, representative_run_id: "r2" }] }],
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={["/index"]}><App /></MemoryRouter></QueryClientProvider>);
}

describe("Index leaderboard", () => {
  beforeEach(() => { vi.clearAllMocks(); mockIndex.mockResolvedValue(board); });
  it("places Index immediately below Leaderboards and shows aggregate and run links", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("complete-model")).toBeInTheDocument());
    const links = within(screen.getByRole("navigation")).getAllByRole("link");
    const leaderboard = links.findIndex((link) => link.textContent === "Leaderboards");
    expect(links[leaderboard + 1]).toHaveTextContent("Index");
    expect(links[leaderboard + 1]).toHaveAttribute("href", "/index");
    expect(screen.getByRole("link", { name: "Configure Index" })).toHaveAttribute("href", "/settings#index-settings");
    expect(screen.getByRole("link", { name: "100.0" })).toHaveAttribute("href", "/runs/r1/results");
    expect(screen.getByText("80.0")).toBeInTheDocument();
    expect(screen.getByText(/models are excluded until all selected benchmarks/)).toBeInTheDocument();
  });
  it("switches the per-suite scoring basis", async () => {
    renderPage();
    await waitFor(() => expect(mockIndex).toHaveBeenCalledWith("latest"));
    await userEvent.click(screen.getByRole("button", { name: "Mean of runs" }));
    await waitFor(() => expect(mockIndex).toHaveBeenCalledWith("mean"));
  });
  it("shows no model rows when none completed the full selection", async () => {
    mockIndex.mockResolvedValue({ ...board, entries: [] });
    renderPage();
    await waitFor(() => expect(screen.getByText("No models have completed the full Index yet")).toBeInTheDocument());
    expect(screen.queryByText("complete-model")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
