import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Badge, Card, EmptyState, PageHeader, Spinner } from "@/components/ui";
import { useToast } from "@/store/toast";
import type { BenchmarkSet, EndpointProfile } from "@/types";

export default function NewRun() {
  const navigate = useNavigate();
  const toast = useToast();
  const { data: endpoints } = useQuery({ queryKey: ["endpoints"], queryFn: api.listEndpoints });
  const { data: benchmarks } = useQuery({ queryKey: ["benchmarks"], queryFn: api.listBenchmarks });
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const [benchmarkId, setBenchmarkId] = useState("");
  const [targetEndpointId, setTargetEndpointId] = useState("");
  const [targetModel, setTargetModel] = useState("");
  const [judgeEndpointId, setJudgeEndpointId] = useState("");
  const [judgeModel, setJudgeModel] = useState("");
  const [temperature, setTemperature] = useState(0);
  const [topP, setTopP] = useState(1);
  const [maxTokens, setMaxTokens] = useState(4096);
  const [maxTokensEdited, setMaxTokensEdited] = useState(false);
  // Default the token budget from Settings (default_max_tokens) unless the user
  // has typed their own value for this run. Keeps runs from truncating a
  // chain-of-thought model before its answer lands.
  useEffect(() => {
    if (settings && !maxTokensEdited) setMaxTokens(settings.default_max_tokens);
  }, [settings, maxTokensEdited]);
  const [timeout, setTimeout_] = useState(60);
  const [repetitions, setRepetitions] = useState(1);
  const [shuffle, setShuffle] = useState(false);
  const [warmup, setWarmup] = useState(false);
  const [streaming, setStreaming] = useState(true);
  const [verifier, setVerifier] = useState(false);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const enabledEndpoints = (endpoints || []).filter((e) => e.enabled);
  const selectedBenchmark = benchmarks?.find((b) => b.id === benchmarkId);
  const needsJudge = selectedBenchmark ? (selectedBenchmark.enabled_prompt_count > 0) : false;
  const targetEndpoint = endpoints?.find((e) => e.id === targetEndpointId);
  const sameModel = targetModel && judgeModel && targetEndpointId === judgeEndpointId && targetModel === judgeModel;

  const validate = (): string | null => {
    if (!benchmarkId) return "Select a benchmark.";
    if (!targetEndpointId) return "Select a target endpoint.";
    if (!targetModel.trim()) return "Enter or select a target model.";
    return null;
  };

  const start = async () => {
    const err = validate();
    if (err) {
      toast(err, "error");
      return;
    }
    setSubmitting(true);
    try {
      const run = await api.createRun({
        benchmark_id: benchmarkId,
        target_endpoint_id: targetEndpointId,
        target_model: targetModel,
        judge_endpoint_id: judgeEndpointId || undefined,
        judge_model: judgeModel || undefined,
        judge_temperature: 0,
        judge_max_tokens: 2048,
        verifier_enabled: verifier,
        run_config: {
          repetitions,
          sequential_execution: true,
          shuffle_prompt_order: shuffle,
          warm_up_request: warmup,
          streaming_enabled: streaming,
          judge_verification_enabled: verifier,
          temperature,
          top_p: topP,
          max_tokens: maxTokens,
          timeout,
        },
        notes,
        auto_start: true,
      });
      toast("Run started", "success");
      navigate(`/runs/${run.id}`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <PageHeader title="New Benchmark Run" subtitle="Configure a run against one target model. Defaults to sequential execution so latency/throughput are not distorted by concurrency." />
      <div className="grid md:grid-cols-2 gap-4">
        <Card>
          <label className="label">Benchmark set</label>
          {!benchmarks || benchmarks.length === 0 ? (
            <EmptyState title="No benchmarks available" />
          ) : (
            <select className="input" value={benchmarkId} onChange={(e) => setBenchmarkId(e.target.value)}>
              <option value="">— select —</option>
              {benchmarks.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} ({b.enabled_prompt_count} prompts) v{b.version}
                </option>
              ))}
            </select>
          )}
          {selectedBenchmark && (
            <p className="text-xs text-gray-500 mt-1">
              {needsJudge ? "Includes judge/hybrid prompts — configure a judge below or defer judging." : "Deterministic/manual only — no judge required."}
            </p>
          )}
        </Card>
        <Card>
          <label className="label">Notes</label>
          <textarea className="input h-16" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional notes for this run" />
        </Card>
        <Card>
          <h3 className="font-medium text-white mb-2">Target</h3>
          <label className="label">Endpoint</label>
          <select className="input mb-2" value={targetEndpointId} onChange={(e) => { setTargetEndpointId(e.target.value); const ep = endpoints?.find((x) => x.id === e.target.value); if (ep) setTargetModel(ep.default_model); }}>
            <option value="">— select —</option>
            {enabledEndpoints.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
          <label className="label">Model</label>
          <input className="input mono" value={targetModel} onChange={(e) => setTargetModel(e.target.value)} placeholder="model name" />
        </Card>
        <Card>
          <h3 className="font-medium text-white mb-2">Judge (optional)</h3>
          <label className="label">Endpoint</label>
          <select className="input mb-2" value={judgeEndpointId} onChange={(e) => { setJudgeEndpointId(e.target.value); const ep = endpoints?.find((x) => x.id === e.target.value); if (ep) setJudgeModel(ep.default_model); }}>
            <option value="">— none (defer judging) —</option>
            {enabledEndpoints.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
          <label className="label">Model</label>
          <input className="input mono" value={judgeModel} onChange={(e) => setJudgeModel(e.target.value)} placeholder="judge model name" />
          {sameModel && (
            <p className="text-xs text-warn mt-2">⚠ The target and judge are the same model — self-judging can bias the score.</p>
          )}
        </Card>
        <Card className="md:col-span-2">
          <h3 className="font-medium text-white mb-2">Generation &amp; run settings</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div><label className="label">Temperature</label><input type="number" step="0.1" className="input" value={temperature} onChange={(e) => setTemperature(parseFloat(e.target.value))} /></div>
            <div><label className="label">Top-p</label><input type="number" step="0.05" className="input" value={topP} onChange={(e) => setTopP(parseFloat(e.target.value))} /></div>
            <div><label className="label">Max output tokens</label><input type="number" min="256" step="256" className="input" value={maxTokens} onChange={(e) => { setMaxTokens(parseInt(e.target.value)); setMaxTokensEdited(true); }} /><div className="text-xs text-gray-500 mt-1">Reasoning models need headroom — keep ≥ 4096.</div></div>
            <div><label className="label">Timeout (s)</label><input type="number" className="input" value={timeout} onChange={(e) => setTimeout_(parseInt(e.target.value))} /></div>
            <div><label className="label">Repetitions</label><input type="number" min="1" max="20" className="input" value={repetitions} onChange={(e) => setRepetitions(parseInt(e.target.value))} /></div>
            <label className="flex items-end gap-2 text-sm pb-2"><input type="checkbox" checked={shuffle} onChange={(e) => setShuffle(e.target.checked)} /> Shuffle prompt order</label>
            <label className="flex items-end gap-2 text-sm pb-2"><input type="checkbox" checked={warmup} onChange={(e) => setWarmup(e.target.checked)} /> Warm-up request</label>
            <label className="flex items-end gap-2 text-sm pb-2"><input type="checkbox" checked={streaming} onChange={(e) => setStreaming(e.target.checked)} /> Streaming</label>
            <label className="flex items-end gap-2 text-sm pb-2"><input type="checkbox" checked={verifier} onChange={(e) => setVerifier(e.target.checked)} /> Judge verification pass</label>
          </div>
        </Card>
      </div>
      <div className="flex justify-end gap-2 mt-4">
        <button className="btn" onClick={() => navigate(-1)}>Cancel</button>
        <button className="btn btn-primary" disabled={submitting} onClick={start}>
          {submitting ? "Starting…" : "Start run"}
        </button>
      </div>
    </div>
  );
}
