import { NavLink, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import Dashboard from "@/pages/Dashboard";
import Endpoints from "@/pages/Endpoints";
import BenchmarkLibrary from "@/pages/BenchmarkLibrary";
import BenchmarkEditor from "@/pages/BenchmarkEditor";
import NewRun from "@/pages/NewRun";
import ActiveRun from "@/pages/ActiveRun";
import Results from "@/pages/Results";
import Compare from "@/pages/Compare";
import Leaderboards from "@/pages/Leaderboards";
import SettingsPage from "@/pages/Settings";

const navItems = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/endpoints", label: "Endpoints" },
  { to: "/benchmarks", label: "Benchmarks" },
  { to: "/runs/new", label: "New Run" },
  { to: "/runs", label: "Runs" },
  { to: "/compare", label: "Compare" },
  { to: "/leaderboards", label: "Leaderboards" },
  { to: "/settings", label: "Settings" },
];

export default function App() {
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: api.health });
  return (
    <div className="min-h-full flex">
      <aside className="w-56 flex-shrink-0 border-r border-border bg-bg-panel flex flex-col">
        <div className="px-4 py-4 border-b border-border">
          <div className="text-white font-semibold leading-tight">LocalBench Studio</div>
          <div className="text-xs text-gray-500 mt-0.5">
            {health ? `v${health.version}` : "loading…"}
          </div>
        </div>
        <nav className="flex-1 p-2 space-y-0.5">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `block px-3 py-2 rounded-md text-sm transition-colors ${
                  isActive ? "bg-bg-elev text-white" : "text-gray-400 hover:text-gray-200 hover:bg-bg-elev/60"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-3 border-t border-border text-xs text-gray-500">
          {health && (
            <>
              <div className="truncate" title={health.data_dir}>
                Data: {health.data_dir}
              </div>
              <div className="mt-1">{health.frontend_built ? "Production build" : "Dev server"}</div>
            </>
          )}
        </div>
      </aside>
      <main className="flex-1 min-w-0 p-6 max-w-[1400px] mx-auto w-full">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/endpoints" element={<Endpoints />} />
          <Route path="/endpoints/:id" element={<Endpoints />} />
          <Route path="/benchmarks" element={<BenchmarkLibrary />} />
          <Route path="/benchmarks/:id" element={<BenchmarkEditor />} />
          <Route path="/runs/new" element={<NewRun />} />
          <Route path="/runs/active/:id" element={<ActiveRun />} />
          <Route path="/runs/:id" element={<ActiveRun />} />
          <Route path="/runs/:id/results" element={<Results />} />
          <Route path="/runs" element={<RunListPage />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/leaderboards" element={<Leaderboards />} />
          <Route path="/leaderboards/:suiteId" element={<Leaderboards />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}

function RunListPage() {
  // Reuse ActiveRun list view via a lightweight inline list.
  return <ActiveRunList />;
}

import { useQuery as useQ, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fmtScore, fmtRelative, fmtDuration, runDurationSeconds, STATUS_LABELS, statusColor, isTerminal } from "@/lib/format";
import { Card, PageHeader, Spinner, EmptyState, Badge, ConfirmButton } from "@/components/ui";
import { useToast } from "@/store/toast";
import type { RunSummary } from "@/types";

function ActiveRunList() {
  const { data, isLoading } = useQ({ queryKey: ["runs"], queryFn: api.listRuns });
  const qc = useQueryClient();
  const toast = useToast();
  const remove = (id: string) =>
    api.deleteRun(id)
      .then(() => { qc.invalidateQueries({ queryKey: ["runs"] }); toast("Run deleted", "success"); })
      .catch((e: Error) => toast(e.message, "error"));
  const failedCount = (data || []).filter((r) => r.status === "failed").length;
  const clearFailed = () =>
    api.clearFailedRuns()
      .then((res) => { qc.invalidateQueries({ queryKey: ["runs"] }); toast(`Cleared ${res.deleted} failed run${res.deleted === 1 ? "" : "s"}`, "success"); })
      .catch((e: Error) => toast(e.message, "error"));
  return (
    <div>
      <PageHeader
        title="Runs"
        subtitle="All benchmark runs, most recent first."
        actions={failedCount > 0 ? (
          <ConfirmButton
            message={`Delete all ${failedCount} failed run${failedCount === 1 ? "" : "s"}? This cannot be undone.`}
            confirmLabel="Clear failed"
            onConfirm={clearFailed}
          >
            <span className="text-err">Clear failed ({failedCount})</span>
          </ConfirmButton>
        ) : undefined}
      />
      {isLoading ? (
        <Spinner label="Loading runs…" />
      ) : !data || data.length === 0 ? (
        <EmptyState title="No runs yet" hint="Create a benchmark run from the New Run page." />
      ) : (
        <Card className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-bg-elev text-gray-400 text-xs uppercase">
              <tr>
                <th className="text-left px-4 py-2">Name</th>
                <th className="text-left px-4 py-2">Model</th>
                <th className="text-left px-4 py-2">Status</th>
                <th className="text-right px-4 py-2">Quality</th>
                <th className="text-right px-4 py-2">Reliability</th>
                <th className="text-right px-4 py-2">Performance</th>
                <th className="text-right px-4 py-2" title="Wall-clock time from run start to finish, including warm-up, grading, retries and any pauses">Total time</th>
                <th className="text-left px-4 py-2">Created</th>
                <th className="text-right px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {data.map((r: RunSummary) => (
                <tr key={r.id} className="border-t border-border hover:bg-bg-elev/40">
                  <td className="px-4 py-2">
                    <Link to={`/runs/${r.id}`} className="text-white hover:text-accent">
                      {r.name}
                    </Link>
                    {r.benchmark_name && <div className="text-xs text-gray-500">{r.benchmark_name}</div>}
                  </td>
                  <td className="px-4 py-2 text-gray-300 mono">{r.target_model}</td>
                  <td className="px-4 py-2">
                    <Badge className={statusColor(r.status)}>{STATUS_LABELS[r.status] || r.status}</Badge>
                  </td>
                  <td className="px-4 py-2 text-right mono">{fmtScore(r.quality_score)}</td>
                  <td className="px-4 py-2 text-right mono">{fmtScore(r.reliability_score)}</td>
                  <td className="px-4 py-2 text-right mono">{fmtScore(r.performance_index)}</td>
                  <td className="px-4 py-2 text-right mono whitespace-nowrap">{fmtDuration(runDurationSeconds(r))}</td>
                  <td className="px-4 py-2 text-gray-400" title={r.created_at}>
                    {fmtRelative(r.created_at)}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {isTerminal(r.status) ? (
                      <ConfirmButton
                        message={`Delete run '${r.name}' and its results? This cannot be undone.`}
                        confirmLabel="Delete"
                        onConfirm={() => remove(r.id)}
                      >
                        <span className="text-err">Delete</span>
                      </ConfirmButton>
                    ) : (
                      <span className="text-xs text-gray-600" title="Cancel the run before deleting">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
