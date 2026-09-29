import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Badge, Card, PageHeader, Spinner } from "@/components/ui";
import { useToast } from "@/store/toast";
import type { AppSettings } from "@/types";

export default function SettingsPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const { data: diag } = useQuery({ queryKey: ["diagnostics"], queryFn: api.diagnostics });
  const [form, setForm] = useState<AppSettings | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  if (isLoading || !form) return <Spinner label="Loading settings…" />;

  const set = (patch: Partial<AppSettings>) => setForm((cur) => (cur ? { ...cur, ...patch } : cur));
  const setWeight = (key: keyof AppSettings["composite_weights"], val: number) =>
    setForm((cur) => (cur ? { ...cur, composite_weights: { ...cur.composite_weights, [key]: val } } : cur));

  const save = async () => {
    setSaving(true);
    try {
      await api.updateSettings(form);
      await qc.invalidateQueries({ queryKey: ["settings"] });
      toast("Settings saved", "success");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  };

  const weightTotal = form.composite_weights.quality + form.composite_weights.reliability + form.composite_weights.performance;

  return (
    <div>
      <PageHeader title="Settings" subtitle="Global limits and application configuration." actions={<button className="btn btn-primary" disabled={saving} onClick={save}>{saving ? "Saving…" : "Save"}</button>} />
      <div className="grid md:grid-cols-2 gap-4">
        <Card>
          <h3 className="font-medium text-white mb-3">Global generation settings</h3>
          <p className="text-xs text-gray-400 mb-3">Token limits and inactivity timeout apply to every new run and are saved with its results. Active generation has no total time limit. Changes apply to subsequent runs.</p>
          <div className="grid grid-cols-2 gap-3">
            <NumField label="Inactivity timeout (s)" value={form.default_timeout} onChange={(v) => set({ default_timeout: v })} />
            <NumField label="Retry max attempts" value={form.default_retry_max_attempts} onChange={(v) => set({ default_retry_max_attempts: v })} />
            <NumField label="Retry backoff base (s)" value={form.default_retry_backoff_base} onChange={(v) => set({ default_retry_backoff_base: v })} />
            <NumField label="Retry backoff max (s)" value={form.default_retry_backoff_max} onChange={(v) => set({ default_retry_backoff_max: v })} />
            <NumField label="Default temperature" value={form.default_temperature} onChange={(v) => set({ default_temperature: v })} step={0.1} />
            <NumField label="Default top-p" value={form.default_top_p} onChange={(v) => set({ default_top_p: v })} step={0.05} />
            <NumField label="Max tokens per question (0 = server default)" value={form.default_max_tokens} onChange={(v) => set({ default_max_tokens: v })} />
            <div>
              <label className="label">Log level</label>
              <select className="input" value={form.log_level} onChange={(e) => set({ log_level: e.target.value })}>
                {["DEBUG", "INFO", "WARNING", "ERROR"].map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
            </div>
          </div>
        </Card>
        <Card>
          <h3 className="font-medium text-white mb-3">Composite-score weights</h3>
          <div className="grid grid-cols-3 gap-3">
            <NumField label="Quality %" value={Math.round(form.composite_weights.quality * 100)} onChange={(v) => setWeight("quality", v / 100)} />
            <NumField label="Reliability %" value={Math.round(form.composite_weights.reliability * 100)} onChange={(v) => setWeight("reliability", v / 100)} />
            <NumField label="Performance %" value={Math.round(form.composite_weights.performance * 100)} onChange={(v) => setWeight("performance", v / 100)} />
          </div>
          <p className={`text-xs mt-2 ${Math.abs(weightTotal - 1) < 0.001 ? "text-ok" : "text-err"}`}>Total: {Math.round(weightTotal * 100)}% (should be 100%)</p>
          <p className="text-xs text-gray-500 mt-2">This is a user-configurable utility score, not a universal intelligence score. Default: Quality 85% / Reliability 10% / Performance 5%.</p>
          <div className="mt-4 space-y-2">
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.automatic_backup} onChange={(e) => set({ automatic_backup: e.target.checked })} /> Automatic backup</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.launch_browser} onChange={(e) => set({ launch_browser: e.target.checked })} /> Launch browser on start</label>
          </div>
        </Card>
        <Card className="md:col-span-2">
          <h3 className="font-medium text-white mb-3">Security &amp; storage</h3>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <KV k="Local data path" v={form.local_data_path} />
            <KV k="Keyring available" v={form.keyring_available ? "yes" : "no — fallback only"} />
            <KV k="Plaintext key fallback" v={form.allow_plaintext_key_fallback ? "enabled (keys in SQLite)" : "disabled"} />
          </div>
          {!form.keyring_available && (
            <p className="text-xs text-warn mt-2">The OS credential store is unavailable. API keys can be provided per-session or via environment variables, but cannot be saved securely.</p>
          )}
        </Card>
        {diag && (
          <Card className="md:col-span-2">
            <h3 className="font-medium text-white mb-3">Diagnostics</h3>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <KV k="Application version" v={String((diag as Record<string, unknown>).application_version ?? "")} />
              <KV k="Python version" v={String((diag as Record<string, unknown>).python_version ?? "")} />
              <KV k="Platform" v={String((diag as Record<string, unknown>).platform ?? "")} />
              <KV k="Frontend built" v={String((diag as Record<string, unknown>).frontend_built ?? "")} />
            </div>
            {!!(diag as Record<string, unknown>).recent_errors && (
              <div className="mt-3">
                <div className="text-xs text-gray-500 mb-1">Recent sanitized errors</div>
                {((diag as Record<string, string[]>).recent_errors || []).length === 0 ? (
                  <span className="text-xs text-gray-500">None.</span>
                ) : (
                  <ul className="text-xs text-err list-disc pl-5">
                    {((diag as Record<string, string[]>).recent_errors || []).map((e, i) => <li key={i}>{e}</li>)}
                  </ul>
                )}
              </div>
            )}
            <div className="mt-3">
              <a className="btn" href="/api/diagnostics" target="_blank" rel="noreferrer">Download full diagnostics report</a>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

function NumField({ label, value, onChange, step }: { label: string; value: number; onChange: (v: number) => void; step?: number }) {
  return (
    <div>
      <label className="label">{label}</label>
      <input type="number" step={step ?? 1} className="input" value={value} onChange={(e) => onChange(parseFloat(e.target.value))} />
    </div>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div className="text-xs text-gray-500">{k}</div>
      <div className="text-gray-200 mono text-sm break-all">{v}</div>
    </div>
  );
}
