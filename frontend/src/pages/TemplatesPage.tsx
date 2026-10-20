import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox, fmtBytes, Spinner } from "../ui";

interface Studio3 { layout_id: string; geometry_hash: string; uploaded_at: string; filename: string; bytes: number; current: boolean }
interface LayoutRow {
  layout_id?: string; size: string; size_label: string; dims?: string; arrangement?: string;
  per_half?: number; per_sheet?: number; pairs?: boolean; rows?: number[]; geometry_hash?: string;
  studio3?: Studio3 | null; error?: string;
}
interface Listing { layouts: LayoutRow[]; outdated: Studio3[] }

const FILES: [string, string][] = [
  ["svg", "SVG (cut file)"],
  ["dxf", "DXF (Studio Basic)"],
  ["json", "Position JSON"],
  ["calibration.pdf", "Calibration PDF"],
];
const fileUrl = (id: string, kind: string) =>
  `/api/templates/${encodeURIComponent(id)}/files/${encodeURIComponent(kind)}?download=1`;

function TemplateCard({ row, reload }: { row: LayoutRow; reload: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const id = row.layout_id!;
  const unit = row.pairs ? " pairs" : "";
  const upload = async (f: File) => {
    setBusy(true);
    setErr("");
    const fd = new FormData();
    fd.append("file", f);
    try {
      await api.post(`/api/templates/${encodeURIComponent(id)}/studio3`, fd);
      reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!confirm(`Remove the uploaded ${id}.studio3?`)) return;
    try {
      await api.del(`/api/templates/${encodeURIComponent(id)}/studio3`);
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const st = row.studio3;
  return (
    <section className="card template-card">
      <img className="template-preview" src={`/api/templates/${encodeURIComponent(id)}/preview.png`} alt={`${id} layout`} />
      <div>
        <h3>{id}</h3>
        <p className="muted small">
          {row.size_label} · {row.dims} · {row.arrangement}<br />
          {row.per_half}{unit} per half · {row.per_sheet}{unit} per sheet · rows {row.rows?.join(" + ")}
        </p>
        <h4>Downloads</h4>
        <ul className="plain">
          {FILES.map(([kind, label]) => (
            <li key={kind}><a href={fileUrl(id, kind)}>{label}</a></li>
          ))}
        </ul>
        <h4>Studio template (.studio3)</h4>
        {st ? (
          st.current ? (
            <p className="ok small">
              <a href={`/api/templates/${encodeURIComponent(id)}/studio3`}>{st.filename}</a> · {fmtBytes(st.bytes)} ·
              uploaded {new Date(st.uploaded_at).toLocaleString()} — current, used in bundles
            </p>
          ) : (
            <p className="bad small">
              <strong>Outdated</strong>: {st.filename} was saved for a different geometry. It is not put in bundles.
              Make it again from the SVG.
            </p>
          )
        ) : (
          <p className="muted small">None yet. Bundles use the SVG and DXF until you upload one.</p>
        )}
        <div className="actions">
          <label className="button">
            {st ? "Replace…" : "Upload .studio3…"}
            <input type="file" accept=".studio3" hidden
              onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) upload(f); }} />
          </label>
          {st && <button onClick={remove}>Remove</button>}
          {busy && <Spinner label="Uploading…" />}
        </div>
        {err && <ErrorBox message={err} />}
      </div>
    </section>
  );
}

export default function TemplatesPage() {
  const [data, setData] = useState<Listing | null>(null);
  const [err, setErr] = useState("");
  const load = () => api.get<Listing>("/api/templates").then(setData).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);
  if (err) return <ErrorBox message={err} />;
  if (!data) return <Spinner label="Loading…" />;
  return (
    <div>
      <h2>Cut templates</h2>
      <p className="muted">
        One fixed layout per label size, so one Silhouette Studio template per layout, made once and reused for
        every order. Build each template from its SVG (steps in <code>docs/studio-template-setup.md</code>), cut the
        calibration PDF on plain paper to check it, then upload the saved <code>.studio3</code> here.
      </p>
      {data.layouts.map((row) =>
        row.error ? (
          <section className="card" key={row.size}>
            <h3>{row.size_label}</h3>
            <ErrorBox message={row.error} />
          </section>
        ) : (
          <TemplateCard key={row.layout_id} row={row} reload={load} />
        ),
      )}
      {data.outdated.length > 0 && (
        <section className="card">
          <h3 className="bad">Outdated .studio3 files</h3>
          <p className="muted small">Saved for layouts that are no longer current. They are never put in bundles.</p>
          <ul>
            {data.outdated.map((s) => (
              <li key={s.layout_id} className="bad">{s.layout_id}: {s.filename} ({new Date(s.uploaded_at).toLocaleDateString()})</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
