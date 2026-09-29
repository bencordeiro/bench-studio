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
  const [reasoningEffort, setReasoningEffort] = useState("");
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

  // When an endpoint is selected, ask it for its /v1/models list so the model
  // field can be prefilled with the real alias. On success: use the profile
  // default if it's a real alias, else the single discovered model, else leave
  // blank (don't guess). On failure: leave blank — the user types the name.
  const { data: targetModels } = useQuery({
    queryKey: ["endpoint-models", targetEndpointId],
    queryFn: () => api.fetchModels(targetEndpointId!),
    enabled: !!targetEndpointId,
    retry: false,
  });
  const { data: judgeModels } = useQuery({
    queryKey: ["endpoint-models", judgeEndpointId],
    queryFn: () => api.fetchModels(judgeEndpointId!),
    enabled: !!judgeEndpointId,
    retry: false,
  });
  const modelList = (targetModels?.success && targetModels.models) || [];
  const judgeModelList = (judgeModels?.success && judgeModels.models) || [];

  useEffect(() => {
    if (!targetEndpointId) return;
    if (targetModels?.success) {
      const list = targetModels.models;
      const preferred = targetEndpoint?.default_model;
      if (preferred && list.includes(preferred)) setTargetModel(preferred);
      else if (list.length === 1) setTargetModel(list[0]);
      else setTargetModel("");
    } else {
      setTargetModel("");
    }
  }, [targetEndpointId, targetModels, targetEndpoint?.default_model]);

  useEffect(() => {
    if (!judgeEndpointId) return;
    if (judgeModels?.success) {
      const list = judgeModels.models;
      const preferred = endpoints?.find((e) => e.id === judgeEndpointId)?.default_model;
      if (preferred && list.includes(preferred)) setJudgeModel(preferred);
      else if (list.length === 1) setJudgeModel(list[0]);
      else setJudgeModel("");
    } else {
      setJudgeModel("");
    }
  }, [judgeEndpointId, judgeModels, endpoints]);

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
          reasoning_effort: reasoningEffort || undefined,
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
          {selectedBenchmark?.tags?.includes("hermes") && (
            <p className="text-xs text-warn mt-2">
              Tool questions automatically use native API calls when the endpoint rejects Hermes text blocks.
              Tool schemas, arguments and supplied history are preserved. The selected protocol is recorded with the run.
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
          <select className="input mb-2" value={targetEndpointId} onChange={(e) => { setTargetEndpointId(e.target.value); setTargetModel(""); }}>
            <option value="">— select —</option>
            {enabledEndpoints.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
          <label className="label">Model</label>
          <input className="input mono" list="target-model-list" value={targetModel} onChange={(e) => setTargetModel(e.target.value)} placeholder="model name" />
          <datalist id="target-model-list">
            {modelList.map((m) => <option key={m} value={m} />)}
          </datalist>
          {modelList.length > 0 && (
            <p className="text-xs text-gray-500 mt-1">{modelList.length} model(s) discovered via /v1/models</p>
          )}
        </Card>
        <Card>
          <h3 className="font-medium text-white mb-2">Judge (optional)</h3>
          <label className="label">Endpoint</label>
          <select className="input mb-2" value={judgeEndpointId} onChange={(e) => { setJudgeEndpointId(e.target.value); setJudgeModel(""); }}>
            <option value="">— none (defer judging) —</option>
            {enabledEndpoints.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
          <label className="label">Model</label>
          <input className="input mono" list="judge-model-list" value={judgeModel} onChange={(e) => setJudgeModel(e.target.value)} placeholder="judge model name" />
          <datalist id="judge-model-list">
            {judgeModelList.map((m) => <option key={m} value={m} />)}
          </datalist>
          {judgeModelList.length > 0 && (
            <p className="text-xs text-gray-500 mt-1">{judgeModelList.length} model(s) discovered via /v1/models</p>
          )}
          {sameModel && (
            <p className="text-xs text-warn mt-2">⚠ The target and judge are the same model — self-judging can bias the score.</p>
          )}
        </Card>
        <Card className="md:col-span-2">
          <h3 className="font-medium text-white mb-2">Generation &amp; run settings</h3>
          <p className="text-xs text-gray-400 mb-3">Global Settings apply to every new run: {settings?.default_max_tokens === 0 ? "server default tokens" : `${settings?.default_max_tokens ?? "…"} max tokens`}, {settings?.default_timeout ?? "…"}s inactivity timeout. Active generation has no time limit.</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div><label className="label">Temperature</label><input type="number" step="0.1" className="input" value={temperature} onChange={(e) => setTemperature(parseFloat(e.target.value))} /></div>
            <div><label className="label">Top-p</label><input type="number" step="0.05" className="input" value={topP} onChange={(e) => setTopP(parseFloat(e.target.value))} /></div>
            <div><label className="label">Reasoning level</label><select className="input" value={reasoningEffort} onChange={(e) => setReasoningEffort(e.target.value)}><option value="">server default</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="xhigh">xhigh</option></select><div className="text-xs text-gray-500 mt-1">Sent as chat_template_kwargs.reasoning_effort (llama.cpp / LM Studio).</div></div>
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
