import { useState } from "react";
import { Modal } from "@/components/ui";
import { approxTokens } from "@/lib/format";
import type { BenchmarkPrompt, GenerationOverrides, GradingMode, PromptMessage } from "@/types";

interface Props {
  benchmarkId: string;
  initial: BenchmarkPrompt | null;
  onClose: () => void;
  onSave: (prompt: Partial<BenchmarkPrompt>) => void;
  submitting: boolean;
}

const EMPTY: BenchmarkPrompt = {
  stable_id: "",
  title: "",
  description: "",
  category: "general",
  tags: [],
  difficulty: "medium",
  importance_weight: 1.0,
  position: 0,
  enabled: true,
  grading_mode: "deterministic",
  generation_overrides: {},
  grader_config: {},
  messages: [{ role: "user", content: "", position: 0 }],
};

const GRADING_MODE_HELP: Record<GradingMode, string> = {
  deterministic: "Objective checks the computer can verify exactly: exact/alias match, numeric tolerance, regex, concept coverage, JSON schema, multiple choice.",
  judge: "Open-ended answers an LLM evaluates against a rubric: troubleshooting, architecture, explanations, writing quality.",
  hybrid: "Combine deterministic checks with an LLM judge. You choose the weighting (must total 100%). Critical failures can cap the final score.",
  manual: "No automatic score. The candidate answer is captured for a human to review and score 0–100 later.",
};

export default function PromptEditor({ initial, onClose, onSave, submitting }: Props) {
  const [p, setP] = useState<BenchmarkPrompt>(initial ?? EMPTY);
  const [tagsInput, setTagsInput] = useState((initial?.tags ?? []).join(", "));
  const update = (patch: Partial<BenchmarkPrompt>) => setP((cur) => ({ ...cur, ...patch }));

  const setMessages = (msgs: PromptMessage[]) => update({ messages: msgs });
  const setGraderConfig = (cfg: Record<string, unknown>) => update({ grader_config: cfg });
  const setOverrides = (ov: GenerationOverrides) => update({ generation_overrides: ov });

  const totalChars = p.messages.reduce((a, m) => a + (m.content?.length ?? 0), 0);
  const totalTokens = approxTokens(p.messages.map((m) => m.content).join("\n"));

  const canSave = p.messages.length > 0 && p.grading_mode !== "hybrid" || (p.grading_mode === "hybrid" && validHybridWeights(p.grader_config));

  const handleSubmit = () => {
    onSave({
      stable_id: p.stable_id || `prompt-${Math.random().toString(36).slice(2, 8)}`,
      title: p.title,
      description: p.description,
      category: p.category,
      tags: tagsInput.split(",").map((t) => t.trim()).filter(Boolean),
      difficulty: p.difficulty,
      importance_weight: p.importance_weight,
      enabled: p.enabled,
      grading_mode: p.grading_mode,
      generation_overrides: p.generation_overrides,
      grader_config: p.grader_config,
      messages: p.messages.map((m, i) => ({ role: m.role, content: m.content, position: i })),
    });
  };

  return (
    <Modal
      title={initial ? "Edit prompt" : "New prompt"}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={submitting || !canSave} onClick={handleSubmit}>
            {submitting ? "Saving…" : "Save prompt"}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Title</label>
            <input className="input" value={p.title} onChange={(e) => update({ title: e.target.value })} />
          </div>
          <div>
            <label className="label">Stable ID (optional)</label>
            <input className="input mono" value={p.stable_id} onChange={(e) => update({ stable_id: e.target.value })} placeholder="auto-generated" />
          </div>
        </div>
        <div>
          <label className="label">Description</label>
          <textarea className="input h-14" value={p.description} onChange={(e) => update({ description: e.target.value })} />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="label">Category</label>
            <input className="input" value={p.category} onChange={(e) => update({ category: e.target.value })} />
          </div>
          <div>
            <label className="label">Difficulty</label>
            <select className="input" value={p.difficulty} onChange={(e) => update({ difficulty: e.target.value })}>
              <option value="easy">easy</option>
              <option value="medium">medium</option>
              <option value="hard">hard</option>
            </select>
          </div>
          <div>
            <label className="label">Importance weight</label>
            <input type="number" step="0.1" min="0" className="input" value={p.importance_weight} onChange={(e) => update({ importance_weight: parseFloat(e.target.value) || 0 })} />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Tags (comma separated)</label>
            <input className="input" value={tagsInput} onChange={(e) => setTagsInput(e.target.value)} />
          </div>
          <label className="flex items-end gap-2 text-sm pb-2">
            <input type="checkbox" checked={p.enabled} onChange={(e) => update({ enabled: e.target.checked })} /> Enabled
          </label>
        </div>

        <MessagesEditor messages={p.messages} onChange={setMessages} totalChars={totalChars} totalTokens={totalTokens} />

        <div>
          <label className="label">Grading mode</label>
          <select
            className="input"
            value={p.grading_mode}
            onChange={(e) => {
              const mode = e.target.value as GradingMode;
              update({ grading_mode: mode, grader_config: defaultGraderConfig(mode, p.grader_config) });
            }}
          >
            <option value="deterministic">Deterministic (exact/numeric/regex/concept/JSON/multiple-choice)</option>
            <option value="judge">LLM Judge (rubric)</option>
            <option value="hybrid">Hybrid (deterministic + judge)</option>
            <option value="manual">Manual review</option>
          </select>
          <p className="text-xs text-gray-500 mt-1">{GRADING_MODE_HELP[p.grading_mode]}</p>
        </div>

        {p.grading_mode === "deterministic" && (
          <DeterministicConfig config={p.grader_config} onChange={setGraderConfig} />
        )}
        {p.grading_mode === "judge" && <JudgeConfig config={p.grader_config} onChange={setGraderConfig} />}
        {p.grading_mode === "hybrid" && <HybridConfig config={p.grader_config} onChange={setGraderConfig} />}

        <GenerationOverridesEditor overrides={p.generation_overrides} onChange={setOverrides} />
      </div>
    </Modal>
  );
}

