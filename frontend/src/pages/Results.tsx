import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/api/client";
import { Badge, Card, EmptyState, Modal, PageHeader, Spinner, StatCard } from "@/components/ui";
import { useToast } from "@/store/toast";
import { GRADING_MODE_LABELS, fmtScore, fmtMs, fmtTokens, fmtCost, STATUS_LABELS, statusColor, scoreColor } from "@/lib/format";
import type { ExecutionDetail, RunResults } from "@/types";

export default function Results() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading } = useQuery({ queryKey: ["results", id], queryFn: () => api.getResults(id!), enabled: !!id });

  if (isLoading) return <Spinner label="Loading results…" />;
  if (!data) return <EmptyState title="Results not found" />;
  const { run, summary, executions, charts, coverage } = data;

  return (
    <div>
      <PageHeader
        title={`Results: ${run.name}`}
        subtitle={`${run.target_endpoint_name} · ${run.target_model}${run.judge_enabled ? ` · judge ${run.judge_model}` : ""}`}
        actions={
          <>
            <Link to={`/runs/${id}`} className="btn">Run detail</Link>
            <a className="btn" href={api.exportRunUrl(id!, "json")} download>Export JSON</a>
            <a className="btn" href={api.exportRunUrl(id!, "csv")} download>Export CSV</a>
            <a className="btn" href={api.exportRunUrl(id!, "html")} download>HTML report</a>
          </>
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-6 gap-3 mb-4">
        <StatCard label="Quality" value={fmtScore(summary.quality_score)} sub={coverage.label} />
        <StatCard label="Reliability" value={fmtScore(summary.reliability_score)} />
        <StatCard label="Performance" value={fmtScore(summary.performance_index)} />
        <StatCard label="Composite" value={fmtScore(summary.composite_score)} sub="user-configured utility" />
        <StatCard label="Cost" value={fmtCost(summary.total_cost)} />
        <StatCard label="Errors" value={String(run.failed_prompts)} />
      </div>

      <div className="grid md:grid-cols-2 gap-4 mb-4">
        <ChartCard title="Score by category">
          <CategoryChart data={(charts.score_by_category as Record<string, number>) || {}} />
        </ChartCard>
        <ChartCard title="Prompt scores">
          <PromptScoreChart data={(charts.prompt_scores as { label: string; score: number }[]) || []} />
        </ChartCard>
        <ChartCard title="Score vs latency">
          <ScatterLatency data={(charts.score_vs_latency as { x: number; y: number }[]) || []} />
        </ChartCard>
        <ChartCard title="Time-to-first-token distribution">
          <DistributionChart data={(charts.ttft_distribution as number[]) || []} label="ttft" color="#5b8def" />
        </ChartCard>
      </div>

      <ExecutionTable executions={executions} runStatus={run.status} />
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <h3 className="font-medium text-white mb-3">{title}</h3>
      <div className="h-56">{children}</div>
    </Card>
  );
}

function CategoryChart({ data }: { data: Record<string, number> }) {
  const rows = Object.entries(data).map(([name, score]) => ({ name, score }));
  if (rows.length === 0) return <Empty mini text="No category data" />;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows}>
        <CartesianGrid strokeDasharray="3 3" stroke="#2a2e36" />
        <XAxis dataKey="name" stroke="#8b919b" fontSize={11} />
        <YAxis domain={[0, 100]} stroke="#8b919b" fontSize={11} />
        <Tooltip contentStyle={{ background: "#161922", border: "1px solid #2a2e36" }} />
        <Bar dataKey="score" fill="#5b8def" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function PromptScoreChart({ data }: { data: { label: string; score: number }[] }) {
  if (data.length === 0) return <Empty mini text="No scored prompts" />;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#2a2e36" />
        <XAxis dataKey="label" stroke="#8b919b" fontSize={9} interval={0} angle={-30} textAnchor="end" height={50} />
        <YAxis domain={[0, 100]} stroke="#8b919b" fontSize={11} />
        <Tooltip contentStyle={{ background: "#161922", border: "1px solid #2a2e36" }} />
        <Bar dataKey="score" radius={[3, 3, 0, 0]}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.score >= 70 ? "#3fb950" : d.score >= 40 ? "#d29922" : "#f85149"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function ScatterLatency({ data }: { data: { x: number; y: number }[] }) {
  if (data.length === 0) return <Empty mini text="No timing data" />;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <ScatterChart>
        <CartesianGrid strokeDasharray="3 3" stroke="#2a2e36" />
        <XAxis type="number" dataKey="x" name="latency" unit="s" stroke="#8b919b" fontSize={11} />
        <YAxis type="number" dataKey="y" name="score" domain={[0, 100]} stroke="#8b919b" fontSize={11} />
        <Tooltip contentStyle={{ background: "#161922", border: "1px solid #2a2e36" }} cursor={{ strokeDasharray: "3 3" }} />
        <Scatter data={data} fill="#5b8def" />
      </ScatterChart>
    </ResponsiveContainer>
  );
}

