import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import BenchmarkEditor from "@/pages/BenchmarkEditor";
import { ToastProvider } from "@/store/toast";
import type { BenchmarkSet } from "@/types";

const { mockGet, mockUpdate } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockUpdate: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  api: {
    getBenchmark: (id: string) => mockGet(id),
    updateBenchmark: (id: string, data: unknown) => mockUpdate(id, data),
    reorderPrompts: vi.fn(),
    savePrompt: vi.fn(),
    deletePrompt: vi.fn(),
    duplicatePrompt: vi.fn(),
  },
}));

const benchFixture: BenchmarkSet = {
  id: "b1",
  name: "My Suite",
  description: "desc",
  version: "1.0.0",
  tags: [],
  scoring_config: {},
  performance_thresholds: { desired_ttft: 0.5, max_ttft: 5 },
  composite_weights: { quality: 0.85, reliability: 0.1, performance: 0.05 },
  is_example: false,
  show_in_leaderboards: false,
  prompts: [],
};

function renderEditor() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/benchmarks/b1"]}>
          <Routes>
            <Route path="/benchmarks/:id" element={<BenchmarkEditor />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("BenchmarkEditor metadata: JSON-wipe guard", () => {
  beforeEach(() => {
    mockGet.mockResolvedValue(benchFixture);
    mockUpdate.mockResolvedValue(benchFixture);
  });

  it("aborts the save (no API call) and shows an error when thresholds JSON is invalid", async () => {
    renderEditor();
    await waitFor(() => expect(screen.getByText("Edit metadata")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Edit metadata"));

    await waitFor(() => expect(screen.getByText("Benchmark metadata")).toBeInTheDocument());

    // Find the thresholds box by its pre-filled JSON value (label is not
    // associated and textarea values aren't matched by getByText).
    const textareas = screen.getAllByRole("textbox");
    const thresholdsBox = textareas.find(
      (el) => (el as HTMLTextAreaElement).value.includes("desired_ttft"),
    ) as HTMLTextAreaElement;
    expect(thresholdsBox).toBeTruthy();
    await userEvent.clear(thresholdsBox);
    // Plain unparseable text (avoid '{'/'}' which userEvent.type treats as modifiers).
    await userEvent.type(thresholdsBox, "this is not json");

    // Click Save.
    const saveButtons = screen.getAllByText("Save");
    await userEvent.click(saveButtons[saveButtons.length - 1]);

    // The error toast renders in the toast region.
    await waitFor(() =>
      expect(screen.getByText(/Performance thresholds is not valid JSON/i)).toBeInTheDocument(),
    );
    // Critical assertion: the wipe path (api.updateBenchmark) must NOT have run.
    expect(mockUpdate).not.toHaveBeenCalled();
  });

  it("aborts the save when weights JSON is invalid", async () => {
    renderEditor();
    await waitFor(() => expect(screen.getByText("Edit metadata")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Edit metadata"));

    await waitFor(() => expect(screen.getByText("Benchmark metadata")).toBeInTheDocument());

    // Thresholds stays valid; corrupt weights instead. Locate the weights box
    // by its pre-filled JSON value containing "quality".
    const textareas = screen.getAllByRole("textbox");
    const weightsBox = textareas.find(
      (el) => (el as HTMLTextAreaElement).value.includes("quality"),
    ) as HTMLTextAreaElement;
    expect(weightsBox).toBeTruthy();
    await userEvent.clear(weightsBox);
    await userEvent.type(weightsBox, "not json");

    const saveButtons = screen.getAllByText("Save");
    await userEvent.click(saveButtons[saveButtons.length - 1]);

    await waitFor(() =>
      expect(screen.getByText(/Composite-score weights is not valid JSON/i)).toBeInTheDocument(),
    );
    expect(mockUpdate).not.toHaveBeenCalled();
  });

  it("saves successfully when both JSON fields are valid (preserves the stored data)", async () => {
    renderEditor();
    await waitFor(() => expect(screen.getByText("Edit metadata")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Edit metadata"));

    await waitFor(() => expect(screen.getByText("Benchmark metadata")).toBeInTheDocument());

    // Leave both JSON fields as-is (valid). Toggle the leaderboard flag while here
    // to also exercise the flag plumbing (label IS associated for the checkbox).
    await userEvent.click(screen.getByLabelText(/Show in leaderboards/i));

    const saveButtons = screen.getAllByText("Save");
    await userEvent.click(saveButtons[saveButtons.length - 1]);

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    const [, payload] = mockUpdate.mock.calls[0];
    expect(payload).toMatchObject({
      performance_thresholds: { desired_ttft: 0.5, max_ttft: 5 },
      composite_weights: { quality: 0.85, reliability: 0.1, performance: 0.05 },
      show_in_leaderboards: true,
    });
  });
});