function validHybridWeights(cfg: Record<string, unknown>): boolean {
  const d = Number(cfg.deterministic_weight ?? 40);
  const j = Number(cfg.judge_weight ?? 60);
  return Math.abs(d + j - 100) < 0.01;
}

function defaultGraderConfig(mode: GradingMode, prev: Record<string, unknown>): Record<string, unknown> {
  if (mode === "deterministic") {
    return prev && prev.type ? prev : { type: "exact", canonical_answer: "", accepted_aliases: [], case_sensitive: false, trim_whitespace: true, normalize_punctuation: true, points: 100 };
  }
  if (mode === "judge") {
    return prev && prev.rubric_dimensions ? prev : { reference_answer: "", reference_facts: [], required_elements: [], rubric_dimensions: [{ name: "correctness", description: "", weight: 1, maximum: 100 }], critical_errors: [], score_caps: [], judge_instructions: "" };
  }
  if (mode === "hybrid") {
    return prev && typeof prev.deterministic_weight === "number" ? prev : {
      deterministic_checks: [{ type: "regex", required_patterns: [], forbidden_patterns: [], points: 100 }],
      deterministic_weight: 40,
      judge_weight: 60,
      judge: { reference_answer: "", reference_facts: [], required_elements: [], rubric_dimensions: [{ name: "correctness", weight: 1, maximum: 100 }], critical_errors: [] },
    };
  }
  return {};
}

function MessagesEditor({ messages, onChange, totalChars, totalTokens }: { messages: PromptMessage[]; onChange: (m: PromptMessage[]) => void; totalChars: number; totalTokens: number }) {
  const update = (i: number, patch: Partial<PromptMessage>) => {
    const next = messages.map((m, idx) => (idx === i ? { ...m, ...patch } : m));
    onChange(next);
  };
  return (
    <div className="panel p-3">
      <div className="flex items-center justify-between mb-2">
        <label className="label mb-0">Messages (OpenAI chat format)</label>
        <span className="text-xs text-gray-500">{totalChars} chars · ~{totalTokens} tokens</span>
      </div>
      <div className="space-y-2">
        {messages.map((m, i) => (
          <div key={i} className="border border-border rounded-md p-2 bg-bg">
            <div className="flex items-center gap-2 mb-1">
              <select
                className="input w-32 py-1"
                value={m.role}
                onChange={(e) => update(i, { role: e.target.value as PromptMessage["role"] })}
              >
                <option value="system">system</option>
                <option value="user">user</option>
                <option value="assistant">assistant</option>
              </select>
              <span className="text-xs text-gray-500">{approxTokens(m.content)} tokens</span>
              <div className="flex-1" />
              <button className="btn btn-ghost px-2" disabled={i === 0} onClick={() => onChange([...messages.slice(0, i - 1), messages[i], messages[i - 1], ...messages.slice(i + 1)])} aria-label="Move up">↑</button>
              <button className="btn btn-ghost px-2" disabled={i === messages.length - 1} onClick={() => onChange([...messages.slice(0, i), messages[i + 1], messages[i], ...messages.slice(i + 2)])} aria-label="Move down">↓</button>
              <button className="btn btn-ghost px-2" disabled={messages.length <= 1} onClick={() => onChange(messages.filter((_, idx) => idx !== i))} aria-label="Remove">✕</button>
            </div>
            <textarea
              className="input mono h-24 resize-y"
              value={m.content}
              onChange={(e) => update(i, { content: e.target.value })}
              placeholder="Message content…"
            />
          </div>
        ))}
      </div>
      <button className="btn mt-2" onClick={() => onChange([...messages, { role: "user", content: "", position: messages.length }])}>
        + Add message
      </button>
    </div>
  );
}

