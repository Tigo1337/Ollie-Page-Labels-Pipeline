import { useEffect, useState } from "react";
import { api, Design } from "../api";
import { useApp } from "../App";
import { ErrorBox, Spinner, useAsync } from "../ui";

export default function DesignPage({ id }: { id: string }) {
  const { catalog } = useApp();
  const [tick, setTick] = useState(0);
  const design = useAsync(() => api.get<Design>(`/api/designs/${encodeURIComponent(id)}`), [id, tick]);
  const d = design.data;

  if (design.error) return <ErrorBox message={design.error} />;
  if (!d) return <Spinner label="Loading…" />;
  const refresh = () => setTick((t) => t + 1);

  return (
    <div>
      <p><a href="#/designs">← All designs</a></p>
      <h2>{d.name} <span className="muted">({d.id})</span></h2>
      <div className="two-col">
        <ArtPanel design={d} source="wide" onChange={refresh}
          help="Wide strip (about 2752 × 1536): the white letterbox is trimmed automatically." />
        <ArtPanel design={d} source="square" onChange={refresh}
          help="Square image (about 2048 × 2048) for round and square labels." />
      </div>
      <CropSummary design={d} />
      <SettingsPanel design={d} onSaved={refresh} />
      <ReviewPanel design={d} fonts={catalog.fonts.map((f) => ({ id: f.id, name: f.name }))} />
    </div>
  );
}

function ArtPanel({ design, source, help, onChange }: { design: Design; source: "wide" | "square"; help: string; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const has = design.art[source];
  const size = design.art[`${source}_size`];
  const version = design.art[`${source}_version`];
  const upload = async (file: File) => {
    setBusy(true);
    setErr("");
    const fd = new FormData();
    fd.append("file", file);
    try {
      await api.post(`/api/designs/${design.id}/art/${source}`, fd);
      onChange();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card">
      <div className="row-between">
        <h3>{source === "wide" ? "Wide art (trimmed)" : "Square art"}</h3>
        <label className="button">
          {has ? "Replace…" : "Upload…"}
          <input type="file" accept="image/png,image/jpeg,image/webp" hidden
            onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        </label>
      </div>
      <p className="muted small">{help}</p>
      {busy && <Spinner label="Uploading…" />}
      {err && <ErrorBox message={err} />}
      {has ? (
        <>
          <img className={`art art-${source}`} src={`/api/designs/${design.id}/art/${source}?w=1200&v=${version}`} alt="" />
          <p className="muted small">
            {size?.[0]} × {size?.[1]} px ·{" "}
            <a href={`/api/designs/${design.id}/art/${source}?variant=original`} target="_blank" rel="noreferrer">original</a>
          </p>
        </>
      ) : (
        <div className="no-art tall">No {source} artwork yet</div>
      )}
    </section>
  );
}

function SettingsPanel({ design, onSaved }: { design: Design; onSaved: () => void }) {
  const [f, setF] = useState({
    name: design.name, fill: design.fill, stroke: design.stroke, char_end: design.char_end,
    stroke_ratio: design.stroke_ratio, cap_frac: design.cap_frac,
  });
  const [err, setErr] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    setF({ name: design.name, fill: design.fill, stroke: design.stroke, char_end: design.char_end,
      stroke_ratio: design.stroke_ratio, cap_frac: design.cap_frac });
  }, [design]);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    try {
      await api.patch(`/api/designs/${design.id}`, f);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      onSaved();
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  return (
    <section className="card">
      <h3>Name style</h3>
      <form className="grid-form" onSubmit={save}>
        <label>Design name<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label>Name colour
          <span className="color-row">
            <input type="color" value={f.fill} onChange={(e) => setF({ ...f, fill: e.target.value.toUpperCase() })} />
            <input value={f.fill} onChange={(e) => setF({ ...f, fill: e.target.value })} />
          </span>
        </label>
        <label>Stroke colour
          <span className="color-row">
            <input type="color" value={f.stroke} onChange={(e) => setF({ ...f, stroke: e.target.value.toUpperCase() })} />
            <input value={f.stroke} onChange={(e) => setF({ ...f, stroke: e.target.value })} />
          </span>
        </label>
        <label>Stroke width (fraction of cap height)
          <span className="color-row">
            <input type="number" step="0.01" min="0" max="0.5" placeholder={`auto (${design.effective_stroke_ratio})`}
              value={f.stroke_ratio ?? ""} onChange={(e) => setF({ ...f, stroke_ratio: e.target.value === "" ? null : Number(e.target.value) })} />
            <small className="muted">blank = auto: 0.20 for a light stroke, 0.14 for a dark one</small>
          </span>
        </label>
        <label>Max cap height (fraction of name box)
          <input type="number" step="0.01" min="0.1" max="1" value={f.cap_frac} onChange={(e) => setF({ ...f, cap_frac: Number(e.target.value) })} />
        </label>
        <label>Character ends at (fraction of the wide strip)
          <input type="number" step="0.01" min="0" max="0.9" value={f.char_end} onChange={(e) => setF({ ...f, char_end: Number(e.target.value) })} />
        </label>
        <div className="span2 actions">
          <button className="primary">Save</button>
          {saved && <span className="ok">Saved</span>}
        </div>
        {err && <div className="span2"><ErrorBox message={err} /></div>}
      </form>
    </section>
  );
}

function ReviewPanel({ design, fonts }: { design: Design; fonts: { id: number; name: string }[] }) {
  const [font, setFont] = useState(1);
  const finish = "matte";   // the one finish
  const [nonce, setNonce] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const ready = design.art.wide && design.art.square;
  const url = `/api/designs/${design.id}/review.png?font=${font}&finish=${finish}&n=${nonce}&v=${design.art.wide_version}${design.art.square_version}${design.fill}${design.stroke}${design.cap_frac}${design.char_end}${design.stroke_ratio}`;
  useEffect(() => { if (ready) { setLoading(true); setErr(""); } }, [url, ready]);
  return (
    <section className="card">
      <div className="row-between">
        <h3>Design review sheet</h3>
        <div className="actions">
          <select value={font} onChange={(e) => setFont(Number(e.target.value))}>
            {fonts.map((f) => <option key={f.id} value={f.id}>{f.id} · {f.name}</option>)}
          </select>
          <button onClick={() => setNonce((n) => n + 1)} disabled={!ready}>Refresh</button>
          {ready && <a className="button" href={`/api/designs/${design.id}/review.png?font=${font}&finish=${finish}&download=1`}>Download PNG</a>}
        </div>
      </div>
      {!ready && <p className="muted">Upload both artworks to see the review sheet.</p>}
      {ready && loading && <Spinner label="Rendering every size…" />}
      {err && <ErrorBox message={err} />}
      {ready && (
        <img className="review" src={url} alt="Review sheet" onLoad={() => setLoading(false)}
          onError={async () => {
            setLoading(false);
            try { await api.get(url); } catch (e) { setErr((e as Error).message); }
          }} />
      )}
    </section>
  );
}

function CropSummary({ design }: { design: Design }) {
  const { catalog } = useApp();
  const saved = catalog.sizes.filter((s) => design.presets[s.id]);
  return (
    <section className="card row-between">
      <div>
        <h3>Crop &amp; name position</h3>
        <p className="muted">
          {saved.length === 0 ? "All sizes use the automatic layout." :
            `Saved: ${saved.map((s) => s.label).join(", ")}. ${catalog.sizes.length - saved.length} size(s) automatic.`}
        </p>
      </div>
      <a className="button primary" href={`#/designs/${encodeURIComponent(design.id)}/crop`}>Open crop editor</a>
    </section>
  );
}
