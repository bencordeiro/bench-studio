import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import SettingsPage from "@/pages/Settings";
import type { AppSettings } from "@/types";

const { mockSettings, mockSave, mockConfig, mockBenchmarks } = vi.hoisted(() => ({
  mockSettings: vi.fn(), mockSave: vi.fn(), mockConfig: vi.fn(), mockBenchmarks: vi.fn(),
}));
vi.mock("@/api/client", () => ({ api: {
  getSettings: () => mockSettings(), updateSettings: (data: AppSettings) => mockSave(data),
  getIndexConfig: () => mockConfig(), listBenchmarks: () => mockBenchmarks(), diagnostics: async () => null,
} }));

const defaults: AppSettings = {
  index_suite_ids: null, local_data_path: "/data", log_level: "INFO", default_timeout: 60,
  default_retry_max_attempts: 3, default_retry_backoff_base: 0.5, default_retry_backoff_max: 30,
  default_temperature: 0, default_top_p: 1, default_max_tokens: 8192,
  composite_weights: { quality: 0.85, reliability: 0.1, performance: 0.05 },
  automatic_backup: true, launch_browser: true, theme: "dark", allow_plaintext_key_fallback: false,
  keyring_available: true,
};
let stored: AppSettings;
function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>);
}

describe("Index settings", () => {
  beforeEach(() => {
    vi.clearAllMocks(); stored = { ...defaults };
    mockSettings.mockImplementation(async () => ({ ...stored }));
    mockSave.mockImplementation(async (data: AppSettings) => { stored = { ...data }; return stored; });
    mockConfig.mockResolvedValue({ uses_defaults: true, default_suite_ids: ["py", "mini"], suites: [] });
    mockBenchmarks.mockResolvedValue([{ id: "py", name: "Python" }, { id: "mini", name: "Mini Master" }, { id: "master", name: "Master Suite" }]);
  });
  it("loads defaults, saves edited membership, and restores it on refresh", async () => {
    const page = renderPage();
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Python" })).toBeChecked());
    expect(screen.getByRole("checkbox", { name: "Mini Master" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Master Suite" })).not.toBeChecked();
    await userEvent.click(screen.getByRole("checkbox", { name: "Mini Master" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Master Suite" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockSave).toHaveBeenCalledWith(expect.objectContaining({ index_suite_ids: ["py", "master"], default_max_tokens: 8192 })));
    page.unmount(); renderPage();
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Master Suite" })).toBeChecked());
    expect(screen.getByRole("checkbox", { name: "Mini Master" })).not.toBeChecked();
  });
  it("restores curated defaults rather than selecting all suites", async () => {
    stored = { ...defaults, index_suite_ids: ["master"] };
    renderPage();
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Master Suite" })).toBeChecked());
    await userEvent.click(screen.getByRole("button", { name: "Restore seven defaults" }));
    expect(screen.getByRole("checkbox", { name: "Python" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Master Suite" })).not.toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockSave).toHaveBeenCalledWith(expect.objectContaining({ index_suite_ids: null })));
  });
});
