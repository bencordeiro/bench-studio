import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import Endpoints from "@/pages/Endpoints";

const { mockList, mockCreate } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockCreate: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  api: {
    listEndpoints: () => mockList(),
    createEndpoint: (data: unknown) => mockCreate(data),
    testEndpoint: vi.fn(),
    fetchModels: vi.fn(),
  },
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Endpoints />
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

describe("Endpoints form validation", () => {
  beforeEach(() => {
    mockList.mockResolvedValue([]);
    mockCreate.mockResolvedValue({ id: "1", name: "x" });
  });

  it("requires a name and base URL before saving", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("+ New Endpoint")).toBeInTheDocument());
    await userEvent.click(screen.getByText("+ New Endpoint"));
    await userEvent.click(screen.getByText("Save"));

    await waitFor(() => {
      expect(mockCreate).not.toHaveBeenCalled();
    });
  });

  it("disables save when custom-headers JSON is invalid", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("+ New Endpoint")).toBeInTheDocument());
    await userEvent.click(screen.getByText("+ New Endpoint"));

    // All text inputs: name, base_url, default_model, env var, then notes,
    // then the two JSON textareas (custom_headers, extra_body_params).
    const inputs = await screen.findAllByRole("textbox");
    // The custom-headers textarea is the first one pre-filled with "{}".
    const headersBox = inputs.find((el) => (el as HTMLTextAreaElement).value === "{}") as HTMLTextAreaElement;
    expect(headersBox).toBeTruthy();
    await userEvent.clear(headersBox);
    await userEvent.type(headersBox, "not valid json");

    const saveButtons = screen.getAllByText("Save");
    const modalSave = saveButtons[saveButtons.length - 1] as HTMLButtonElement;
    // The save button is disabled while JSON is invalid.
    await waitFor(() => expect(modalSave).toBeDisabled());
    expect(mockCreate).not.toHaveBeenCalled();
  });
});
