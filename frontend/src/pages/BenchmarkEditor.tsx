import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Badge, Card, ConfirmButton, EmptyState, Modal, PageHeader, Spinner } from "@/components/ui";
import { useToast } from "@/store/toast";
import { GRADING_MODE_LABELS } from "@/lib/format";
import PromptEditor from "@/components/PromptEditor";
import type { BenchmarkPrompt, BenchmarkSet } from "@/types";

export default function BenchmarkEditor() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const qc = useQueryClient();
  const { data: bench, isLoading } = useQuery({
    queryKey: ["benchmark", id],
    queryFn: () => api.getBenchmark(id!),
    enabled: !!id,
  });
  const [editingPrompt, setEditingPrompt] = useState<BenchmarkPrompt | null>(null);
  const [creatingPrompt, setCreatingPrompt] = useState(false);
  const [showMeta, setShowMeta] = useState(false);

  const savePromptMut = useMutation({
    mutationFn: ({ prompt }: { prompt: Partial<BenchmarkPrompt> }) => {
      if (!id) throw new Error("no benchmark id");
      return api.savePrompt(id, editingPrompt?.id ?? null, prompt);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["benchmark", id] });
      setEditingPrompt(null);
      setCreatingPrompt(false);
      toast("Prompt saved", "success");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  if (isLoading) return <Spinner label="Loading benchmark…" />;
  if (!bench) return <EmptyState title="Benchmark not found" />;

  const move = (idx: number, dir: -1 | 1) => {
    const ordered = [...bench.prompts].sort((a, b) => a.position - b.position);
    const target = idx + dir;
    if (target < 0 || target >= ordered.length) return;
    [ordered[idx], ordered[target]] = [ordered[target], ordered[idx]];
    api.reorderPrompts(bench.id, ordered.map((p) => p.id!)).then(() => qc.invalidateQueries({ queryKey: ["benchmark", id] }));
  };

  return (
    <div>
      <PageHeader
        title={bench.name}
        subtitle={`${bench.prompts.length} prompts · v${bench.version}${bench.is_example ? " · example" : ""}`}
        actions={
          <>
            <Link to="/benchmarks" className="btn">Back</Link>
            <button className="btn" onClick={() => setShowMeta(true)}>Edit metadata</button>
            <button className="btn btn-primary" onClick={() => setCreatingPrompt(true)}>+ Add Prompt</button>
          </>
        }
      />
      <p className="text-sm text-gray-400 mb-4">{bench.description}</p>

      {bench.prompts.length === 0 ? (
        <EmptyState title="No prompts yet" hint="Add prompts to build your benchmark set." />
      ) : (
        <div className="space-y-2">
          {[...bench.prompts].sort((a, b) => a.position - b.position).map((p, idx) => (
            <Card key={p.id} className="p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <button className="font-medium text-white hover:text-accent text-left" onClick={() => setEditingPrompt(p)}>
                      {p.title || "(untitled)"}
                    </button>
                    <Badge className="text-gray-400 border-border bg-bg-elev">{GRADING_MODE_LABELS[p.grading_mode] || p.grading_mode}</Badge>
                    <Badge className="text-accent border-accent/40 bg-accent/10">{p.category}</Badge>
                    {!p.enabled && <Badge className="text-gray-500 border-border bg-bg-elev">disabled</Badge>}
                  </div>
                  <div className="text-xs text-gray-500 mt-1 truncate mono">{p.stable_id} · weight {p.importance_weight} · {p.messages.length} message(s)</div>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <button className="btn btn-ghost px-2" disabled={idx === 0} onClick={() => move(idx, -1)} aria-label="Move up">↑</button>
                  <button className="btn btn-ghost px-2" disabled={idx === bench.prompts.length - 1} onClick={() => move(idx, 1)} aria-label="Move down">↓</button>
                  <button className="btn" onClick={() => setEditingPrompt(p)}>Edit</button>
                  <button
                    className="btn"
                    onClick={() => api.duplicatePrompt(bench.id, p.id!).then(() => { qc.invalidateQueries({ queryKey: ["benchmark", id] }); toast("Duplicated", "success"); })}
                  >
                    Duplicate
                  </button>
                  <ConfirmButton
                    message={`Delete prompt '${p.title || p.stable_id}'?`}
                    onConfirm={() => api.deletePrompt(bench.id, p.id!).then(() => { qc.invalidateQueries({ queryKey: ["benchmark", id] }); toast("Deleted", "success"); })}
                  >
                    Delete
                  </ConfirmButton>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {(creatingPrompt || editingPrompt) && (
        <PromptEditor
          benchmarkId={bench.id}
          initial={editingPrompt}
          onClose={() => { setEditingPrompt(null); setCreatingPrompt(false); }}
          onSave={(prompt) => savePromptMut.mutate({ prompt })}
          submitting={savePromptMut.isPending}
        />
      )}

      {showMeta && (
        <MetadataModal bench={bench} onClose={() => setShowMeta(false)} onSaved={() => { qc.invalidateQueries({ queryKey: ["benchmark", id] }); qc.invalidateQueries({ queryKey: ["leaderboards"] }); setShowMeta(false); }} />
      )}
    </div>
  );
}

function MetadataModal({ bench, onClose, onSaved }: { bench: BenchmarkSet; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(bench.name);
  const [description, setDescription] = useState(bench.description);
  const [version, setVersion] = useState(bench.version);
  const [thresholds, setThresholds] = useState(JSON.stringify(bench.performance_thresholds || {}, null, 2));
  const [weights, setWeights] = useState(JSON.stringify(bench.composite_weights || {}, null, 2));
  const [showInLeaderboards, setShowInLeaderboards] = useState(bench.show_in_leaderboards);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    // Refuse to save unparseable JSON instead of silently wiping stored values.
    const parsedThresholds = tryParseJson(thresholds);
    if (parsedThresholds === undefined) {
      toast("Performance thresholds is not valid JSON — fix it or clear the field to {}.", "error");
      return;
    }
    const parsedWeights = tryParseJson(weights);
    if (parsedWeights === undefined) {
      toast("Composite-score weights is not valid JSON — fix it or clear the field to {}.", "error");
      return;
    }
    setSaving(true);
    try {
      await api.updateBenchmark(bench.id, {
        name,
        description,
        version,
        performance_thresholds: parsedThresholds,
        composite_weights: parsedWeights,
        show_in_leaderboards: showInLeaderboards,
      });
      toast("Metadata saved", "success");
      onSaved();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title="Benchmark metadata"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={saving} onClick={save}>{saving ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <div className="space-y-3">
        <div>
          <label className="label">Name</label>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label className="label">Description</label>
          <textarea className="input h-20" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div>
          <label className="label">Version</label>
          <input className="input" value={version} onChange={(e) => setVersion(e.target.value)} />
        </div>
        <div>
          <label className="label">Performance thresholds (JSON)</label>
          <textarea className="input mono h-32" value={thresholds} onChange={(e) => setThresholds(e.target.value)} />
          <p className="text-xs text-gray-500 mt-1">Keys: desired_ttft, max_ttft, desired_tps, min_tps, max_failure_rate</p>
        </div>
        <div>
          <label className="label">Composite-score weights (JSON)</label>
          <textarea className="input mono h-24" value={weights} onChange={(e) => setWeights(e.target.value)} />
          <p className="text-xs text-gray-500 mt-1">quality, reliability, performance (should total 1.0)</p>
        </div>
        <div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={showInLeaderboards}
              onChange={(e) => setShowInLeaderboards(e.target.checked)}
            />
            <span className="text-sm text-gray-200">Show in leaderboards</span>
          </label>
          <p className="text-xs text-gray-500 mt-1">
            List this suite on the Leaderboards tab, ranking every model tested against it.
          </p>
        </div>
      </div>
    </Modal>
  );
}

function tryParseJson(s: string): Record<string, unknown> | undefined {
  if (!s.trim()) return {};
  try {
    const parsed = JSON.parse(s);
    return typeof parsed === "object" && parsed !== null ? parsed : undefined;
  } catch {
    return undefined;
  }
}
