import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Badge, Card, EmptyState, PageHeader, Spinner } from "@/components/ui";
import { fmtScore, fmtRelative, hasResults, scoreColor } from "@/lib/format";
import type { RunSummary } from "@/types";

interface CompareData {
  runs: { id: string; name: string; target_model: string; quality_score: number | null; reliability_score: number | null; performance_index: number | null; composite_score: number | null; benchmark_version: string; benchmark_name: string }[];
  per_prompt: { key: string; label: string; scores: Record<string, number | null> }[];
  warnings: string[];
}

export default function Compare() {
  const { data: runs } = useQuery({ queryKey: ["runs"], queryFn: api.listRuns });
  const completed = (runs || []).filter((r) => hasResults(r.status));
  const [searchParams] = useSearchParams();
  // Deep-compare entry point: /compare?ids=a&ids=b preselects those runs.
  const [selected, setSelected] = useState<string[]>(() => searchParams.getAll("ids"));
  const { data: comparison, isLoading, isError, error } = useQuery({
    queryKey: ["compare", selected],
    queryFn: () => api.compareRuns(selected),
    enabled: selected.length >= 2,
  });

  const toggle = (id: string) => {
    setSelected((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  };

  // Preselected ids that aren't in the rendered list (deleted runs, or runs
  // beyond the list limit) would otherwise be stuck in the selection with no
  // way to remove them.
  const phantomIds = runs ? selected.filter((id) => !completed.some((r) => r.id === id)) : [];

  return (
    <div>
      <PageHeader title="Compare Runs" subtitle="Select two or more completed runs to compare. Warnings appear when configurations differ." />
      {completed.length < 2 ? (
        <EmptyState title="Need at least two completed runs" hint="Complete a couple of runs first." />
      ) : (
        <Card className="mb-4">
          <div className="space-y-1 max-h-60 overflow-auto">
            {completed.map((r: RunSummary) => (
              <label key={r.id} className="flex items-center gap-2 p-2 hover:bg-bg-elev/40 rounded cursor-pointer">
                <input type="checkbox" checked={selected.includes(r.id)} onChange={() => toggle(r.id)} />
                <span className="text-sm text-gray-200 flex-1">{r.name}</span>
                <span className="text-xs text-gray-500 mono">{r.target_model}</span>
                <span className="text-xs text-gray-500">{fmtRelative(r.created_at)}</span>
              </label>
            ))}
          </div>
          {phantomIds.length > 0 && (
            <div className="mt-3 pt-3 border-t border-border">
              <p className="text-xs text-warn mb-1">
                Selected runs not shown in the list above (deleted or older than the listing limit):
              </p>
              <div className="flex flex-wrap gap-1">
                {phantomIds.map((id) => (
                  <button
                    key={id}
                    className="badge text-warn border-warn/40 bg-warn/10 hover:bg-warn/20"
                    onClick={() => toggle(id)}
                    title="Remove from selection"
                  >
                    {id.slice(0, 8)}… ✕
                  </button>
                ))}
              </div>
            </div>
          )}
        </Card>
      )}

      {selected.length >= 2 && isLoading && <Spinner label="Comparing…" />}
      {isError && (
        <Card className="border-err/40">
          <p className="text-sm text-err">Comparison failed: {(error as Error).message}</p>
          <p className="text-xs text-gray-500 mt-1">
            A selected run may have been deleted — remove it from the selection and try again.
          </p>
        </Card>
      )}
      {comparison && <ComparisonView data={comparison as CompareData} />}
    </div>
  );
}

function ComparisonView({ data }: { data: CompareData }) {
  const runs = data.runs;
  return (
    <div className="space-y-4">
      {data.warnings.length > 0 && (
        <Card className="border-warn/40">
          <h3 className="text-sm font-medium text-warn mb-1">Comparability warnings</h3>
          <ul className="list-disc pl-5 text-xs text-warn">
            {data.warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
          <p className="text-xs text-gray-500 mt-1">Do not imply strict comparability when configurations differ.</p>
        </Card>
      )}
      <Card className="p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-bg-elev text-gray-400 text-xs uppercase">
            <tr>
              <th className="text-left px-3 py-2">Metric</th>
              {runs.map((r) => <th key={r.id} className="text-right px-3 py-2"><Link to={`/runs/${r.id}/results`} className="hover:text-accent">{r.name}</Link></th>)}
            </tr>
          </thead>
          <tbody>
            <MetricRow label="Quality" runs={runs} get={(r) => r.quality_score} />
            <MetricRow label="Reliability" runs={runs} get={(r) => r.reliability_score} />
            <MetricRow label="Performance" runs={runs} get={(r) => r.performance_index} />
            <MetricRow label="Composite" runs={runs} get={(r) => r.composite_score} />
            <tr className="border-t border-border">
              <td className="px-3 py-2 text-gray-500 text-xs">Benchmark version</td>
              {runs.map((r) => <td key={r.id} className="px-3 py-2 text-right text-xs mono">{r.benchmark_version}</td>)}
            </tr>
          </tbody>
        </table>
      </Card>
      {data.per_prompt.length > 0 && (
        <Card className="p-0 overflow-x-auto">
          <h3 className="text-sm font-medium text-white p-3 border-b border-border">Per-prompt scores</h3>
          <table className="w-full text-sm">
            <thead className="bg-bg-elev text-gray-400 text-xs uppercase">
              <tr>
                <th className="text-left px-3 py-2">Prompt</th>
                {runs.map((r) => <th key={r.id} className="text-right px-3 py-2">{r.target_model}</th>)}
              </tr>
            </thead>
            <tbody>
              {data.per_prompt.map((p) => (
                <tr key={p.key} className="border-t border-border">
                  <td className="px-3 py-2 text-gray-300">{p.label}</td>
                  {runs.map((r) => {
                    const v = p.scores[r.id];
                    return <td key={r.id} className={`px-3 py-2 text-right mono ${scoreColor(v)}`}>{v === null || v === undefined ? "—" : fmtScore(v)}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

function MetricRow({ label, runs, get }: { label: string; runs: CompareData["runs"]; get: (r: CompareData["runs"][number]) => number | null }) {
  const values = runs.map(get).filter((v): v is number => v !== null && v !== undefined);
  const best = values.length ? Math.max(...values) : null;
  return (
    <tr className="border-t border-border">
      <td className="px-3 py-2 text-gray-300">{label}</td>
      {runs.map((r) => {
        const v = get(r);
        const isBest = v !== null && v !== undefined && v === best && values.length > 1;
        return (
          <td key={r.id} className="px-3 py-2 text-right">
            <span className={`mono ${scoreColor(v)} ${isBest ? "font-semibold" : ""}`}>{fmtScore(v)}</span>
            {isBest && <Badge className="ml-1 text-ok border-ok/40 bg-ok/10 text-xs">best</Badge>}
          </td>
        );
      })}
    </tr>
  );
}
