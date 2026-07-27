import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { api } from "@/api/client";
import { Badge, Card, ConfirmButton, EmptyState, Modal, PageHeader, Spinner, StatCard } from "@/components/ui";
import { useToast } from "@/store/toast";
import type { ConnectionTestResult, EndpointProfile, FetchModelsResult } from "@/types";

const schema = z.object({
  name: z.string().min(1, "Name is required"),
  base_url: z.string().min(1, "Base URL is required"),
  default_model: z.string().optional().default(""),
  request_timeout: z.coerce.number().positive("Must be > 0"),
  verify_tls: z.boolean().default(true),
  enabled: z.boolean().default(true),
  notes: z.string().optional().default(""),
  api_key_env_var: z.string().optional().default(""),
  custom_headers: z.string().optional().default("{}"),
  extra_body_params: z.string().optional().default("{}"),
  api_key: z.string().optional().default(""),
});
type FormValues = z.infer<typeof schema>;

function profileToForm(p?: EndpointProfile): FormValues {
  return {
    name: p?.name ?? "",
    base_url: p?.base_url ?? "http://127.0.0.1:11434/v1",
    default_model: p?.default_model ?? "",
    request_timeout: p?.request_timeout ?? 60,
    verify_tls: p?.verify_tls ?? true,
    enabled: p?.enabled ?? true,
    notes: p?.notes ?? "",
    api_key_env_var: p?.api_key_env_var ?? "",
    custom_headers: JSON.stringify(p?.custom_headers ?? {}, null, 2),
    extra_body_params: JSON.stringify(p?.extra_body_params ?? {}, null, 2),
    api_key: "",
  };
}

