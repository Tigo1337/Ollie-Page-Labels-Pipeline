import { useEffect, useState } from "react";
import { api, Design, uploadWithProgress } from "../api";
import { ErrorBox, Progress, useAsync } from "../ui";

interface ImportReport {
  imported: { design: string; source: string; file: string }[];
  skipped: { file: string; reason: string }[];
  unknown_folders: string[];
  ignored: number;
}
interface ImportJob {
  id: string; file: string; status: "running" | "done" | "error"; done: number; total: number; current: string;
  report: ImportReport | null; error: string | null;
}

export default function DesignsPage() {
  const [tick, setTick] = useState(0);
  const designs = useAsync(() => api.get<Design[]>("/api/designs"), [tick]);
  const [uploading, setUploading] = useState<number | null>(null);   // upload progress, 0..1
  const [job, setJob] = useState<ImportJob | null>(null);
  const [err, setErr] = useState("");
  const [showNew, setShowNew] = useState(false);

  // pick up an import that is still running (e.g. after reloading the page)
  useEffect(() => {
    api.get<ImportJob | null>("/api/designs/import-zip/latest").then((j) => j && j.status === "running" && setJob(j))
      .catch(() => undefined);
  }, []);

  // poll a running import; refresh the cards every few seconds so the art appears as it lands
  useEffect(() => {
    if (!job || job.status !== "running") return;
    let n = 0;
    const t = setInterval(async () => {
      try {
        const j = await api.get<ImportJob>(`/api/designs/import-zip/${encodeURIComponent(job.id)}`);
        setJob(j);
        if (j.status !== "running" || ++n % 5 === 0) setTick((x) => x + 1);
      } catch (e) {
        setErr((e as Error).message);
        setJob(null);
      }
    }, 1000);
    return () => clearInterval(t);
  }, [job?.id, job?.status]);

  const importZip = async (file: File) => {
    setErr("");
    setJob(null);
    setUploading(0);
    const fd = new FormData();
    fd.append("file", file);
    try {
      setJob(await uploadWithProgress<ImportJob>("/api/designs/import-zip", fd, setUploading));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setUploading(null);
    }
  };
  const busy = uploading !== null || job?.status === "running";

  const list = designs.data ?? [];
  const missing = list.filter((d) => !d.art.wide || !d.art.square).length;

  return (
    <div>
      <div className="row-between">
        <h2>Designs</h2>
        <div className="actions">
          <label className="button">
            Bulk import ZIP…
            <input type="file" accept=".zip" hidden disabled={busy}
              onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) importZip(f); }} />
          </label>
          <button onClick={() => setShowNew((s) => !s)}>New design</button>
        </div>
      </div>
      <p className="muted">
        ZIP your <code>Label Designs</code> folder (right-click it → Send to → Compressed (zipped) folder):
        each design's folder holds <code>&lt;id&gt;_wide.jpg</code> and <code>&lt;id&gt;_square.jpg</code>, matched to
        designs by folder name. Sub-folders inside a design folder are ignored.
        {missing > 0 && ` ${missing} design${missing === 1 ? "" : "s"} still need artwork.`}
      </p>
      {uploading !== null && (
        <Progress value={uploading} label={`Uploading the ZIP… ${Math.round(uploading * 100)} %`} />
      )}
      {job?.status === "running" && (
        <Progress value={job.total ? job.done / job.total : 0}
          label={job.total ? `Importing artwork… ${job.done} / ${job.total} images${job.current ? ` · ${job.current.split(/[\\/]/).slice(-2).join("/")}` : ""}`
            : "Reading the ZIP…"} />
      )}
      {err && <ErrorBox message={err} />}
      {job?.status === "error" && <ErrorBox message={job.error ?? "The import failed."} />}
      {job?.status === "done" && job.report && <ImportResult report={job.report} />}
      {showNew && <NewDesign onCreated={() => { setShowNew(false); setTick((t) => t + 1); }} />}
      {designs.error && <ErrorBox message={designs.error} />}
      <div className="design-grid">
        {list.map((d) => (
          <a key={d.id} className="design-card" href={`#/designs/${encodeURIComponent(d.id)}`}>
            {d.art.wide ? (
              <img src={`/api/designs/${d.id}/art/wide?w=480&v=${d.art.wide_version}`} alt="" />
            ) : (
              <div className="no-art">No wide art</div>
            )}
            <div className="design-card-body">
              <span className="swatch" style={{ background: d.fill, outlineColor: d.stroke }} />
              <strong>{d.name}</strong>
              <span className="muted"> {d.id}</span>
              <div className="badges">
                <span className={d.art.wide ? "ok" : "bad"}>wide</span>
                <span className={d.art.square ? "ok" : "bad"}>square</span>
                {Object.keys(d.presets).length > 0 && <span>{Object.keys(d.presets).length} presets</span>}
              </div>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}

function ImportResult({ report }: { report: ImportReport }) {
  return (
    <div className="card">
      <strong>Imported {report.imported.length} image{report.imported.length === 1 ? "" : "s"}.</strong>
      {report.ignored > 0 && (
        <span className="muted"> {report.ignored} file{report.ignored === 1 ? "" : "s"} in sub-folders of design folders (like test-labels) ignored.</span>
      )}
      {report.unknown_folders.length > 0 && (
        <p className="bad">
          No design matches these folders: {report.unknown_folders.join(", ")}. Create the design first (New design)
          with the folder name as its id, then import again.
        </p>
      )}
      {report.skipped.length > 0 && (
        <details>
          <summary>{report.skipped.length} file{report.skipped.length === 1 ? "" : "s"} skipped</summary>
          <ul>{report.skipped.map((s) => <li key={s.file}><code>{s.file}</code>: {s.reason}</li>)}</ul>
        </details>
      )}
    </div>
  );
}

function NewDesign({ onCreated }: { onCreated: () => void }) {
  const [f, setF] = useState({ id: "", name: "", fill: "#1F3B63", stroke: "#FFFFFF", char_end: 0.25 });
  const [err, setErr] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.post("/api/designs", f);
      onCreated();
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  return (
    <form className="card grid-form" onSubmit={submit}>
      <label>Id (folder name)<input value={f.id} onChange={(e) => setF({ ...f, id: e.target.value })} placeholder="sea-turtle" required /></label>
      <label>Name<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Sea Turtle" required /></label>
      <label>Name colour<input type="color" value={f.fill} onChange={(e) => setF({ ...f, fill: e.target.value.toUpperCase() })} /></label>
      <label>Stroke colour<input type="color" value={f.stroke} onChange={(e) => setF({ ...f, stroke: e.target.value.toUpperCase() })} /></label>
      <label>Character ends at (0–1)<input type="number" step="0.01" min="0" max="0.9" value={f.char_end} onChange={(e) => setF({ ...f, char_end: Number(e.target.value) })} /></label>
      <div className="actions span2"><button className="primary">Create</button></div>
      {err && <div className="span2"><ErrorBox message={err} /></div>}
    </form>
  );
}
