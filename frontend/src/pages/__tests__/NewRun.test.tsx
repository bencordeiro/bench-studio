import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import NewRun from "@/pages/NewRun";

const { mockEndpoints, mockBenchmarks, mockCreate, mockFetchModels } = vi.hoisted(() => ({
  mockEndpoints: vi.fn(),
  mockBenchmarks: vi.fn(),
  mockCreate: vi.fn(),
  mockFetchModels: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  api: {
    getSettings: async () => ({ default_max_tokens: 4096, default_timeout: 90 }),
    listEndpoints: () => mockEndpoints(),
    listBenchmarks: () => mockBenchmarks(),
    createRun: (data: unknown) => mockCreate(data),
    fetchModels: (id: string) => mockFetchModels(id),
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
    // Models probe fails by default -> model field stays empty.
    mockFetchModels.mockResolvedValue({ success: false, error: "nope", models: [] });
  });

  it("shows global limits without per-run limit controls", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText(/4096 max tokens, 90s inactivity timeout/)).toBeInTheDocument());
    expect(screen.queryByText("Max output tokens")).not.toBeInTheDocument();
    expect(screen.queryByText("Request time budget (s)")).not.toBeInTheDocument();
  });

  it("explains Hermes compatibility before starting a run", async () => {
    mockBenchmarks.mockResolvedValue([
      { id: "h1", name: "Hermes", enabled_prompt_count: 15, version: "4.0.0", tags: ["hermes"] },
    ]);
    renderPage();
    await waitFor(() => expect(screen.getByText(/Hermes \(15 prompts\)/)).toBeInTheDocument());
    await userEvent.selectOptions(screen.getAllByRole("combobox")[0], "h1");
    expect(screen.getByText(/Compatibility is checked before questions run/)).toBeInTheDocument();
  });

  it("prevents starting without a target model", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Start run")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Start run"));
    await waitFor(() => expect(mockCreate).not.toHaveBeenCalled());
  });

  it("warns when target and judge are the same model", async () => {
    // Both endpoints report the same single model -> both prefilled identically.
    mockFetchModels.mockResolvedValue({ success: true, models: ["demo"], error: null });
    renderPage();
    await waitFor(() => expect(screen.getByText(/Bench \(5 prompts\)/)).toBeInTheDocument());
    // Comboboxes in DOM order: benchmark, target endpoint, target model input,
    // judge endpoint, judge model input.
    const selects = screen.getAllByRole("combobox");
    await userEvent.selectOptions(selects[0], "b1");
    await userEvent.selectOptions(selects[1], "e1");
    await userEvent.selectOptions(selects[3], "e1");
    // Both models prefilled to 'demo' -> same model warning.
    await waitFor(() => {
      expect(screen.getByText(/self-judging can bias/i)).toBeInTheDocument();
    });
  });

  it("prefills the target model from /v1/models when a single model is discovered", async () => {
    mockFetchModels.mockResolvedValue({ success: true, models: ["laguna"], error: null });
    renderPage();
    await waitFor(() => expect(screen.getByText(/Bench \(5 prompts\)/)).toBeInTheDocument());
    const selects = screen.getAllByRole("combobox");
    await userEvent.selectOptions(selects[0], "b1");
    await userEvent.selectOptions(selects[1], "e1");
    await waitFor(() => {
      expect(screen.getByDisplayValue("laguna")).toBeInTheDocument();
    });
    expect(screen.getByText(/model\(s\) discovered via \/v1\/models/i)).toBeInTheDocument();
  });

  it("leaves the model empty when /v1/models fails", async () => {
    mockFetchModels.mockResolvedValue({ success: false, models: [], error: "refused" });
    renderPage();
    await waitFor(() => expect(screen.getByText(/Bench \(5 prompts\)/)).toBeInTheDocument());
    const selects = screen.getAllByRole("combobox");
    await userEvent.selectOptions(selects[0], "b1");
    await userEvent.selectOptions(selects[1], "e1");
    await waitFor(() => {
      expect(screen.queryByDisplayValue("demo")).not.toBeInTheDocument();
    });
    const modelInput = screen.getByPlaceholderText("model name") as HTMLInputElement;
    expect(modelInput.value).toBe("");
  });

  it("does not guess when multiple models are discovered", async () => {
    mockFetchModels.mockResolvedValue({ success: true, models: ["laguna", "qwen27b"], error: null });
    renderPage();
    await waitFor(() => expect(screen.getByText(/Bench \(5 prompts\)/)).toBeInTheDocument());
    const selects = screen.getAllByRole("combobox");
    await userEvent.selectOptions(selects[0], "b1");
    await userEvent.selectOptions(selects[1], "e1");
    await waitFor(() => {
      expect(screen.queryByDisplayValue("laguna")).not.toBeInTheDocument();
    });
    const modelInput = screen.getByPlaceholderText("model name") as HTMLInputElement;
    expect(modelInput.value).toBe("");
  });
});
