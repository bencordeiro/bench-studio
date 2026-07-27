import type {
  AppSettings,
  BenchmarkSet,
  BenchmarkSetSummary,
  ConnectionTestResult,
  EndpointProfile,
  FetchModelsResult,
  HealthResponse,
  LeaderboardBasis,
  LeaderboardResponse,
  LeaderboardSort,
  LeaderboardSuiteSummary,
  RunResponse,
  RunResults,
  RunSummary,
} from "@/types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // ignore parse errors
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return (await res.json()) as T;
  return (await res.text()) as unknown as T;
}

export const api = {
  health: () => request<HealthResponse>("/api/health"),
  diagnostics: () => request<Record<string, unknown>>("/api/diagnostics"),

  // Settings
  getSettings: () => request<AppSettings>("/api/settings"),
  updateSettings: (s: AppSettings) =>
    request<AppSettings>("/api/settings", { method: "PUT", body: JSON.stringify(s) }),

  // Endpoints
  listEndpoints: () => request<EndpointProfile[]>("/api/endpoints"),
  getEndpoint: (id: string) => request<EndpointProfile>(`/api/endpoints/${id}`),
  createEndpoint: (data: Partial<EndpointProfile> & { api_key?: string }) =>
    request<EndpointProfile>("/api/endpoints", { method: "POST", body: JSON.stringify(data) }),
  updateEndpoint: (id: string, data: Partial<EndpointProfile> & { api_key?: string }) =>
    request<EndpointProfile>(`/api/endpoints/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteEndpoint: (id: string) =>
    request<void>(`/api/endpoints/${id}`, { method: "DELETE" }),
  duplicateEndpoint: (id: string) =>
    request<EndpointProfile>(`/api/endpoints/${id}/duplicate`, { method: "POST" }),
  testEndpoint: (id: string) =>
    request<ConnectionTestResult>(`/api/endpoints/${id}/test`, { method: "POST" }),
  fetchModels: (id: string) =>
    request<FetchModelsResult>(`/api/endpoints/${id}/models`, { method: "POST" }),

  // Benchmarks
  listBenchmarks: () => request<BenchmarkSetSummary[]>("/api/benchmarks"),
  getBenchmark: (id: string) => request<BenchmarkSet>(`/api/benchmarks/${id}`),
  createBenchmark: (data: Partial<BenchmarkSet>) =>
    request<BenchmarkSet>("/api/benchmarks", { method: "POST", body: JSON.stringify(data) }),
  updateBenchmark: (id: string, data: Partial<BenchmarkSet>) =>
    request<BenchmarkSet>(`/api/benchmarks/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteBenchmark: (id: string) => request<void>(`/api/benchmarks/${id}`, { method: "DELETE" }),
  duplicateBenchmark: (id: string) =>
    request<BenchmarkSet>(`/api/benchmarks/${id}/duplicate`, { method: "POST" }),
  exportBenchmarkUrl: (id: string) => `/api/benchmarks/${id}/export`,
  importBenchmark: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch("/api/benchmarks/import", { method: "POST", body: form }).then((r) => {
      if (!r.ok) throw new Error("Import failed");
      return r.json();
    });
  },
  savePrompt: (benchId: string, promptId: string | null, data: Partial<BenchmarkSet["prompts"][number]>) =>
    request<BenchmarkSet["prompts"][number]>(
      `/api/benchmarks/${benchId}/prompts${promptId ? `/${promptId}` : ""}`,
      { method: promptId ? "PUT" : "POST", body: JSON.stringify(data) },
    ),
  deletePrompt: (benchId: string, promptId: string) =>
    request<void>(`/api/benchmarks/${benchId}/prompts/${promptId}`, { method: "DELETE" }),
  duplicatePrompt: (benchId: string, promptId: string) =>
    request<BenchmarkSet["prompts"][number]>(
      `/api/benchmarks/${benchId}/prompts/${promptId}/duplicate`,
      { method: "POST" },
    ),
  reorderPrompts: (benchId: string, promptIds: string[]) =>
    request<BenchmarkSet>(`/api/benchmarks/${benchId}/reorder`, {
      method: "POST",
      body: JSON.stringify({ prompt_ids: promptIds }),
    }),

  // Runs
  listRuns: () => request<RunSummary[]>("/api/runs"),
  getRun: (id: string) => request<RunResponse>(`/api/runs/${id}`),
  createRun: (data: Record<string, unknown>) =>
    request<RunResponse>("/api/runs", { method: "POST", body: JSON.stringify(data) }),
  startRun: (id: string) => request<RunResponse>(`/api/runs/${id}/start`, { method: "POST" }),
  cancelRun: (id: string) => request<RunResponse>(`/api/runs/${id}/cancel`, { method: "POST" }),
  resumeRun: (id: string) => request<RunResponse>(`/api/runs/${id}/resume`, { method: "POST" }),
  deleteRun: (id: string) => request<void>(`/api/runs/${id}`, { method: "DELETE" }),
  clearFailedRuns: () => request<{ deleted: number }>(`/api/runs/clear-failed`, { method: "POST" }),
  getResults: (id: string) => request<RunResults>(`/api/runs/${id}/results`),
  exportRunUrl: (id: string, fmt: "json" | "csv" | "html") => `/api/runs/${id}/export/${fmt}`,
  addManualGrade: (execId: string, data: { score: number; notes: string }) =>
    request<unknown>(`/api/runs/executions/${execId}/manual`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  compareRuns: (ids: string[]) =>
    request<{ runs: Record<string, unknown>[]; per_prompt: unknown[]; warnings: string[] }>(
      `/api/runs/compare?${ids.map((i) => `ids=${i}`).join("&")}`,
    ),

  // Leaderboards
  listLeaderboardSuites: () =>
    request<LeaderboardSuiteSummary[]>("/api/leaderboards"),
  getLeaderboard: (suiteId: string, basis: LeaderboardBasis = "best", sort: LeaderboardSort = "quality") =>
    request<LeaderboardResponse>(
      `/api/leaderboards/${suiteId}?basis=${basis}&sort=${sort}`,
    ),
};