function DistributionChart({ data, label, color }: { data: number[]; label: string; color: string }) {
  if (data.length === 0) return <Empty mini text="No data" />;
  const buckets = buildHistogram(data, 8);
  const rows = buckets.map((b) => ({ range: b.label, count: b.count }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows}>
        <CartesianGrid strokeDasharray="3 3" stroke="#2a2e36" />
        <XAxis dataKey="range" stroke="#8b919b" fontSize={10} />
        <YAxis stroke="#8b919b" fontSize={11} allowDecimals={false} />
        <Tooltip contentStyle={{ background: "#161922", border: "1px solid #2a2e36" }} />
        <Bar dataKey="count" fill={color} radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function buildHistogram(values: number[], bins: number) {
  if (!values.length) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const width = (max - min) / bins || 1;
  const out = Array.from({ length: bins }, (_, i) => ({
    label: `${(min + i * width).toFixed(2)}–${(min + (i + 1) * width).toFixed(2)}`,
    count: 0,
  }));
  for (const v of values) {
    let idx = Math.floor((v - min) / width);
    if (idx >= bins) idx = bins - 1;
    if (idx < 0) idx = 0;
    out[idx].count++;
  }
  return out;
}

function Empty({ mini, text }: { mini?: boolean; text: string }) {
  return <div className={`text-gray-500 ${mini ? "text-sm" : ""}`}>{text}</div>;
}

function ExecutionTable({ executions, runStatus }: { executions: ExecutionDetail[]; runStatus: string }) {
  const [search, setSearch] = useState("");
  const [catFilter, setCatFilter] = useState("");
  const [modeFilter, setModeFilter] = useState("");
  const [errOnly, setErrOnly] = useState(false);
  const [selected, setSelected] = useState<ExecutionDetail | null>(null);

  const categories = useMemo(() => Array.from(new Set(executions.map((e) => e.category))).sort(), [executions]);
  const modes = useMemo(() => Array.from(new Set(executions.map((e) => e.grading_mode))).sort(), [executions]);

  const filtered = executions.filter((e) => {
    if (search && !(e.title.toLowerCase().includes(search.toLowerCase()) || e.prompt_snapshot_id.toLowerCase().includes(search.toLowerCase()))) return false;
    if (catFilter && e.category !== catFilter) return false;
    if (modeFilter && e.grading_mode !== modeFilter) return false;
    if (errOnly && e.status !== "failed") return false;
    return true;
  });

  return (
    <Card className="p-0 overflow-hidden">
      <div className="flex flex-wrap gap-2 p-3 border-b border-border">
        <input className="input flex-1 min-w-[180px]" placeholder="Search prompts…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select className="input w-40" value={catFilter} onChange={(e) => setCatFilter(e.target.value)}>
          <option value="">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select className="input w-44" value={modeFilter} onChange={(e) => setModeFilter(e.target.value)}>
          <option value="">All grading modes</option>
          {modes.map((m) => <option key={m} value={m}>{GRADING_MODE_LABELS[m] || m}</option>)}
        </select>
        <label className="flex items-center gap-2 text-sm px-2"><input type="checkbox" checked={errOnly} onChange={(e) => setErrOnly(e.target.checked)} /> Errors only</label>
      </div>
      <div className="overflow-auto max-h-[60vh]">
        <table className="w-full text-sm">
          <thead className="bg-bg-elev text-gray-400 text-xs uppercase sticky top-0">
            <tr>
              <th className="text-left px-3 py-2">#</th>
              <th className="text-left px-3 py-2">Prompt</th>
              <th className="text-left px-3 py-2">Category</th>
              <th className="text-left px-3 py-2">Mode</th>
              <th className="text-right px-3 py-2">Score</th>
              <th className="text-right px-3 py-2">Weight</th>
              <th className="text-left px-3 py-2">Status</th>
              <th className="text-right px-3 py-2">TTFT</th>
              <th className="text-right px-3 py-2">Tok/s</th>
              <th className="text-right px-3 py-2">Cost</th>
              <th className="text-right px-3 py-2">Total</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e) => (
              <tr key={e.id} className="border-t border-border hover:bg-bg-elev/40 cursor-pointer" onClick={() => setSelected(e)}>
                <td className="px-3 py-2 text-gray-500">{e.position}</td>
                <td className="px-3 py-2 text-gray-200">{e.title || e.prompt_snapshot_id}</td>
                <td className="px-3 py-2 text-gray-400">{e.category}</td>
                <td className="px-3 py-2"><Badge className="text-accent border-accent/40 bg-accent/10">{GRADING_MODE_LABELS[e.grading_mode] || e.grading_mode}</Badge></td>
                <td className={`px-3 py-2 text-right mono ${scoreColor(e.final_score)}`}>{fmtScore(e.final_score)}</td>
                <td className="px-3 py-2 text-right text-gray-400">{e.importance_weight}</td>
                <td className="px-3 py-2"><Badge className={statusColor(e.status)}>{STATUS_LABELS[e.status] || e.status}</Badge></td>
                <td className="px-3 py-2 text-right mono text-gray-400">{fmtMs(e.timing.time_to_first_token)}</td>
                <td className="px-3 py-2 text-right mono text-gray-400">{e.timing.output_tokens_per_second?.toFixed(1) ?? "—"}</td>
                <td className="px-3 py-2 text-right mono text-gray-400">{fmtCost(e.timing.cost)}</td>
                <td className="px-3 py-2 text-right mono text-gray-400">{fmtMs(e.timing.total_response_time)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected && <ExecutionDetailModal execution={selected} onClose={() => setSelected(null)} runStatus={runStatus} />}
    </Card>
  );
}


function ExecutionDetailModal({ execution, onClose, runStatus }: { execution: ExecutionDetail; onClose: () => void; runStatus: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const isAwaiting = execution.status === "awaiting_manual" || execution.status === "awaiting_judge" || execution.status === "completed";
  const [manualScore, setManualScore] = useState<number>(execution.manual?.score ?? execution.final_score ?? 0);
  const [manualNotes, setManualNotes] = useState<string>(execution.manual?.notes ?? "");
  const [saving, setSaving] = useState(false);

  const saveManual = async () => {
    setSaving(true);
    try {
      await api.addManualGrade(execution.id, { score: manualScore, notes: manualNotes });
      qc.invalidateQueries({ queryKey: ["results"] });
      toast("Manual score saved", "success");
      onClose();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={execution.title || execution.prompt_snapshot_id} onClose={onClose}>
      <div className="space-y-4">
        <div className="flex items-center gap-2 flex-wrap">
          <Badge className={statusColor(execution.status)}>{STATUS_LABELS[execution.status] || execution.status}</Badge>
          <Badge className="text-accent border-accent/40 bg-accent/10">{GRADING_MODE_LABELS[execution.grading_mode]}</Badge>
          <Badge className="text-gray-400 border-border bg-bg-elev">{execution.category}</Badge>
          <span className="text-sm text-gray-400 ml-auto">Final score: <span className={`mono font-semibold ${scoreColor(execution.final_score)}`}>{fmtScore(execution.final_score)}</span></span>
        </div>

        <Section title="Original messages">
          {execution.messages.map((m, i) => (
            <div key={i} className="mb-2">
              <div className="text-xs text-accent uppercase">{m.role}</div>
              <pre className="mono text-xs bg-bg p-2 rounded border border-border whitespace-pre-wrap">{m.content}</pre>
            </div>
          ))}
        </Section>

        {(execution.generation_diagnostics?.no_final_answer || execution.generation_diagnostics?.possible_repetition || execution.generation_diagnostics?.truncated) && (
          <p className="text-sm text-warn">
            {execution.generation_diagnostics.no_final_answer && "No final answer was returned. "}
            {execution.generation_diagnostics.possible_repetition && "Possible repetitive generation detected. "}
            {execution.generation_diagnostics.truncated && "The response reached its token limit. "}
          </p>
        )}
        {execution.error_message && <p className="text-sm text-err">{execution.error_message}</p>}
        {execution.reasoning_response && (
          <details>
            <summary className="text-sm text-gray-400 cursor-pointer">Model reasoning ({execution.reasoning_response.length.toLocaleString()} characters)</summary>
            <pre className="mono text-xs bg-bg p-2 rounded border border-border whitespace-pre-wrap max-h-60 overflow-auto">{execution.reasoning_response}</pre>
          </details>
        )}
        <Section title="Candidate response">
          <pre className="mono text-xs bg-bg p-2 rounded border border-border whitespace-pre-wrap max-h-60 overflow-auto">{execution.candidate_response || "(empty)"}</pre>
        </Section>

        {execution.reference_answer && (
          <Section title="Reference answer (guidance)">
            <pre className="mono text-xs bg-bg p-2 rounded border border-border whitespace-pre-wrap">{execution.reference_answer}</pre>
          </Section>
        )}

        {execution.deterministics.length > 0 && (
          <Section title="Deterministic checks">
            {execution.deterministics.map((d, i) => (
              <div key={i} className="text-xs mb-2">
                <Badge className={d.passed ? "text-ok border-ok/40 bg-ok/10" : "text-err border-err/40 bg-err/10"}>{d.passed ? "PASS" : "FAIL"}</Badge>
                <span className="ml-2 text-gray-300">{d.type}: {fmtScore(d.score)} / {fmtScore(d.max_score)}</span>
                <pre className="mono text-xs text-gray-400 mt-1 bg-bg p-2 rounded border border-border overflow-auto">{JSON.stringify(d.details, null, 2)}</pre>
              </div>
            ))}
          </Section>
        )}

        {execution.judge && (
          <Section title="Judge rubric">
            {!execution.judge.valid && <Badge className="text-err border-err/40 bg-err/10">invalid output</Badge>}
            {execution.judge.critical_error && <Badge className="text-err border-err/40 bg-err/10">critical error</Badge>}
            {execution.judge.score_cap !== null && execution.judge.score_cap !== undefined && <span className="text-xs text-warn ml-2">capped at {execution.judge.score_cap}</span>}
            <table className="w-full text-xs mt-2">
              <thead className="text-gray-500"><tr><th className="text-left py-1">Dimension</th><th className="text-right">Score</th><th className="text-right">Max</th></tr></thead>
              <tbody>
                {Object.entries(execution.judge.dimension_scores).map(([name, d]) => (
                  <tr key={name} className="border-t border-border"><td className="py-1">{name}</td><td className="text-right mono">{d.score}</td><td className="text-right mono">{d.maximum}</td></tr>
                ))}
              </tbody>
            </table>
            {execution.judge.strengths.length > 0 && <div className="text-xs mt-2"><span className="text-ok">Strengths:</span> {execution.judge.strengths.join("; ")}</div>}
            {execution.judge.deductions.length > 0 && (
              <ul className="text-xs mt-1 list-disc pl-5 text-warn">
                {execution.judge.deductions.map((d, i) => <li key={i}>−{d.points}: {d.reason}</li>)}
              </ul>
            )}
          </Section>
        )}

        {execution.verifier && (
          <Section title="Verifier pass">
            <Badge className={execution.verifier.adjusted ? "text-warn border-warn/40 bg-warn/10" : "text-ok border-ok/40 bg-ok/10"}>
              {execution.verifier.adjusted ? `adjusted ${execution.verifier.original_score} → ${execution.verifier.verified_score}` : "confirmed"}
            </Badge>
            {execution.verifier.problems_found.length > 0 && <ul className="text-xs mt-1 list-disc pl-5 text-warn">{execution.verifier.problems_found.map((p, i) => <li key={i}>{p}</li>)}</ul>}
            {execution.verifier.adjustment_reason && <p className="text-xs text-gray-400 mt-1">{execution.verifier.adjustment_reason}</p>}
          </Section>
        )}

        <Section title="Timing & tokens">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
            <KV k="TTFT" v={fmtMs(execution.timing.time_to_first_token)} />
            <KV k="Total" v={fmtMs(execution.timing.total_response_time)} />
            <KV
              k={execution.timing.tps_source === "server" ? "Tok/s (server)" : "Tok/s"}
              v={execution.timing.output_tokens_per_second?.toFixed(1) ?? "—"}
            />
            <KV
              k="Prefill tok/s"
              v={execution.timing.prompt_tokens_per_second?.toFixed(1) ?? "—"}
            />
            <KV
              k="Completion tokens"
              v={`${fmtTokens(execution.timing.completion_tokens)}${execution.raw_meta.tokens_estimated ? " (est.)" : ""}`}
            />
            <KV k="Prompt tokens" v={fmtTokens(execution.timing.prompt_tokens)} />
            <KV k="Cost" v={fmtCost(execution.timing.cost)} />
            <KV k="HTTP" v={execution.raw_meta.http_status?.toString() ?? "—"} />
            <KV k="Retries" v={String(execution.raw_meta.retry_count)} />
            <KV k="Truncated" v={execution.timing.truncated ? "yes" : "no"} />
            <KV k="Finish" v={execution.finish_reason} />
          </div>
        </Section>

        <Section title="Manual override">
          <p className="text-xs text-gray-500 mb-2">Override or add a manual score (0–100). Manual/pending prompts are excluded from auto-scoring until scored.</p>
          <div className="flex gap-2 items-end">
            <div className="flex-1"><label className="label">Score</label><input type="number" min="0" max="100" className="input" value={manualScore} onChange={(e) => setManualScore(Number(e.target.value))} /></div>
            <button className="btn btn-primary" disabled={saving} onClick={saveManual}>{saving ? "Saving…" : "Save"}</button>
          </div>
          <textarea className="input mt-2 h-16" placeholder="Notes" value={manualNotes} onChange={(e) => setManualNotes(e.target.value)} />
        </Section>
      </div>
    </Modal>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-2">{title}</h4>
      {children}
    </div>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div className="panel p-2">
      <div className="text-gray-500">{k}</div>
      <div className="mono text-gray-200">{v}</div>
    </div>
  );
}