function GenerationOverridesEditor({ overrides, onChange }: { overrides: GenerationOverrides; onChange: (o: GenerationOverrides) => void }) {
  const set = (patch: Partial<GenerationOverrides>) => onChange({ ...overrides, ...patch });
  const num = (v: unknown) => (v === null || v === undefined ? "" : String(v));
  return (
    <details className="panel p-3">
      <summary className="cursor-pointer text-sm font-medium text-gray-300">Generation overrides (optional, per prompt)</summary>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mt-3">
        <Field label="Temperature (blank = inherit)">
          <input className="input" value={num(overrides.temperature)} onChange={(e) => set({ temperature: e.target.value === "" ? null : parseFloat(e.target.value) })} />
        </Field>
        <Field label="Top-p (blank = inherit)">
          <input className="input" value={num(overrides.top_p)} onChange={(e) => set({ top_p: e.target.value === "" ? null : parseFloat(e.target.value) })} />
        </Field>
        <Field label="Max tokens (blank = inherit)">
          <input className="input" value={num(overrides.max_tokens)} onChange={(e) => set({ max_tokens: e.target.value === "" ? null : parseInt(e.target.value) })} />
        </Field>
        <Field label="Seed (blank = inherit)">
          <input className="input" value={num(overrides.seed)} onChange={(e) => set({ seed: e.target.value === "" ? null : parseInt(e.target.value) })} />
        </Field>
        <Field label="Stop sequences (comma separated)">
          <input
            className="input"
            value={(overrides.stop || []).join(", ")}
            onChange={(e) => set({ stop: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
          />
        </Field>
      </div>
    </details>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
    </div>
  );
}

// Deterministic grader config: switches on grader type.
function DeterministicConfig({ config, onChange }: { config: Record<string, unknown>; onChange: (c: Record<string, unknown>) => void }) {
  const type = (config.type as string) || "exact";
  const setType = (t: string) => onChange({ ...config, type: t });
  const set = (patch: Record<string, unknown>) => onChange({ ...config, ...patch });
  return (
    <div className="panel p-3 space-y-2">
      <label className="label">Deterministic grader type</label>
      <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
        <option value="exact">Exact / alias match</option>
        <option value="numeric">Numeric result</option>
        <option value="regex">Regular-expression checks</option>
        <option value="concept">Concept coverage</option>
        <option value="json">Structured JSON</option>
        <option value="multiple_choice">Multiple choice</option>
      </select>
      <p className="text-xs text-gray-500">
        Max score per check: 100. Concept matching is less reliable than exact/numeric grading.
      </p>

      {type === "exact" && (
        <div className="space-y-2">
          <Field label="Canonical answer"><input className="input" value={String(config.canonical_answer ?? "")} onChange={(e) => set({ canonical_answer: e.target.value })} /></Field>
          <Field label="Accepted aliases (comma separated)"><input className="input" value={(config.accepted_aliases as string[] || []).join(", ")} onChange={(e) => set({ accepted_aliases: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></Field>
          <div className="flex gap-4 text-sm">
            <label><input type="checkbox" checked={!!config.case_sensitive} onChange={(e) => set({ case_sensitive: e.target.checked })} /> Case sensitive</label>
            <label><input type="checkbox" checked={!!config.trim_whitespace} onChange={(e) => set({ trim_whitespace: e.target.checked })} /> Trim whitespace</label>
            <label><input type="checkbox" checked={!!config.normalize_punctuation} onChange={(e) => set({ normalize_punctuation: e.target.checked })} /> Normalize punctuation</label>
          </div>
        </div>
      )}

      {type === "numeric" && (
        <div className="grid grid-cols-2 gap-2">
          <Field label="Expected value"><input type="number" className="input" value={String(config.expected_value ?? "")} onChange={(e) => set({ expected_value: parseFloat(e.target.value) })} /></Field>
          <Field label="Absolute tolerance"><input type="number" className="input" value={String(config.absolute_tolerance ?? 0)} onChange={(e) => set({ absolute_tolerance: parseFloat(e.target.value) })} /></Field>
          <Field label="Relative tolerance"><input type="number" className="input" value={String(config.relative_tolerance ?? 0)} onChange={(e) => set({ relative_tolerance: parseFloat(e.target.value) })} /></Field>
          <Field label="Required unit (optional)"><input className="input" value={String(config.required_unit ?? "")} onChange={(e) => set({ required_unit: e.target.value })} /></Field>
          <Field label="Unit aliases (comma separated)"><input className="input" value={(config.unit_aliases as string[] || []).join(", ")} onChange={(e) => set({ unit_aliases: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></Field>
        </div>
      )}

      {type === "regex" && (
        <div className="space-y-2">
          <Field label="Required patterns (one per line)"><textarea className="input mono h-16" value={(config.required_patterns as string[] || []).join("\n")} onChange={(e) => set({ required_patterns: e.target.value.split("\n").filter(Boolean) })} /></Field>
          <Field label="Optional patterns (one per line)"><textarea className="input mono h-16" value={(config.optional_patterns as string[] || []).join("\n")} onChange={(e) => set({ optional_patterns: e.target.value.split("\n").filter(Boolean) })} /></Field>
          <Field label="Forbidden patterns (one per line)"><textarea className="input mono h-16" value={(config.forbidden_patterns as string[] || []).join("\n")} onChange={(e) => set({ forbidden_patterns: e.target.value.split("\n").filter(Boolean) })} /></Field>
          <label className="text-sm"><input type="checkbox" checked={!!config.case_sensitive} onChange={(e) => set({ case_sensitive: e.target.checked })} /> Case sensitive</label>
        </div>
      )}

      {type === "concept" && (
        <div className="space-y-2">
          <Field label="Required concepts (comma separated)"><input className="input" value={(config.required_concepts as string[] || []).join(", ")} onChange={(e) => set({ required_concepts: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></Field>
          <Field label="Optional concepts (comma separated)"><input className="input" value={(config.optional_concepts as string[] || []).join(", ")} onChange={(e) => set({ optional_concepts: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></Field>
          <Field label="Forbidden claims (comma separated)"><input className="input" value={(config.forbidden_claims as string[] || []).join(", ")} onChange={(e) => set({ forbidden_claims: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></Field>
          <Field label="Points per concept"><input type="number" className="input" value={String(config.points_per_concept ?? 10)} onChange={(e) => set({ points_per_concept: parseFloat(e.target.value) })} /></Field>
          <p className="text-xs text-warn">Keyword presence alone does not prove a complex answer is correct — treat as a coverage signal.</p>
        </div>
      )}

      {type === "json" && (
        <div className="space-y-2">
          <Field label="Required fields (comma separated)"><input className="input" value={(config.required_fields as string[] || []).join(", ")} onChange={(e) => set({ required_fields: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></Field>
          <Field label="Expected field values (JSON)"><textarea className="input mono h-20" value={JSON.stringify(config.expected_field_values ?? {}, null, 2)} onChange={(e) => { try { set({ expected_field_values: JSON.parse(e.target.value) }); } catch { /* ignore */ } }} /></Field>
          <label className="text-sm"><input type="checkbox" checked={config.allow_code_fences !== false} onChange={(e) => set({ allow_code_fences: e.target.checked })} /> Allow markdown code fences</label>
        </div>
      )}

      {type === "multiple_choice" && (
        <div className="space-y-2">
          <Field label="Correct option (letter or text)"><input className="input" value={String(config.correct_option ?? "")} onChange={(e) => set({ correct_option: e.target.value })} /></Field>
          <Field label="Accepted formats (comma separated, e.g. B, Option B, Ottawa)"><input className="input" value={(config.accepted_formats as string[] || []).join(", ")} onChange={(e) => set({ accepted_formats: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></Field>
        </div>
      )}
    </div>
  );
}

function JudgeConfig({ config, onChange }: { config: Record<string, unknown>; onChange: (c: Record<string, unknown>) => void }) {
  const set = (patch: Record<string, unknown>) => onChange({ ...config, ...patch });
  const dims = (config.rubric_dimensions as { name: string; description: string; weight: number; maximum: number }[]) || [];
  const setDim = (i: number, patch: Partial<{ name: string; description: string; weight: number; maximum: number }>) => {
    const next = dims.map((d, idx) => (idx === i ? { ...d, ...patch } : d));
    set({ rubric_dimensions: next });
  };
  const totalWeight = dims.reduce((a, d) => a + (Number(d.weight) || 0), 0);
  return (
    <div className="panel p-3 space-y-2">
      <Field label="Reference answer (guidance, not required wording)"><textarea className="input h-24" value={String(config.reference_answer ?? "")} onChange={(e) => set({ reference_answer: e.target.value })} /></Field>
      <Field label="Reference facts (comma separated)"><input className="input" value={(config.reference_facts as string[] || []).join(", ")} onChange={(e) => set({ reference_facts: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></Field>
      <Field label="Required elements (comma separated)"><input className="input" value={(config.required_elements as string[] || []).join(", ")} onChange={(e) => set({ required_elements: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></Field>
      <div>
        <div className="flex items-center justify-between">
          <label className="label mb-0">Rubric dimensions</label>
          <span className="text-xs text-gray-500">total weight {totalWeight}</span>
        </div>
        <div className="space-y-2 mt-1">
          {dims.map((d, i) => (
            <div key={i} className="grid grid-cols-12 gap-2 items-center">
              <input className="input col-span-4" placeholder="name" value={d.name} onChange={(e) => setDim(i, { name: e.target.value })} />
              <input className="input col-span-4" placeholder="description" value={d.description} onChange={(e) => setDim(i, { description: e.target.value })} />
              <input type="number" className="input col-span-2" placeholder="weight" value={d.weight} onChange={(e) => setDim(i, { weight: parseFloat(e.target.value) })} />
              <input type="number" className="input col-span-1" placeholder="max" value={d.maximum} onChange={(e) => setDim(i, { maximum: parseFloat(e.target.value) })} />
              <button className="btn btn-ghost col-span-1" onClick={() => set({ rubric_dimensions: dims.filter((_, idx) => idx !== i) })}>✕</button>
            </div>
          ))}
        </div>
        <button className="btn mt-2" onClick={() => set({ rubric_dimensions: [...dims, { name: "", description: "", weight: 1, maximum: 100 }] })}>+ Add dimension</button>
      </div>
      <Field label="Critical errors (comma separated — any present caps the score)"><input className="input" value={(config.critical_errors as string[] || []).join(", ")} onChange={(e) => set({ critical_errors: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} /></Field>
      <Field label="Judge-specific instructions (optional)"><textarea className="input h-16" value={String(config.judge_instructions ?? "")} onChange={(e) => set({ judge_instructions: e.target.value })} /></Field>
    </div>
  );
}

function HybridConfig({ config, onChange }: { config: Record<string, unknown>; onChange: (c: Record<string, unknown>) => void }) {
  const set = (patch: Record<string, unknown>) => onChange({ ...config, ...patch });
  const detW = Number(config.deterministic_weight ?? 40);
  const judW = Number(config.judge_weight ?? 60);
  const total = detW + judW;
  const judge = (config.judge as Record<string, unknown>) || {};
  return (
    <div className="panel p-3 space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <Field label={`Deterministic weight (${detW})`}><input type="number" className="input" value={detW} onChange={(e) => set({ deterministic_weight: parseFloat(e.target.value) })} /></Field>
        <Field label={`Judge weight (${judW})`}><input type="number" className="input" value={judW} onChange={(e) => set({ judge_weight: parseFloat(e.target.value) })} /></Field>
      </div>
      <p className={`text-xs ${Math.abs(total - 100) < 0.01 ? "text-ok" : "text-err"}`}>Weights must total 100 (currently {total}).</p>
      <Field label="Deterministic checks (JSON array)"><textarea className="input mono h-28" value={JSON.stringify(config.deterministic_checks || [], null, 2)} onChange={(e) => { try { set({ deterministic_checks: JSON.parse(e.target.value) }); } catch { /* ignore */ } }} /></Field>
      <Field label="Judge reference answer"><textarea className="input h-16" value={String(judge.reference_answer ?? "")} onChange={(e) => set({ judge: { ...judge, reference_answer: e.target.value } })} /></Field>
      <Field label="Judge required elements (comma separated)"><input className="input" value={(judge.required_elements as string[] || []).join(", ")} onChange={(e) => set({ judge: { ...judge, required_elements: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) } })} /></Field>
      <p className="text-xs text-gray-500">Critical deterministic failures may cap the final prompt score.</p>
    </div>
  );
}
