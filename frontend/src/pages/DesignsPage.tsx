import { useState } from "react";
import { api, Design } from "../api";
import { ErrorBox, Spinner, useAsync } from "../ui";

interface ImportReport {
  imported: { design: string; source: string; file: string }[];
  skipped: { file: string; reason: string }[];
  unknown_folders: string[];
  ignored: number;
}

export default function DesignsPage() {
  const [tick, setTick] = useState(0);
  const designs = useAsync(() => api.get<Design[]>("/api/designs"), [tick]);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [err, setErr] = useState("");
  const [showNew, setShowNew] = useState(false);

  const importZip = async (file: File) => {
    setBusy(true);
    setErr("");
    setReport(null);
    const fd = new FormData();
    fd.append("file", file);
    try {
      setReport(await api.post<ImportReport>("/api/designs/import-zip", fd));
      setTick((t) => t + 1);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const list = designs.data ?? [];
  const missing = list.filter((d) => !d.art.wide || !d.art.square).length;

  return (
    <div>
      <div className="row-between">
        <h2>Designs</h2>
        <div className="actions">
          <label className="button">
            Bulk import ZIP…
            <input type="file" accept=".zip" hidden onChange={(e) => e.target.files?.[0] && importZip(e.target.files[0])} />
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
      {busy && <Spinner label="Importing and trimming artwork…" />}
      {err && <ErrorBox message={err} />}
      {report && <ImportResult report={report} />}
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
