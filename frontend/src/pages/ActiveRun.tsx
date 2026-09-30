import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Badge, Card, ConfirmButton, EmptyState, PageHeader, Spinner } from "@/components/ui";
import { useToast } from "@/store/toast";
import { fmtDuration, runDurationSeconds, isTerminal, STATUS_LABELS, statusColor } from "@/lib/format";
import type { RunResponse } from "@/types";

export default function ActiveRun() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const qc = useQueryClient();
  const { data: run, isLoading } = useQuery({
    queryKey: ["run", id],
    queryFn: () => api.getRun(id!),
    enabled: !!id,
    refetchInterval: (q) => {
      const r = q.state.data as RunResponse | undefined;
      return r && !isTerminal(r.status) ? 1500 : false;
    },
  });

  const [progress, setProgress] = useState(0);
  const [phase, setPhase] = useState<string>("");
  const [currentPrompt, setCurrentPrompt] = useState<string>("");
  const [elapsed, setElapsed] = useState(0);
  const [generation, setGeneration] = useState<{
    elapsed_seconds: number; answer_chars: number; reasoning_chars: number;
    possible_repetition: boolean; retry_count: number; receivedAt: number;
  } | null>(null);

  // SSE subscription while running.
  useEffect(() => {
    if (!id || !run || isTerminal(run.status)) return;
    const es = new EventSource(`/api/runs/${id}/progress`);
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.event === "prompt_started") setGeneration(null);
        if (data.event === "generation") setGeneration({ ...data, receivedAt: Date.now() });
        if (data.event === "snapshot" || data.event === "prompt" || data.event === "prompt_started" || data.event === "phase") {
          if (typeof data.progress === "number") setProgress(data.progress);
          if (data.phase) setPhase(data.phase);
          if (data.current_prompt) setCurrentPrompt(data.current_prompt);
        }
      } catch {
        // ignore
      }
    };
    es.onerror = () => { /* polling fallback continues */ };
    return () => es.close();
  }, [id, run?.status]);

  // Elapsed timer.
  useEffect(() => {
    if (!run?.started_at || isTerminal(run.status)) return;
    const tick = () => setElapsed(runDurationSeconds({
      started_at: run.started_at, completed_at: new Date().toISOString(),
    }) ?? 0);
    tick();
    const intv = setInterval(tick, 1000);
    return () => clearInterval(intv);
  }, [run?.started_at, run?.status]);

  const cancelMut = useMutation({
    mutationFn: () => api.cancelRun(id!),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["run", id] }); toast("Cancel requested — aborting current request", "info"); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const resumeMut = useMutation({
    mutationFn: () => api.resumeRun(id!),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["run", id] }); toast("Run resumed", "success"); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const deleteMut = useMutation({
    mutationFn: () => api.deleteRun(id!),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["runs"] }); toast("Run deleted", "success"); navigate("/runs"); },
    onError: (e: Error) => toast(e.message, "error"),
  });

  if (isLoading) return <Spinner label="Loading run…" />;
  if (!run) return <EmptyState title="Run not found" />;

  const total = run.total_prompts || 1;
  const done = run.completed_prompts;
  // Use SSE progress if available, otherwise derive from run state (polling fallback).
  // Take the max of the two: the SSE stream closes when the run ends, so its last
  // value can lag behind the final count and leave a finished run stuck at e.g. 90%.
  const runDerived = total > 0 ? done / total : 0;
  const rawProgress = isTerminal(run.status) ? runDerived : Math.max(progress, runDerived);
  // Guard against glitchy counters that push progress past 100% (or NaN), which
  // would otherwise flip the ETA negative.
  const displayProgress = Number.isFinite(rawProgress) ? Math.min(Math.max(rawProgress, 0), 1) : 0;
  const eta =
    displayProgress > 0 && displayProgress < 1
      ? (elapsed / displayProgress) * (1 - displayProgress)
      : null;

  return (
    <div>
      <PageHeader
        title={run.name}
        subtitle={`${run.target_endpoint_name} · ${run.target_model}${run.judge_enabled ? ` · judge: ${run.judge_model}` : ""}`}
        actions={
          <>
            <Link to="/runs" className="btn">Back</Link>
            {isTerminal(run.status) && (
              <Link to={`/runs/${id}/results`} className="btn btn-primary">View results</Link>
            )}
            {!isTerminal(run.status) && (
              <ConfirmButton message="Cancel this run? The current request is aborted immediately." onConfirm={() => cancelMut.mutate()} confirmLabel="Cancel run">
                Cancel
              </ConfirmButton>
            )}
            {run.status === "interrupted" && (
              <button className="btn btn-primary" disabled={resumeMut.isPending} onClick={() => resumeMut.mutate()}>
                {resumeMut.isPending ? "Resuming…" : "Resume"}
              </button>
            )}
            {(run.status === "queued" || run.status === "preparing") && (
              <button className="btn btn-primary" onClick={() => api.startRun(id!).then(() => qc.invalidateQueries({ queryKey: ["run", id] }))}>Start now</button>
            )}
            {isTerminal(run.status) && (
              <ConfirmButton
                message={`Delete run '${run.name}' and its results? This cannot be undone.`}
                confirmLabel="Delete"
                onConfirm={() => deleteMut.mutate()}
              >
                <span className="text-err">Delete</span>
              </ConfirmButton>
            )}
          </>
        }
      />
      <Card className="mb-4">
        <div className="flex items-center justify-between">
          <Badge className={statusColor(run.status)}>{STATUS_LABELS[run.status] || run.status}</Badge>
          {phase && !isTerminal(run.status) && <span className="text-sm text-accent">{phase.replace(/_/g, " ")}</span>}
        </div>
        {currentPrompt && !isTerminal(run.status) && (
          <p className="text-sm text-gray-400 mt-2 truncate">
            Now: <span className="text-white">{currentPrompt}</span>
          </p>
        )}
        {generation && run.status === "running_target" && (
          <div className="mt-3 text-xs text-gray-400 space-y-1">
            <p>Current request: {fmtDuration(generation.elapsed_seconds + (Date.now() - generation.receivedAt) / 1000)} · Answer: {generation.answer_chars.toLocaleString()} characters · Reasoning: {generation.reasoning_chars.toLocaleString()} characters · Retries: {generation.retry_count}</p>
            <p>Last stream update: {Math.max(0, Math.floor((Date.now() - generation.receivedAt) / 1000))}s ago</p>
            {generation.possible_repetition && <p className="text-warn">Possible repetitive generation detected. The request continues under your global limits.</p>}
          </div>
        )}
        <div className="mt-4">
          <div className="flex justify-between text-sm text-gray-400 mb-1">
            <span>{done} / {total} prompts</span>
            <span>{Math.round(displayProgress * 100)}%</span>
          </div>
          <div className="h-2 bg-bg-elev rounded-full overflow-hidden">
            <div className="h-full bg-accent transition-all" style={{ width: `${Math.min(100, displayProgress * 100)}%` }} />
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4 text-sm">
            <Metric label={isTerminal(run.status) ? "Total time" : "Elapsed"}
              value={fmtDuration(isTerminal(run.status) ? runDurationSeconds(run) : elapsed)} />
            <Metric label="Est. remaining" value={eta !== null && !isTerminal(run.status) ? `${fmtDuration(eta)} (estimate)` : "—"} />
            <Metric label="Errors" value={String(run.failed_prompts)} />
            <Metric label="Repetitions" value={String(run.run_config.repetitions ?? 1)} />
          </div>
        </div>
        {run.error_message && (
          <p className="text-sm text-err mt-3">Error: {run.error_message}</p>
        )}
        {run.text_tool_compatibility?.message && (
          <p className="text-sm text-gray-400 mt-3">{run.text_tool_compatibility.message}</p>
        )}
      </Card>
      {run.status === "interrupted" && (
        <Card>
          <p className="text-sm text-warn">
            This run was interrupted (the application stopped before it completed). Completed prompts are preserved.
            Click <strong>Resume</strong> to continue from the first incomplete prompt — already-completed target prompts will not be rerun.
          </p>
        </Card>
      )}
      {run.notes && <Card><p className="text-sm text-gray-400">{run.notes}</p></Card>}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
      <div className="text-lg font-medium text-white mono">{value}</div>
    </div>
  );
}