export default function Endpoints() {
  const toast = useToast();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["endpoints"], queryFn: api.listEndpoints });
  const [editing, setEditing] = useState<EndpointProfile | null>(null);
  const [creating, setCreating] = useState(false);
  const [testResult, setTestResult] = useState<Record<string, ConnectionTestResult>>({});
  const [models, setModels] = useState<Record<string, FetchModelsResult>>({});

  const saveMutation = useMutation({
    mutationFn: async ({ id, values }: { id: string | null; values: FormValues }) => {
      const payload = {
        name: values.name,
        base_url: values.base_url,
        default_model: values.default_model,
        request_timeout: values.request_timeout,
        verify_tls: values.verify_tls,
        enabled: values.enabled,
        notes: values.notes,
        api_key_env_var: values.api_key_env_var,
        custom_headers: safeJson(values.custom_headers, {}),
        extra_body_params: safeJson(values.extra_body_params, {}),
        api_key: values.api_key || undefined,
      };
      return id ? api.updateEndpoint(id, payload) : api.createEndpoint(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["endpoints"] });
      setEditing(null);
      setCreating(false);
      toast("Endpoint saved", "success");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  return (
    <div>
      <PageHeader
        title="Endpoint Profiles"
        subtitle="OpenAI-compatible target and judge endpoints. Keys are never returned after saving."
        actions={<button className="btn btn-primary" onClick={() => setCreating(true)}>+ New Endpoint</button>}
      />
      {isLoading ? (
        <Spinner label="Loading endpoints…" />
      ) : !data || data.length === 0 ? (
        <EmptyState title="No endpoint profiles" hint="Add an OpenAI-compatible endpoint to start benchmarking." />
      ) : (
        <div className="space-y-3">
          {data.map((p) => (
            <Card key={p.id}>
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-white">{p.name}</span>
                    {!p.enabled && <Badge className="text-gray-500 border-border bg-bg-elev">disabled</Badge>}
                    {p.has_api_key && <Badge className="text-ok border-ok/40 bg-ok/10">key saved</Badge>}
                  </div>
                  <div className="text-sm text-gray-400 mono truncate mt-1">{p.base_url}</div>
                  {p.default_model && <div className="text-xs text-gray-500 mt-1">Default model: {p.default_model}</div>}
                  {testResult[p.id] && (
                    <div className="mt-3 text-xs">
                      <Badge className={testResult[p.id].reachable ? "text-ok border-ok/40 bg-ok/10" : "text-err border-err/40 bg-err/10"}>
                        {testResult[p.id].reachable ? "Reachable" : "Unreachable"}
                      </Badge>
                      {testResult[p.id].http_status != null && (
                        <span className="ml-2 text-gray-400">HTTP {testResult[p.id].http_status}</span>
                      )}
                      {testResult[p.id].response_time_ms != null && (
                        <span className="ml-2 text-gray-400">{testResult[p.id].response_time_ms} ms</span>
                      )}
                      {testResult[p.id].models_discovered && (
                        <span className="ml-2 text-gray-400">{testResult[p.id].model_count} models</span>
                      )}
                      {testResult[p.id].completion_checked && (
                        <Badge className={`ml-2 ${testResult[p.id].completion_ok ? "text-ok border-ok/40 bg-ok/10" : "text-err border-err/40 bg-err/10"}`}>
                          {testResult[p.id].completion_ok
                            ? `Completion ✓${testResult[p.id].completion_model ? ` (${testResult[p.id].completion_model})` : ""}`
                            : "Completion ✗"}
                        </Badge>
                      )}
                      {testResult[p.id].error && (
                        <span className="ml-2 text-err">{testResult[p.id].error}</span>
                      )}
                    </div>
                  )}
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  <TestButton id={p.id} onResult={(r) => setTestResult((s) => ({ ...s, [p.id]: r }))} />
                  <ModelsButton id={p.id} onResult={(r) => setModels((s) => ({ ...s, [p.id]: r }))} />
                  <button className="btn" onClick={() => setEditing(p)}>Edit</button>
                  <button
                    className="btn"
                    onClick={() => saveMutation.mutateAsync({ id: null, values: profileToForm(p) }).then(() => toast("Duplicated", "success"))}
                  >
                    Duplicate
                  </button>
                  <ConfirmButton message={`Delete endpoint '${p.name}'?`} onConfirm={() => api.deleteEndpoint(p.id).then(() => { qc.invalidateQueries({ queryKey: ["endpoints"] }); toast("Deleted", "success"); })}>
                    Delete
                  </ConfirmButton>
                </div>
              </div>
              {models[p.id] && (
                <div className="mt-3 border-t border-border pt-3">
                  <div className="text-xs text-gray-500 mb-1">Available models</div>
                  {models[p.id].success ? (
                    <div className="flex flex-wrap gap-1">
                      {models[p.id].models.map((m) => (
                        <span key={m} className="badge text-gray-300 border-border bg-bg-elev mono">{m}</span>
                      ))}
                    </div>
                  ) : (
                    <span className="text-err text-sm">{models[p.id].error}</span>
                  )}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      {(creating || editing) && (
        <EndpointForm
          initial={editing}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSubmit={(values) => saveMutation.mutate({ id: editing?.id ?? null, values })}
          submitting={saveMutation.isPending}
        />
      )}
    </div>
  );
}

function TestButton({ id, onResult }: { id: string; onResult: (r: ConnectionTestResult) => void }) {
  const [loading, setLoading] = useState(false);
  return (
    <button
      className="btn"
      disabled={loading}
      onClick={async () => {
        setLoading(true);
        try {
          onResult(await api.testEndpoint(id));
        } finally {
          setLoading(false);
        }
      }}
    >
      {loading ? "Testing…" : "Test"}
    </button>
  );
}

function ModelsButton({ id, onResult }: { id: string; onResult: (r: FetchModelsResult) => void }) {
  const [loading, setLoading] = useState(false);
  return (
    <button
      className="btn"
      disabled={loading}
      onClick={async () => {
        setLoading(true);
        try {
          onResult(await api.fetchModels(id));
        } finally {
          setLoading(false);
        }
      }}
    >
      {loading ? "Fetching…" : "Models"}
    </button>
  );
}

function safeJson(s: string, fallback: unknown): Record<string, unknown> {
  try {
    return JSON.parse(s);
  } catch {
    return fallback as Record<string, unknown>;
  }
}

function EndpointForm({
  initial,
  onClose,
  onSubmit,
  submitting,
}: {
  initial: EndpointProfile | null;
  onClose: () => void;
  onSubmit: (v: FormValues) => void;
  submitting: boolean;
}) {
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: profileToForm(initial ?? undefined) });
  const headers = watch("custom_headers");
  const extra = watch("extra_body_params");
  const headersValid = isValidJson(headers);
  const extraValid = isValidJson(extra);

  return (
    <Modal
      title={initial ? "Edit endpoint" : "New endpoint"}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button
            className="btn btn-primary"
            disabled={submitting || !headersValid || !extraValid}
            onClick={handleSubmit(onSubmit)}
          >
            {submitting ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <form className="space-y-3" onSubmit={handleSubmit(onSubmit)}>
        <div>
          <label className="label">Display name</label>
          <input className="input" {...register("name")} />
          {errors.name && <p className="text-err text-xs mt-1">{errors.name.message}</p>}
        </div>
        <div>
          <label className="label">Base URL</label>
          <input className="input mono" {...register("base_url")} placeholder="http://127.0.0.1:11434/v1" />
          {errors.base_url && <p className="text-err text-xs mt-1">{errors.base_url.message}</p>}
          <p className="text-xs text-gray-500 mt-1">Both <code>http://host</code> and <code>http://host/v1</code> are accepted; duplicates are normalized.</p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Default model</label>
            <input className="input" {...register("default_model")} />
          </div>
          <div>
            <label className="label">Request timeout (s)</label>
            <input type="number" step="1" className="input" {...register("request_timeout")} />
            {errors.request_timeout && <p className="text-err text-xs mt-1">{errors.request_timeout.message}</p>}
          </div>
        </div>
        <div>
          <label className="label">API key (write-only; never returned)</label>
          <input className="input mono" type="password" {...register("api_key")} placeholder={initial?.has_api_key ? "•••••••• (leave blank to keep)" : "Optional — many local servers need none"} />
          {initial?.has_api_key && <p className="text-xs text-ok mt-1">A key is stored for this profile.</p>}
        </div>
        <div>
          <label className="label">API key environment variable</label>
          <input className="input" {...register("api_key_env_var")} placeholder="e.g. OPENAI_API_KEY" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" {...register("verify_tls")} /> Verify TLS
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" {...register("enabled")} /> Enabled
          </label>
        </div>
        <div>
          <label className="label">Custom headers (JSON)</label>
          <textarea className="input mono h-20" {...register("custom_headers")} />
          {!headersValid && <p className="text-err text-xs mt-1">Invalid JSON</p>}
        </div>
        <div>
          <label className="label">Extra body parameters (JSON)</label>
          <textarea className="input mono h-20" {...register("extra_body_params")} />
          {!extraValid && <p className="text-err text-xs mt-1">Invalid JSON</p>}
        </div>
        <div>
          <label className="label">Notes</label>
          <textarea className="input h-16" {...register("notes")} />
        </div>
      </form>
    </Modal>
  );
}

function isValidJson(s: string | undefined): boolean {
  if (!s) return true;
  try {
    JSON.parse(s);
    return true;
  } catch {
    return false;
  }
}
