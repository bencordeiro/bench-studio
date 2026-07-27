import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Badge, Card, EmptyState, PageHeader, Spinner } from "@/components/ui";
import { fmtScore, fmtRelative, scoreColor } from "@/lib/format";
import type {
  LeaderboardBasis,
  LeaderboardEntry,
  LeaderboardSort,
  LeaderboardSuiteSummary,
} from "@/types";

const BASIS_LABELS: Record<LeaderboardBasis, string> = {
  best: "Best run",
  mean: "Mean of runs",
  latest: "Latest run",
};

export default function Leaderboards() {
  const { suiteId } = useParams<{ suiteId: string }>();
  return suiteId ? <SuiteLeaderboard suiteId={suiteId} /> : <SuitePicker />;
}

// --------------------------------------------------------------------------- //
// Suite picker
// --------------------------------------------------------------------------- //
function SuitePicker() {
  const { data, isLoading } = useQuery({
    queryKey: ["leaderboards"],
    queryFn: api.listLeaderboardSuites,
  });

  return (
    <div>
      <PageHeader
        title="Leaderboards"
        subtitle="Ranked models per benchmark suite. Enable a suite in its editor to list it here."
      />
      {isLoading ? (
        <Spinner label="Loading suites…" />
      ) : !data || data.length === 0 ? (
        <EmptyState
          title="No suites enabled for leaderboards"
          hint="Open a benchmark's metadata and turn on “Show in leaderboards.”"
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {data.map((s: LeaderboardSuiteSummary) => (
            <Link
              key={s.suite_id}
              to={`/leaderboards/${s.suite_id}`}
              className="panel p-4 hover:border-accent/60 transition-colors block"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="text-white font-medium">{s.suite_name}</div>
                <Badge className="text-gray-400 border-border bg-bg-elev">v{s.suite_version}</Badge>
              </div>
              <div className="mt-3 text-sm text-gray-400">
                {s.model_count} model{s.model_count === 1 ? "" : "s"} · {s.run_count} run
                {s.run_count === 1 ? "" : "s"}
              </div>
              {s.top_model ? (
                <div className="mt-2 text-sm">
                  <span className="text-gray-500">Top: </span>
                  <span className="text-gray-200 mono">{s.top_model}</span>
                  <span className={`ml-2 mono ${scoreColor(s.top_quality_score)}`}>
                    {fmtScore(s.top_quality_score)}
                  </span>
                </div>
              ) : (
                <div className="mt-2 text-sm text-gray-500">No completed runs yet</div>
              )}
              <div className="mt-2 text-xs text-gray-500">
                {s.last_run_at ? `Last run ${fmtRelative(s.last_run_at)}` : "—"}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Per-suite leaderboard
// --------------------------------------------------------------------------- //
function SuiteLeaderboard({ suiteId }: { suiteId: string }) {
  const navigate = useNavigate();
  const [basis, setBasis] = useState<LeaderboardBasis>("best");
  const [sort, setSort] = useState<LeaderboardSort>("quality");
  const [selected, setSelected] = useState<string[]>([]);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["leaderboard", suiteId, basis, sort],
    queryFn: () => api.getLeaderboard(suiteId, basis, sort),
  });

  const toggle = (model: string) =>
    setSelected((cur) => (cur.includes(model) ? cur.filter((m) => m !== model) : [...cur, model]));

  // Map each selected model to the run its ranking reflects (basis-aware).
  const compareIds = useMemo(() => {
    if (!data) return [];
    return selected
      .map((m) => data.entries.find((e) => e.model === m)?.representative_run_id)
      .filter((id): id is string => Boolean(id));
  }, [selected, data]);

  const goCompare = () => {
    if (compareIds.length >= 2) {
      navigate(`/compare?${compareIds.map((i) => `ids=${i}`).join("&")}`);
    }
  };

  return (
    <div>
      <PageHeader
        title={data ? data.suite_name : "Leaderboard"}
        subtitle={data ? `v${data.suite_version} · ${data.total_runs} eligible run${data.total_runs === 1 ? "" : "s"}` : undefined}
        actions={
          <Link to="/leaderboards" className="btn btn-ghost">
            ← All suites
          </Link>
        }
      />

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="flex items-center gap-1" role="group" aria-label="Scoring basis">
          <span className="text-xs uppercase tracking-wide text-gray-500 mr-1">Basis</span>
          {(Object.keys(BASIS_LABELS) as LeaderboardBasis[]).map((b) => (
            <button
              key={b}
              onClick={() => setBasis(b)}
              className={`btn text-xs ${basis === b ? "btn-primary" : "btn-ghost"}`}
            >
              {BASIS_LABELS[b]}
            </button>
          ))}
        </div>
        {selected.length >= 2 && (
          <button className="btn btn-primary text-xs ml-auto" onClick={goCompare}>
            Compare {selected.length} models →
          </button>
        )}
      </div>

      {isLoading && <Spinner label="Loading leaderboard…" />}
      {isError && (
        <EmptyState title="Could not load leaderboard" hint={(error as Error)?.message} />
      )}

      {data && data.warnings.length > 0 && (
        <Card className="border-warn/40 mb-4">
          <h3 className="text-sm font-medium text-warn mb-1">Comparability warnings</h3>
          <ul className="list-disc pl-5 text-xs text-warn">
            {data.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Card>
      )}

      {data && data.entries.length === 0 ? (
        <EmptyState title="No completed runs on this suite yet" hint="Run a benchmark against this suite to populate the leaderboard." />
      ) : (
        data && (
          <Card className="p-0 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-bg-elev text-gray-400 text-xs uppercase">
                <tr>
                  <th className="w-8 px-3 py-2"></th>
                  <th className="text-right px-2 py-2">#</th>
                  <th className="text-left px-3 py-2">Model</th>
                  <SortHeader label="Quality" metric="quality" sort={sort} onSort={setSort} />
                  <SortHeader label="Performance" metric="performance" sort={sort} onSort={setSort} />
                  <SortHeader label="Reliability" metric="reliability" sort={sort} onSort={setSort} />
                  <SortHeader label="Composite" metric="composite" sort={sort} onSort={setSort} />
                  <th className="text-right px-3 py-2">Runs</th>
                  <th className="text-left px-3 py-2">Last run</th>
                </tr>
              </thead>
              <tbody>
                {data.entries.map((e: LeaderboardEntry) => (
                  <tr key={e.model} className="border-t border-border hover:bg-bg-elev/40">
                    <td className="px-3 py-2 text-center">
                      <input
                        type="checkbox"
                        checked={selected.includes(e.model)}
                        onChange={() => toggle(e.model)}
                        aria-label={`Select ${e.model} for comparison`}
                      />
                    </td>
                    <td className="px-2 py-2 text-right text-gray-500 mono">{e.rank}</td>
                    <td className="px-3 py-2">
                      <div className="text-gray-100 mono">{e.model}</div>
                      {e.target_endpoint_names.length > 0 && (
                        <div className="text-xs text-gray-500">{e.target_endpoint_names.join(", ")}</div>
                      )}
                    </td>
                    <ScoreCell value={e.quality_score} active={sort === "quality"} />
                    <ScoreCell value={e.performance_index} active={sort === "performance"} />
                    <ScoreCell value={e.reliability_score} active={sort === "reliability"} />
                    <ScoreCell value={e.composite_score} active={sort === "composite"} />
                    <td className="px-3 py-2 text-right text-gray-400 mono">{e.run_count}</td>
                    <td className="px-3 py-2 text-gray-400 text-xs" title={e.last_run_at || ""}>
                      {e.last_run_at ? fmtRelative(e.last_run_at) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )
      )}
    </div>
  );
}

function SortHeader({
  label,
  metric,
  sort,
  onSort,
}: {
  label: string;
  metric: LeaderboardSort;
  sort: LeaderboardSort;
  onSort: (m: LeaderboardSort) => void;
}) {
  const active = sort === metric;
  return (
    <th className="text-right px-3 py-2">
      <button
        onClick={() => onSort(metric)}
        className={`inline-flex items-center gap-1 hover:text-gray-200 ${active ? "text-white" : ""}`}
        aria-pressed={active}
      >
        {label}
        {active && <span aria-hidden>▼</span>}
      </button>
    </th>
  );
}

function ScoreCell({ value, active }: { value: number | null; active: boolean }) {
  return (
    <td className={`px-3 py-2 text-right mono ${scoreColor(value)} ${active ? "font-semibold" : ""}`}>
      {fmtScore(value)}
    </td>
  );
}
