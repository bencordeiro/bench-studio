export function fmtScore(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

export function fmtMs(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v < 1) return `${(v * 1000).toFixed(0)} ms`;
  return `${v.toFixed(2)} s`;
}

export function fmtTokens(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v < 1000) return v.toString();
  return `${(v / 1000).toFixed(1)}k`;
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString();
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso).getTime();
  if (Number.isNaN(d)) return "—";
  const diff = Date.now() - d;
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  return `${day}d ago`;
}

export const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  preparing: "Preparing",
  warming_up: "Warming up",
  running_target: "Running target",
  running_deterministic: "Grading (deterministic)",
  running_judge: "Grading (judge)",
  running_verifier: "Verifying",
  completed: "Completed",
  completed_with_errors: "Completed with errors",
  cancel_requested: "Cancel requested",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
  failed: "Failed",
  pending: "Pending",
  running: "Running",
  skipped: "Skipped",
  awaiting_judge: "Awaiting judge",
  awaiting_manual: "Awaiting manual review",
};

export const GRADING_MODE_LABELS: Record<string, string> = {
  deterministic: "Deterministic",
  judge: "LLM Judge",
  hybrid: "Hybrid",
  manual: "Manual review",
  execution: "Execution (code tests)",
};

export function statusColor(status: string): string {
  if (["completed"].includes(status)) return "text-ok border-ok/40 bg-ok/10";
  if (["completed_with_errors", "awaiting_manual", "awaiting_judge", "interrupted", "cancel_requested"].includes(status))
    return "text-warn border-warn/40 bg-warn/10";
  if (["failed", "cancelled"].includes(status)) return "text-err border-err/40 bg-err/10";
  if (status.startsWith("running") || status === "preparing" || status === "warming_up" || status === "running")
    return "text-accent border-accent/40 bg-accent/10";
  return "text-gray-400 border-border bg-bg-elev";
}

export function isTerminal(status: string): boolean {
  return ["completed", "completed_with_errors", "cancelled", "failed"].includes(status);
}

/** Run finished with scorable results (mirrors backend COMPLETED_STATUSES). */
export function hasResults(status: string): boolean {
  return status === "completed" || status === "completed_with_errors";
}

/** Traffic-light text color for a 0-100 score; gray for missing. */
export function scoreColor(s: number | null | undefined): string {
  if (s === null || s === undefined) return "text-gray-500";
  if (s >= 70) return "text-ok";
  if (s >= 40) return "text-warn";
  return "text-err";
}

export function approxTokens(text: string): number {
  if (!text) return 0;
  return Math.max(1, Math.ceil(text.length / 4));
}

/** Format a USD cost value. Returns "—" for null/undefined, appropriate precision otherwise. */
export function fmtCost(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v === 0) return "$0.00";
  if (v < 0.0001) return `$${v.toFixed(6)}`;
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}
