import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Badge, Card, ConfirmButton, EmptyState, Modal, PageHeader, Spinner } from "@/components/ui";
import { useToast } from "@/store/toast";
import { fmtRelative } from "@/lib/format";
import type { BenchmarkSet } from "@/types";

export default function BenchmarkLibrary() {
  const toast = useToast();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["benchmarks"], queryFn: api.listBenchmarks });
  const [search, setSearch] = useState("");
  const filtered = data?.filter((b) => `${b.name} ${b.description} ${b.tags.join(" ")}`.toLowerCase().includes(search.toLowerCase()));
  const [creating, setCreating] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const importMut = useMutation({
    mutationFn: (file: File) => api.importBenchmark(file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["benchmarks"] });
      toast("Benchmark imported", "success");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const createMut = useMutation({
    mutationFn: (data: Partial<BenchmarkSet>) => api.createBenchmark(data),
    onSuccess: (b) => {
      qc.invalidateQueries({ queryKey: ["benchmarks"] });
      setCreating(false);
      toast("Benchmark created", "success");
      window.location.href = `/benchmarks/${b.id}`;
    },
  });

  return (
    <div>
      <PageHeader
        title="Benchmark Library"
        subtitle="Reusable benchmark sets and their prompts."
        actions={
          <>
            <input
              ref={fileRef}
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) importMut.mutate(f);
                e.target.value = "";
              }}
            />
            <button className="btn" onClick={() => fileRef.current?.click()}>
              Import JSON
            </button>
            <button className="btn btn-primary" onClick={() => setCreating(true)}>
              + New Benchmark
            </button>
          </>
        }
      />
      <div className="flex items-center gap-3 mb-4">
        <input aria-label="Search benchmarks" className="input max-w-md" placeholder="Search suites, topics, or tags…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <span className="text-xs text-gray-400">{filtered?.length ?? 0} suites</span>
      </div>
      {isLoading ? (
        <Spinner label="Loading…" />
      ) : !data || data.length === 0 ? (
        <EmptyState title="No benchmarks" hint="Create one or import a benchmark JSON file." />
      ) : filtered?.length === 0 ? (
        <EmptyState title="No matching suites" hint="Try a different title or topic." />
      ) : (
        <div className="grid md:grid-cols-2 gap-3">
          {filtered?.map((b) => (
            <Card key={b.id}>
              <div className="flex items-start justify-between gap-2">
                <Link to={`/benchmarks/${b.id}`} className="font-medium text-white hover:text-accent">
                  {b.name}
                </Link>
                <div className="flex gap-1 flex-shrink-0">
                  {b.is_example && <Badge className="text-warn border-warn/40 bg-warn/10">example</Badge>}
                  <Badge className="text-gray-400 border-border bg-bg-elev">v{b.version}</Badge>
                </div>
              </div>
              <p className="text-sm text-gray-400 mt-1 line-clamp-2">{b.description}</p>
              <div className="flex flex-wrap items-center justify-between gap-3 mt-4">
                <div className="text-xs text-gray-500">
                  {b.enabled_prompt_count} / {b.prompt_count} prompts · {fmtRelative(b.updated_at)}
                </div>
                <div className="flex gap-1">
                  <a className="btn" href={api.exportBenchmarkUrl(b.id)} download>
                    Export
                  </a>
                  <button
                    className="btn"
                    onClick={() => api.duplicateBenchmark(b.id).then(() => { qc.invalidateQueries({ queryKey: ["benchmarks"] }); toast("Duplicated", "success"); })}
                  >
                    Duplicate
                  </button>
                  <ConfirmButton
                    message={`Delete benchmark '${b.name}'? This cannot be undone.`}
                    onConfirm={() => api.deleteBenchmark(b.id).then(() => { qc.invalidateQueries({ queryKey: ["benchmarks"] }); toast("Deleted", "success"); })}
                  >
                    Delete
                  </ConfirmButton>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {creating && (
        <CreateBenchmarkModal
          onClose={() => setCreating(false)}
          onCreate={(name, description) => createMut.mutate({ name, description, prompts: [] })}
          submitting={createMut.isPending}
        />
      )}
    </div>
  );
}

function CreateBenchmarkModal({
  onClose,
  onCreate,
  submitting,
}: {
  onClose: () => void;
  onCreate: (name: string, description: string) => void;
  submitting: boolean;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  return (
    <Modal
      title="New benchmark"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={!name.trim() || submitting} onClick={() => onCreate(name.trim(), description)}>
            {submitting ? "Creating…" : "Create"}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <div>
          <label className="label">Name</label>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </div>
        <div>
          <label className="label">Description</label>
          <textarea className="input h-20" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
      </div>
    </Modal>
  );
}
