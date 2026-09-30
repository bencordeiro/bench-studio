import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import App from "@/App";
import type { RunSummary } from "@/types";

vi.mock("@/api/client", () => ({ api: {
  health: async () => ({ version: "1.0.0", data_dir: "/tmp", frontend_built: true }),
  listRuns: async () => [
    { id: "r1", name: "Master run", benchmark_name: "Master Suite", status: "completed", target_model: "qwenflash",
      started_at: "2026-01-01T00:00:00", completed_at: "2026-01-01T00:25:46",
      created_at: "2026-01-01T00:00:00Z", quality_score: 80, reliability_score: 90, performance_index: 70 },
    { id: "r2", name: "Older run", status: "completed", target_model: "another-model",
      started_at: null, completed_at: null, created_at: "2026-01-01T00:00:00Z" },
  ] as RunSummary[],
} }));

describe("Run history duration", () => {
  it("shows a completed model's total run time and leaves missing timestamps unknown", async () => {
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={["/runs"]}><App /></MemoryRouter>
    </QueryClientProvider>);
    await waitFor(() => expect(screen.getByText("Master run")).toBeInTheDocument());
    expect(screen.getByRole("columnheader", { name: "Total time" })).toBeInTheDocument();
    const row = screen.getByText("Master run").closest("tr")!;
    expect(within(row).getByText("qwenflash")).toBeInTheDocument();
    expect(within(row).getByText("Master Suite")).toBeInTheDocument();
    expect(within(row).getByText("25m 46s")).toBeInTheDocument();
    const oldRow = screen.getByText("Older run").closest("tr")!;
    expect(within(oldRow).getAllByRole("cell")[6]).toHaveTextContent("—");
  });
});
