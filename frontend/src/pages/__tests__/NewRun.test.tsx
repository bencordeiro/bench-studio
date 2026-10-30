import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import NewRun from "@/pages/NewRun";

const { mockEndpoints, mockBenchmarks, mockCreate, mockChain, mockFetchModels, mockIndexConfig } = vi.hoisted(() => ({
  mockEndpoints: vi.fn(),
  mockBenchmarks: vi.fn(),
  mockCreate: vi.fn(),
  mockChain: vi.fn(),
  mockFetchModels: vi.fn(),
  mockIndexConfig: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  api: {
    getSettings: async () => ({ default_max_tokens: 4096, default_timeout: 90 }),
    listEndpoints: () => mockEndpoints(),
    getIndexConfig: () => mockIndexConfig(),
    listBenchmarks: () => mockBenchmarks(),
    createRun: (data: unknown) => mockCreate(data),
    createRunChain: (data: unknown) => mockChain(data),
    fetchModels: (id: string) => mockFetchModels(id),
  },
}));

function renderPage(path = "/runs/new") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <NewRun />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("New Run form validation", () => {
  it("selects the six core suites and keeps Mini Master as a separate shortcut", async () => {
    const core = Array.from({ length: 6 }, (_, i) => ({ id: `core-${i}`, name: `Core ${i}`, enabled_prompt_count: 10, version: "1.0.0" }));
    mockBenchmarks.mockResolvedValue([...core, { id: "mini", name: "Mini Master", enabled_prompt_count: 25, version: "3.0.0" }]);
    mockIndexConfig.mockResolvedValue({ default_suite_ids: core.map((b) => b.id), suites: [] });
    renderPage();
    const selectCore = await screen.findByRole("button", { name: "Select six Index suites" });
    await waitFor(() => expect(selectCore).toBeEnabled());
    await userEvent.click(selectCore);
    expect(within(screen.getByRole("group", { name: "Benchmark sets" })).getAllByRole("checkbox").filter((box) => (box as HTMLInputElement).checked)).toHaveLength(6);
    expect(screen.getByRole("checkbox", { name: /Mini Master/ })).not.toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Mini Master only" }));
    expect(within(screen.getByRole("group", { name: "Benchmark sets" })).getAllByRole("checkbox").filter((box) => (box as HTMLInputElement).checked)).toHaveLength(1);
    expect(screen.getByRole("checkbox", { name: /Mini Master/ })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(within(screen.getByRole("group", { name: "Benchmark sets" })).getAllByRole("checkbox").every((box) => !(box as HTMLInputElement).checked)).toBe(true);
  });

  it("preselects the suite linked from the library", async () => {
    renderPage("/runs/new?benchmark=b1");
    await waitFor(() => expect(screen.getByRole("checkbox", { name: /Bench/ })).toBeChecked());
  });

  it("shows failed benchmark loading with a retry action", async () => {
    mockBenchmarks.mockRejectedValue(new Error("Library unavailable"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Library unavailable");
    expect(screen.queryByText("No benchmarks available")).not.toBeInTheDocument();
    mockBenchmarks.mockResolvedValue([{ id: "b1", name: "Recovered", enabled_prompt_count: 5, version: "1.0.0" }]);
    await userEvent.click(screen.getByRole("button", { name: "Retry loading benchmarks" }));
    expect(await screen.findByRole("checkbox", { name: /Recovered/ })).toBeInTheDocument();
  });

  it("queues multiple benchmarks in the chosen order with shared settings", async () => {
    mockBenchmarks.mockResolvedValue([
      { id: "b1", name: "Python", enabled_prompt_count: 40, version: "8.0.0" },
      { id: "b2", name: "Mini Master", enabled_prompt_count: 25, version: "3.0.0" },
      { id: "b3", name: "Empty", enabled_prompt_count: 0, version: "1.0.0" },
    ]);
    mockFetchModels.mockResolvedValue({ success: true, models: ["demo"], error: null });
    renderPage();
    await waitFor(() => expect(screen.getByRole("checkbox", { name: /Python/ })).toBeInTheDocument());
    expect(screen.getByRole("checkbox", { name: /Empty/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /Python/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Mini Master/ }));
    await userEvent.click(screen.getByRole("button", { name: "Move Mini Master up" }));
    expect(screen.getByText("1. Mini Master")).toBeInTheDocument();
    expect(screen.getByText(/65 prompts including repetitions/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getAllByRole("combobox")[0], "e1");
    await waitFor(() => expect(screen.getByDisplayValue("demo")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Start 2 benchmarks" }));
    await waitFor(() => expect(mockChain).toHaveBeenCalledOnce());
    expect(mockChain).toHaveBeenCalledWith(expect.objectContaining({
      benchmark_ids: ["b2", "b1"], target_endpoint_id: "e1", target_model: "demo",
      run_config: expect.objectContaining({ repetitions: 1, sequential_execution: true }),
    }));
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it("keeps the single benchmark submission path", async () => {
    mockFetchModels.mockResolvedValue({ success: true, models: ["demo"], error: null });
    renderPage();
    await waitFor(() => expect(screen.getByRole("checkbox", { name: /Bench/ })).toBeInTheDocument());
    await userEvent.click(screen.getByRole("checkbox", { name: /Bench/ }));
    await userEvent.selectOptions(screen.getAllByRole("combobox")[0], "e1");
    await waitFor(() => expect(screen.getByDisplayValue("demo")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    await waitFor(() => expect(mockCreate).toHaveBeenCalledOnce());
    expect(mockCreate).toHaveBeenCalledWith(expect.objectContaining({ benchmark_id: "b1" }));
    expect(mockChain).not.toHaveBeenCalled();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mockIndexConfig.mockResolvedValue({ default_suite_ids: [], suites: [] });
    mockEndpoints.mockResolvedValue([
      { id: "e1", name: "Local", enabled: true, default_model: "demo" },
    ]);
    mockBenchmarks.mockResolvedValue([
      { id: "b1", name: "Bench", enabled_prompt_count: 5, version: "1.0.0" },
    ]);
    mockCreate.mockResolvedValue({ id: "r1" });
    mockChain.mockResolvedValue([{ id: "r1" }, { id: "r2" }]);
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
    await userEvent.click(screen.getByRole("checkbox", { name: /Hermes \(15 prompts\)/ }));
    expect(screen.getByText(/automatically use native API calls/)).toBeInTheDocument();
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
    // Comboboxes: target endpoint, target model, judge endpoint, judge model.
    const selects = screen.getAllByRole("combobox");
    await userEvent.click(screen.getByRole("checkbox", { name: /Bench \(5 prompts\)/ }));
    await userEvent.selectOptions(selects[0], "e1");
    await userEvent.selectOptions(selects[2], "e1");
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
    await userEvent.click(screen.getByRole("checkbox", { name: /Bench \(5 prompts\)/ }));
    await userEvent.selectOptions(selects[0], "e1");
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
    await userEvent.click(screen.getByRole("checkbox", { name: /Bench \(5 prompts\)/ }));
    await userEvent.selectOptions(selects[0], "e1");
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
    await userEvent.click(screen.getByRole("checkbox", { name: /Bench \(5 prompts\)/ }));
    await userEvent.selectOptions(selects[0], "e1");
    await waitFor(() => {
      expect(screen.queryByDisplayValue("laguna")).not.toBeInTheDocument();
    });
    const modelInput = screen.getByPlaceholderText("model name") as HTMLInputElement;
    expect(modelInput.value).toBe("");
  });
});
