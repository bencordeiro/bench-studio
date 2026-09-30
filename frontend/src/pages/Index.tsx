import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Card, EmptyState, PageHeader, Spinner } from "@/components/ui";
import { fmtRelative, fmtScore, scoreColor } from "@/lib/format";
import type { LeaderboardBasis } from "@/types";

const BASIS_LABELS: Record<LeaderboardBasis, string> = {
  latest: "Latest run", best: "Best run", mean: "Mean of runs",
};

export default function IndexPage() {
  const [basis, setBasis] = useState<LeaderboardBasis>("latest");
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["index", basis], queryFn: () => api.getIndex(basis), refetchInterval: 10000,
  });
  return (
    <div>
      <PageHeader title="Index"
        subtitle="An equal-weight average of quality scores across your selected benchmarks."
        actions={<Link to="/settings#index-settings" className="btn">Configure Index</Link>} />
      <Card className="mb-4">
        <p className="text-sm text-gray-300">Only models with completed, fully scored runs for every selected benchmark appear. Failed generations count as zero within a completed run.</p>
        <p className="text-xs text-gray-500 mt-2">Each benchmark contributes equally, regardless of its question count. The basis applies separately to each benchmark.</p>
        <div className="flex flex-wrap gap-2 mt-3" role="group" aria-label="Index scoring basis">
          {(Object.keys(BASIS_LABELS) as LeaderboardBasis[]).map((value) => (
            <button key={value} className={`btn text-xs ${basis === value ? "btn-primary" : "btn-ghost"}`}
              aria-pressed={basis === value} onClick={() => setBasis(value)}>{BASIS_LABELS[value]}</button>
          ))}
        </div>
        {data && (
          <div className="mt-3 text-xs text-gray-400">
            <p>{data.suites.length} selected benchmarks · {data.entries.length} eligible models</p>
            {data.incomplete_model_count > 0 && <p className="mt-1">{data.incomplete_model_count} models are excluded until all selected benchmarks are completed and scored.</p>}
            <ul className="flex flex-wrap gap-x-4 gap-y-1 mt-2">
              {data.suites.map((suite, i) => (
                <li key={suite.id || i}>{suite.missing ? <span className="text-warn">{suite.name} (missing)</span> :
                  <Link to={`/leaderboards/${suite.id}`} className="hover:text-white">{suite.name}</Link>}</li>
              ))}
            </ul>
          </div>
        )}
      </Card>
      {isLoading && <Spinner label="Loading Index…" />}
      {isError && <EmptyState title="Could not load Index" hint={(error as Error).message} />}
      {data && data.warnings.length > 0 && (
        <Card className="mb-4 border-warn/40">
          <ul className="text-xs text-warn list-disc pl-5">{data.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul>
        </Card>
      )}
      {data && data.entries.length === 0 && <EmptyState
        title={data.suites.length ? "No models have completed the full Index yet" : "No Index benchmarks selected"}
        hint={data.suites.length ? "Complete all selected benchmarks for a model to include it here." : "Choose benchmarks in Settings."} />}
      {data && data.entries.length > 0 && (
        <Card className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-bg-elev text-gray-400 text-xs uppercase">
              <tr>
                <th className="text-right px-3 py-2">#</th>
                <th className="text-left px-3 py-2">Model</th>
                <th className="text-right px-3 py-2">Index score</th>
                {data.suites.map((suite, i) => <th key={suite.id || i} className="text-right px-3 py-2 min-w-32">{suite.name}</th>)}
                <th className="text-right px-3 py-2">Runs</th>
                <th className="text-left px-3 py-2">Last run</th>
              </tr>
            </thead>
            <tbody>
              {data.entries.map((entry) => (
                <tr key={entry.model} className="border-t border-border hover:bg-bg-elev/40">
                  <td className="text-right px-3 py-2 text-gray-500 mono">{entry.rank}</td>
                  <td className="px-3 py-2"><div className="text-white mono">{entry.model}</div>
                    <div className="text-xs text-gray-500">{entry.target_endpoint_names.join(", ")}</div></td>
                  <td className={`px-3 py-2 text-right font-semibold mono ${scoreColor(entry.index_score)}`}>{fmtScore(entry.index_score)}</td>
                  {entry.suite_scores.map((score, i) => <td key={score.suite_id || i} className="px-3 py-2 text-right mono">
                    {score.representative_run_id ? <Link to={`/runs/${score.representative_run_id}/results`}
                      title={basis === "mean" ? "View the latest contributing run" : "View the contributing run"}
                      className={`${scoreColor(score.score)} hover:underline`}>{fmtScore(score.score)}</Link> : "—"}
                  </td>)}
                  <td className="px-3 py-2 text-right mono text-gray-400">{entry.run_count}</td>
                  <td className="px-3 py-2 text-xs text-gray-400">{entry.last_run_at ? fmtRelative(entry.last_run_at) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
