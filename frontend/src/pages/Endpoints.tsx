import { PROVIDERS } from "@/lib/providers";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { api } from "@/api/client";
import { Badge, Card, ConfirmButton, EmptyState, Modal, PageHeader, Spinner } from "@/components/ui";
import { useToast } from "@/store/toast";
import type { ConnectionTestResult, EndpointProfile, FetchModelsResult } from "@/types";

const schema = z.object({
  name: z.string().min(1, "Name is required"),
  base_url: z.string().trim().min(1, "Base URL is required").refine((v) => !/[{}]/.test(v), "Replace the workspace placeholder with your workspace ID"),
  default_model: z.string().optional().default(""),
  request_timeout: z.coerce.number().positive("Must be > 0"),
  verify_tls: z.boolean().default(true),
  enabled: z.boolean().default(true),
  notes: z.string().optional().default(""),
  api_key_env_var: z.string().optional().default(""),
  custom_headers: z.string().optional().default("{}").refine(isValidJson, "Enter a JSON object"),
  extra_body_params: z.string().optional().default("{}").refine(isValidJson, "Enter a JSON object"),
  api_key: z.string().optional().default(""),
  input_price_per_1m: z.coerce.number().finite().min(0).optional().default(0),
  output_price_per_1m: z.coerce.number().finite().min(0).optional().default(0),
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
    input_price_per_1m: p?.input_price_per_1m ?? 0,
    output_price_per_1m: p?.output_price_per_1m ?? 0,
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
        custom_headers: JSON.parse(values.custom_headers.trim() || "{}"),
        extra_body_params: JSON.parse(values.extra_body_params.trim() || "{}"),
        api_key: values.api_key || undefined,
        input_price_per_1m: values.input_price_per_1m,
        output_price_per_1m: values.output_price_per_1m,
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
              <div className="flex flex-col lg:flex-row items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-white">{p.name}</span>
                    {!p.enabled && <Badge className="text-gray-500 border-border bg-bg-elev">disabled</Badge>}
                    {p.has_api_key && <Badge className="text-ok border-ok/40 bg-ok/10">{p.api_key_storage === "session" ? "key in server memory" : "key saved"}</Badge>}
                  </div>
                  <div className="text-sm text-gray-400 mono truncate mt-1">{p.base_url}</div>
                  {p.default_model && <div className="text-xs text-gray-500 mt-1">Default model: {p.default_model}</div>}
                  {p.has_api_key && p.api_key_storage === "session" && <p className="text-xs text-warn mt-1">Re-enter this key after restarting Bench Studio, or use an environment variable to keep it available.</p>}
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
                <div className="flex flex-wrap gap-2">
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
  const toast = useToast();
  const [loading, setLoading] = useState(false);
  return (
    <button
      className="btn"
      disabled={loading}
      onClick={async () => {
        setLoading(true);
        try {
          onResult(await api.testEndpoint(id));
        } catch (error) {
          toast(error instanceof Error ? error.message : "Connection test failed", "error");
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
  const toast = useToast();
  const [loading, setLoading] = useState(false);
  return (
    <button
      className="btn"
      disabled={loading}
      onClick={async () => {
        setLoading(true);
        try {
          onResult(await api.fetchModels(id));
        } catch (error) {
          toast(error instanceof Error ? error.message : "Model discovery failed", "error");
        } finally {
          setLoading(false);
        }
      }}
    >
      {loading ? "Fetching…" : "Models"}
    </button>
  );
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
    setValue,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: profileToForm(initial ?? undefined) });
  const [providerId, setProviderId] = useState("custom");
  const provider = PROVIDERS.find((p) => p.id === providerId)!;
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
      <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
        {!initial && <div className="rounded-lg border border-accent/30 bg-accent/5 p-3 space-y-2">
          <label className="label" htmlFor="provider">Provider preset</label>
          <select id="provider" className="input" value={providerId} onChange={(e) => {
            const next = PROVIDERS.find((p) => p.id === e.target.value)!;
            setProviderId(next.id);
            setValue("name", next.id === "custom" ? "" : next.name);
            setValue("base_url", next.url);
            setValue("api_key_env_var", next.env);
            setValue("default_model", "");
            setValue("api_key", "");
            setValue("custom_headers", "{}");
            setValue("extra_body_params", "{}");
            setValue("verify_tls", true);
            setValue("input_price_per_1m", 0);
            setValue("output_price_per_1m", 0);
          }}>
            {PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <p className="text-xs text-gray-400">{provider.hint} {provider.docs && <a className="text-accent underline" href={provider.docs} target="_blank" rel="noreferrer">Provider docs ↗</a>}</p>
        </div>}
        <div>
          <label className="label" htmlFor="name">Display name</label>
          <input id="name" className="input" {...register("name")} />
          {errors.name && <p className="text-err text-xs mt-1">{errors.name.message}</p>}
        </div>
        <div>
          <label className="label" htmlFor="base_url">Base URL</label>
          <input id="base_url" className="input mono" {...register("base_url")} placeholder="http://127.0.0.1:11434/v1" />
          {errors.base_url && <p className="text-err text-xs mt-1">{errors.base_url.message}</p>}
          <p className="text-xs text-gray-500 mt-1">Use the API base URL, without /chat/completions. Provider-specific paths are preserved.</p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="default_model">Default model</label>
            <input id="default_model" className="input" {...register("default_model")} placeholder="Model ID from your provider" />
          </div>
          <div>
            <label className="label" htmlFor="request_timeout">Request timeout (s)</label>
            <input id="request_timeout" type="number" step="1" className="input" {...register("request_timeout")} />
            {errors.request_timeout && <p className="text-err text-xs mt-1">{errors.request_timeout.message}</p>}
          </div>
        </div>
        <div>
          <label className="label" htmlFor="api_key">API key (write-only; never returned)</label>
          <input id="api_key" className="input mono" type="password" {...register("api_key")} placeholder={initial?.has_api_key ? "•••••••• (leave blank to keep)" : "Optional — many local servers need none"} />
          {initial?.has_api_key && <p className="text-xs text-ok mt-1">A key is stored for this profile.</p>}
        </div>
        <div>
          <label className="label" htmlFor="api_key_env_var">API key environment variable</label>
          <input id="api_key_env_var" className="input" {...register("api_key_env_var")} placeholder="e.g. OPENAI_API_KEY" />
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
          <label className="label" htmlFor="custom_headers">Custom headers (JSON)</label>
          <textarea id="custom_headers" className="input mono h-20" {...register("custom_headers")} />
          {!headersValid && <p className="text-err text-xs mt-1">Enter a JSON object</p>}
        </div>
        <div>
          <label className="label" htmlFor="extra_body_params">Extra body parameters (JSON)</label>
          <textarea id="extra_body_params" className="input mono h-20" {...register("extra_body_params")} />
          {!extraValid && <p className="text-err text-xs mt-1">Enter a JSON object</p>}
        </div>
        <div>
          <label className="label" htmlFor="notes">Notes</label>
          <textarea id="notes" className="input h-16" {...register("notes")} />
        </div>
        <PricingSection register={register} errors={errors} />
      </form>
    </Modal>
  );
}

function isValidJson(s: string | undefined): boolean {
  if (!s?.trim()) return true;
  try {
    const value = JSON.parse(s);
    return value !== null && typeof value === "object" && !Array.isArray(value);
  } catch {
    return false;
  }
}

function PricingSection({ register, errors }: {
  register: ReturnType<typeof useForm<FormValues>>["register"];
  errors: ReturnType<typeof useForm<FormValues>>["formState"]["errors"];
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-t border-border pt-3 mt-1">
      <button
        type="button"
        className="text-xs text-gray-400 hover:text-gray-200 flex items-center gap-1"
        onClick={() => setOpen(!open)}
      >
        <span className={`transition-transform ${open ? "rotate-90" : ""}`}>▸</span>
        Pricing (optional)
      </button>
      {open && (
        <div className="grid grid-cols-2 gap-3 mt-3">
          <div>
            <label className="label" htmlFor="input_price_per_1m">Input price per 1M tokens ($)</label>
            <input
              id="input_price_per_1m"
              type="number"
              step="0.0001"
              min="0"
              className="input mono"
              placeholder="e.g. 0.15"
              {...register("input_price_per_1m")}
            />
            {errors.input_price_per_1m && <p className="text-err text-xs mt-1">{errors.input_price_per_1m.message}</p>}
            <p className="text-xs text-gray-500 mt-1">USD per million input/prompt tokens.</p>
          </div>
          <div>
            <label className="label" htmlFor="output_price_per_1m">Output price per 1M tokens ($)</label>
            <input
              id="output_price_per_1m"
              type="number"
              step="0.0001"
              min="0"
              className="input mono"
              placeholder="e.g. 0.60"
              {...register("output_price_per_1m")}
            />
            {errors.output_price_per_1m && <p className="text-err text-xs mt-1">{errors.output_price_per_1m.message}</p>}
            <p className="text-xs text-gray-500 mt-1">USD per million output/completion tokens.</p>
          </div>
        </div>
      )}
    </div>
  );
}
