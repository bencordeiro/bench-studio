import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

  it.each(["Custom headers (JSON)", "Extra body parameters (JSON)"])(
    "rejects invalid %s through the form submission handler",
    async (label) => {
      mockCreate.mockClear();
      renderPage();
      await userEvent.click(await screen.findByText("+ New Endpoint"));
      await userEvent.selectOptions(screen.getByLabelText("Provider preset"), "deepseek");
      const field = screen.getByLabelText(label);
      await userEvent.clear(field);
      await userEvent.type(field, "not valid json");

      await act(async () => {
        fireEvent.submit(field.closest("form")!);
      });

      expect(mockCreate).not.toHaveBeenCalled();
      expect(field).toHaveValue("not valid json");
      expect(screen.getByText("Save")).toBeDisabled();
    },
  );
});

it("creates a Z.ai profile using its versioned provider URL", async () => {
  mockList.mockResolvedValue([]);
  mockCreate.mockClear();
  renderPage();
  await userEvent.click(await screen.findByText("+ New Endpoint"));
  await userEvent.selectOptions(screen.getByLabelText("Provider preset"), "zai");
  expect(screen.getByLabelText("Base URL")).toHaveValue("https://api.z.ai/api/paas/v4");
  await userEvent.type(screen.getByLabelText("Default model"), "my-model-id");
  await userEvent.click(screen.getByText("Save"));
  await waitFor(() => expect(mockCreate).toHaveBeenCalledWith(expect.objectContaining({
    name: "Z.ai", base_url: "https://api.z.ai/api/paas/v4", default_model: "my-model-id", api_key_env_var: "ZAI_API_KEY", verify_tls: true,
  })));
});

it("requires an Alibaba workspace ID and rejects non-object JSON", async () => {
  mockList.mockResolvedValue([]);
  mockCreate.mockClear();
  renderPage();
  await userEvent.click(await screen.findByText("+ New Endpoint"));
  await userEvent.selectOptions(screen.getByLabelText("Provider preset"), "qwen");
  await userEvent.click(screen.getByText("Save"));
  expect(await screen.findByText("Replace the workspace placeholder with your workspace ID")).toBeInTheDocument();
  expect(mockCreate).not.toHaveBeenCalled();
  const headers = screen.getByLabelText("Custom headers (JSON)");
  await userEvent.clear(headers);
  await userEvent.type(headers, "null");
  expect(screen.getByText("Save")).toBeDisabled();
});

it("clears provider credentials when switching presets", async () => {
  mockList.mockResolvedValue([]);
  renderPage();
  await userEvent.click(await screen.findByText("+ New Endpoint"));
  await userEvent.selectOptions(screen.getByLabelText("Provider preset"), "openai");
  await userEvent.type(screen.getByLabelText("API key (write-only; never returned)"), "test-secret");
  await userEvent.selectOptions(screen.getByLabelText("Provider preset"), "deepseek");
  expect(screen.getByLabelText("API key (write-only; never returned)")).toHaveValue("");
  expect(screen.getByLabelText("API key environment variable")).toHaveValue("DEEPSEEK_API_KEY");
});
