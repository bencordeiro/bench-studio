import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import BenchmarkLibrary from "@/pages/BenchmarkLibrary";

const { list } = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock("@/api/client", () => ({ api: {
  listBenchmarks: () => list(), exportBenchmarkUrl: (id: string) => `/api/benchmarks/${id}/export`,
} }));
function renderPage() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><BenchmarkLibrary /></MemoryRouter>
  </QueryClientProvider>);
}
describe("Benchmark library", () => {
  beforeEach(() => vi.clearAllMocks());
  it("links a standalone sampler directly to a preselected run", async () => {
    list.mockResolvedValue([{ id: "mini", name: "Mini Master", description: "25 selected questions", tags: [], version: "3.0.0",
      prompt_count: 25, enabled_prompt_count: 25, updated_at: "2026-10-29T00:00:00Z" }]);
    renderPage();
    expect(await screen.findByRole("link", { name: "Run suite" })).toHaveAttribute("href", "/runs/new?benchmark=mini");
    expect(screen.getByText("Standalone")).toBeInTheDocument();
  });
  it("distinguishes request failure from an empty library and retries", async () => {
    list.mockRejectedValue(new Error("Connection lost"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Connection lost");
    expect(screen.queryByText("No benchmarks")).not.toBeInTheDocument();
    list.mockResolvedValue([]);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No benchmarks")).toBeInTheDocument();
  });
});
