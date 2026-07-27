import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import PromptEditor from "@/components/PromptEditor";

describe("PromptEditor grading-mode selection", () => {
  it("renders all four grading modes", () => {
    render(
      <PromptEditor
        benchmarkId="b1"
        initial={null}
        onClose={() => {}}
        onSave={() => {}}
        submitting={false}
      />,
    );
    // The grading-mode select options include Deterministic, Judge, Hybrid, Manual.
    const selects = screen.getAllByRole("combobox");
    const gradingSelect = selects.find((s) =>
      Array.from(s.querySelectorAll("option")).some((o) => o.textContent?.includes("LLM Judge")),
    )!;
    const options = Array.from(gradingSelect.querySelectorAll("option")).map((o) => o.textContent);
    expect(options.join("|")).toMatch(/Deterministic/);
    expect(options.join("|")).toMatch(/LLM Judge/);
    expect(options.join("|")).toMatch(/Hybrid/);
    expect(options.join("|")).toMatch(/Manual review/);
  });

  it("shows the deterministic help text by default", () => {
    render(<PromptEditor benchmarkId="b1" initial={null} onClose={() => {}} onSave={() => {}} submitting={false} />);
    expect(screen.getByText(/Objective checks the computer can verify/i)).toBeInTheDocument();
  });
});
