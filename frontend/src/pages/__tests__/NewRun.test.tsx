import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import NewRun from "@/pages/NewRun";

const { mockEndpoints, mockBenchmarks, mockCreate } = vi.hoisted(() => ({
  mockEndpoints: vi.fn(),
  mockBenchmarks: vi.fn(),
  mockCreate: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  api: {
    listEndpoints: () => mockEndpoints(),
    listBenchmarks: () => mockBenchmarks(),
    createRun: (data: unknown) => mockCreate(data),
  },
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <NewRun />
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

describe("New Run form validation", () => {
  beforeEach(() => {
    mockEndpoints.mockResolvedValue([
      { id: "e1", name: "Local", enabled: true, default_model: "demo" },
    ]);
    mockBenchmarks.mockResolvedValue([
      { id: "b1", name: "Bench", enabled_prompt_count: 5, version: "1.0.0" },
    ]);
    mockCreate.mockResolvedValue({ id: "r1" });
  });

  it("prevents starting without a target model", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Start run")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Start run"));
    await waitFor(() => expect(mockCreate).not.toHaveBeenCalled());
  });

  it("warns when target and judge are the same model", async () => {
    renderPage();
    // Wait for the benchmark select option (rendered as "Bench (5 prompts) v1.0.0").
    await waitFor(() => expect(screen.getByText(/Bench \(5 prompts\)/)).toBeInTheDocument());
    const selects = screen.getAllByRole("combobox");
    await userEvent.selectOptions(selects[0], "b1");
    await userEvent.selectOptions(selects[1], "e1");
    await userEvent.selectOptions(selects[2], "e1");
    // Both models default to 'demo' -> same model warning.
    await waitFor(() => {
      expect(screen.getByText(/self-judging can bias/i)).toBeInTheDocument();
    });
  });
});
