import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { Card, EmptyState, PageHeader, Spinner, StatCard, Badge } from "@/components/ui";
import { fmtScore, fmtRelative, STATUS_LABELS, statusColor, GRADING_MODE_LABELS, hasResults, isTerminal } from "@/lib/format";

export default function Dashboard() {
  const { data: runs, isLoading: runsLoading } = useQuery({ queryKey: ["runs"], queryFn: api.listRuns });
  const { data: benchmarks } = useQuery({ queryKey: ["benchmarks"], queryFn: api.listBenchmarks });
  const { data: endpoints } = useQuery({ queryKey: ["endpoints"], queryFn: api.listEndpoints });

  const completed = (runs || []).filter((r) => hasResults(r.status));
  const active = (runs || []).find((r) => !isTerminal(r.status));
  const totalPrompts = (benchmarks || []).reduce((acc, b) => acc + b.prompt_count, 0);
  const highest = completed
    .filter((r) => r.quality_score !== null)
    .sort((a, b) => (b.quality_score || 0) - (a.quality_score || 0))[0];
  const mostReliable = completed
    .filter((r) => r.reliability_score !== null)
    .sort((a, b) => (b.reliability_score || 0) - (a.reliability_score || 0))[0];
  const fastest = completed
    .filter((r) => r.performance_index !== null)
    .sort((a, b) => (b.performance_index || 0) - (a.performance_index || 0))[0];
  const recentFailures = (runs || []).filter((r) => r.status === "failed").slice(0, 5);

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="Overview of benchmarks, runs, and recent activity."
        actions={
          <Link to="/runs/new" className="btn btn-primary">
            + New Run
          </Link>
        }
      />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Benchmark sets" value={benchmarks?.length ?? "—"} />
        <StatCard label="Saved prompts" value={totalPrompts} />
        <StatCard label="Endpoint profiles" value={endpoints?.length ?? "—"} />
        <StatCard label="Completed runs" value={completed.length} />
      </div>

      {active && (
        <Card className="mb-6">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-500">Active run</div>
              <Link to={`/runs/${active.id}`} className="text-white font-medium hover:text-accent">
                {active.name}
              </Link>
            </div>
            <Badge className={statusColor(active.status)}>{STATUS_LABELS[active.status] || active.status}</Badge>
          </div>
          <div className="mt-3 text-sm text-gray-400">
            {active.completed_prompts} / {active.total_prompts} prompts • {active.target_model}
          </div>
        </Card>
      )}

      <div className="grid md:grid-cols-3 gap-4 mb-6">
        <Card>
          <div className="text-xs uppercase tracking-wide text-gray-500 mb-2">Highest quality</div>
          {highest ? (
            <Link to={`/runs/${highest.id}/results`} className="block">
              <div className="text-2xl font-semibold text-white">{fmtScore(highest.quality_score)}</div>
              <div className="text-sm text-gray-400 mt-1 truncate mono">{highest.target_model}</div>
            </Link>
          ) : (
            <p className="text-gray-500 text-sm">No completed runs yet.</p>
          )}
        </Card>
        <Card>
          <div className="text-xs uppercase tracking-wide text-gray-500 mb-2">Most reliable</div>
          {mostReliable ? (
            <Link to={`/runs/${mostReliable.id}/results`} className="block">
              <div className="text-2xl font-semibold text-white">{fmtScore(mostReliable.reliability_score)}</div>
              <div className="text-sm text-gray-400 mt-1 truncate mono">{mostReliable.target_model}</div>
            </Link>
          ) : (
            <p className="text-gray-500 text-sm">No completed runs yet.</p>
          )}
        </Card>
        <Card>
          <div className="text-xs uppercase tracking-wide text-gray-500 mb-2">Fastest recent</div>
          {fastest ? (
            <Link to={`/runs/${fastest.id}/results`} className="block">
              <div className="text-2xl font-semibold text-white">{fmtScore(fastest.performance_index)}</div>
              <div className="text-sm text-gray-400 mt-1 truncate mono">{fastest.target_model}</div>
            </Link>
          ) : (
            <p className="text-gray-500 text-sm">No completed runs yet.</p>
          )}
        </Card>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <Card>
          <h2 className="font-semibold text-white mb-3">Recent runs</h2>
          {runsLoading ? (
            <Spinner label="Loading…" />
          ) : !runs || runs.length === 0 ? (
            <EmptyState title="No runs yet" />
          ) : (
            <ul className="divide-y divide-border">
              {runs.slice(0, 6).map((r) => (
                <li key={r.id} className="py-2 flex items-center justify-between">
                  <Link to={`/runs/${r.id}`} className="text-sm text-gray-200 hover:text-accent truncate">
                    {r.name} <span className="text-gray-500 mono">· {r.target_model}</span>
                  </Link>
                  <div className="flex items-center gap-2">
                    <Badge className={statusColor(r.status)}>{STATUS_LABELS[r.status] || r.status}</Badge>
                    <span className="text-xs text-gray-500">{fmtRelative(r.created_at)}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <h2 className="font-semibold text-white mb-3">Recent failures</h2>
          {recentFailures.length === 0 ? (
            <p className="text-gray-500 text-sm">No failures recorded.</p>
          ) : (
            <ul className="divide-y divide-border">
              {recentFailures.map((r) => (
                <li key={r.id} className="py-2">
                  <Link to={`/runs/${r.id}`} className="text-sm text-err hover:underline">
                    {r.name}
                  </Link>
                  <div className="text-xs text-gray-500">{fmtRelative(r.created_at)}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card className="mt-4">
        <h2 className="font-semibold text-white mb-3">Benchmark library</h2>
        {!benchmarks || benchmarks.length === 0 ? (
          <EmptyState title="No benchmarks" hint="Create one or import a benchmark file." />
        ) : (
          <ul className="divide-y divide-border">
            {benchmarks.slice(0, 6).map((b) => (
              <li key={b.id} className="py-2 flex items-center justify-between">
                <Link to={`/benchmarks/${b.id}`} className="text-sm text-gray-200 hover:text-accent">
                  {b.name} {b.is_example && <span className="text-xs text-gray-500">(example)</span>}
                </Link>
                <div className="text-xs text-gray-500">
                  {b.enabled_prompt_count} prompts · v{b.version}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
