import { useEffect, useMemo, useState } from "react";
import { api, Design, fileUrl, Preview, Run } from "../api";
import { useApp } from "../App";
import { ErrorBox, fmtBytes, Spinner, useAsync, useDebounced, Warnings } from "../ui";

interface GlyphCheck { ok: boolean; message?: string; alternatives?: { id: number; name: string }[] }

const KIND_LABEL: Record<string, string> = {
  zip: "Everything (ZIP)", print: "Print PDF", cut: "Cut file", "page-proof": "Page proof",
  "customer-proof": "Customer proof", notch: "Laminate notches", info: "Info sheet", other: "Other",
};

export default function MakePage() {
  const { catalog } = useApp();
  const designs = useAsync(() => api.get<Design[]>("/api/designs"), []);
  const [form, setForm] = useState({
    order_id: "", design: "", pack: "starter", finish: "matte", font: 1, name: "", line2: "", lang: "en",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const runs = useAsync(() => api.get<Run[]>("/api/runs?limit=10"), [run?.id]);

  const ready = (designs.data ?? []).filter((d) => d.art.wide && d.art.square);
  useEffect(() => {
    if (!form.design && ready.length) setForm((f) => ({ ...f, design: ready[0].id }));
  }, [ready, form.design]);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm({ ...form, [k]: k === "font" ? Number(e.target.value) : e.target.value });

  const pack = catalog.packs.find((p) => p.id === form.pack);
  const sizeLabel = (id: string) => catalog.sizes.find((s) => s.id === id)?.label ?? id;

  // live preview + glyph check (debounce a string key so it only fires when inputs change)
  const liveKey = useDebounced(JSON.stringify({ design: form.design, name: form.name, line2: form.line2, font: form.font, finish: form.finish, pack: form.pack }));
  const [glyph, setGlyph] = useState<GlyphCheck | null>(null);
  const [previews, setPreviews] = useState<{ size: string; p: Preview }[]>([]);
  const [previewErr, setPreviewErr] = useState("");
  useEffect(() => {
    const live = JSON.parse(liveKey);
    setGlyph(null);
    setPreviews([]);
    setPreviewErr("");
    if (!live.name.trim() || !live.design) return;
    const sizes = Object.keys(catalog.packs.find((p) => p.id === live.pack)?.contents ?? {});
    let stale = false;
    api.get<GlyphCheck>(`/api/check-name?name=${encodeURIComponent(live.name)}&line2=${encodeURIComponent(live.line2)}&font=${live.font}`)
      .then(async (g) => {
        if (stale) return;
        setGlyph(g);
        if (!g.ok) return;
        const out: { size: string; p: Preview }[] = [];
        for (const size of sizes) {  // one at a time: the server renders serially anyway
          const p = await api.post<Preview>("/api/preview", { ...live, size, scale: 6 });
          if (stale) return;
          out.push({ size, p });
          setPreviews([...out]);
        }
      })
      .catch((e) => !stale && setPreviewErr(e.message));
    return () => { stale = true; };
  }, [liveKey, catalog.packs]);

  const fontSpec = catalog.fonts.find((f) => f.id === form.font);
  const miniWarn = fontSpec && !fontSpec.mini_ok && pack && "mini" in pack.contents;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    setRun(null);
    try {
      setRun(await api.post<Run>("/api/make", form));
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const designOptions = useMemo(() => designs.data ?? [], [designs.data]);

  return (
    <div className="make">
      <section className="card">
        <h2>Make labels</h2>
        {designs.error && <ErrorBox message={designs.error} />}
        {designs.data && !ready.length && (
          <ErrorBox message="No design has both artworks yet. Upload art in Designs first." />
        )}
        <form onSubmit={submit} className="grid-form">
          <label>Design
            <select value={form.design} onChange={set("design")} required>
              {designOptions.map((d) => (
                <option key={d.id} value={d.id} disabled={!(d.art.wide && d.art.square)}>
                  {d.name}{d.art.wide && d.art.square ? "" : " (no art)"}
                </option>
              ))}
            </select>
          </label>
          <label>Bundle
            <select value={form.pack} onChange={set("pack")}>
              {catalog.packs.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
            {pack && (
              <small className="muted">
                {Object.entries(pack.contents).map(([s, q]) => `${q} × ${sizeLabel(s)}`).join(", ")}
                {" · "}{pack.sheets} sheet{pack.sheets === 1 ? "" : "s"}
              </small>
            )}
          </label>
          <label>Finish
            <select value={form.finish} onChange={set("finish")}>
              {catalog.finishes.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
            </select>
          </label>
          <label>Font
            <select value={form.font} onChange={set("font")}>
              {catalog.fonts.map((f) => <option key={f.id} value={f.id}>{f.id} · {f.name}</option>)}
            </select>
          </label>
          <label>Name
            <input value={form.name} onChange={set("name")} required placeholder="e.g. Émilie-Rose" />
          </label>
          <label>Second line <small className="muted">(optional)</small>
            <input value={form.line2} onChange={set("line2")} placeholder="e.g. Tremblay-Gagnon" />
          </label>
          <label>Order number <small className="muted">(optional)</small>
            <input value={form.order_id} onChange={set("order_id")} placeholder="Etsy order #" />
          </label>
          <label>Proof language
            <select value={form.lang} onChange={set("lang")}>
              <option value="en">English</option>
              <option value="fr">Français</option>
            </select>
          </label>
          <div className="span2">
            {miniWarn && <Warnings items={[`Font ${fontSpec!.id} (${fontSpec!.name}) is hard to read on Mini labels.`]} />}
            {glyph && !glyph.ok && (
              <ErrorBox message={glyph.message ?? "Missing characters."} />
            )}
            {previewErr && <ErrorBox message={previewErr} />}
            {previews.length > 0 && (
              <div className="previews">
                {previews.map(({ size, p }) => (
                  <div className="preview" key={size}>
                    <img src={p.image} alt={`${size} preview`} />
                    <div className={p.cap_mm.some((c) => c < p.min_cap_mm) ? "bad small" : "muted small"}>
                      {sizeLabel(size)} · caps {p.cap_mm.map((c) => c.toFixed(1)).join(" / ")} mm
                    </div>
                  </div>
                ))}
              </div>
            )}
            <Warnings items={[...new Set(previews.flatMap(({ p }) => p.warnings))]} />
          </div>
          <div className="span2 actions">
            <button className="primary" disabled={busy || !form.design || !form.name.trim() || (glyph !== null && !glyph.ok)}>
              Generate files
            </button>
            {busy && <Spinner label="Rendering labels…" />}
          </div>
        </form>
        {err && <ErrorBox message={err} />}
      </section>

      {run && <RunResult run={run} />}

      {runs.data && runs.data.length > 0 && (
        <section className="card">
          <h3>Recent</h3>
          <table className="table">
            <tbody>
              {runs.data.map((r) => {
                const zip = r.files.find((f) => f.kind === "zip");
                return (
                  <tr key={r.id}>
                    <td>{new Date(r.created_at).toLocaleString()}</td>
                    <td>{r.title}</td>
                    <td>{Object.entries(r.summary.finishes).map(([f, s]) => `${s.labels} ${f} on ${s.sheets} sheet${s.sheets === 1 ? "" : "s"}`).join(", ")}</td>
                    <td><button className="link" onClick={() => setRun(r)}>Open</button></td>
                    <td>{zip && <a href={fileUrl(r, zip.name, true)}>ZIP</a>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}

function RunResult({ run }: { run: Run }) {
  const zip = run.files.find((f) => f.kind === "zip");
  const proof = run.files.find((f) => f.kind === "customer-proof");
  const pages = run.files.filter((f) => f.kind === "page-proof");
  const order = ["zip", "print", "cut", "notch", "info", "customer-proof", "page-proof", "other"];
  const files = [...run.files].sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind) || a.name.localeCompare(b.name));
  return (
    <section className="card">
      <div className="row-between">
        <h3>{run.title}</h3>
        {zip && <a className="button primary" href={fileUrl(run, zip.name, true)}>Download everything (ZIP)</a>}
      </div>
      <p className="muted">
        {Object.entries(run.summary.finishes).map(([f, s]) => `${s.labels} labels on ${s.sheets} ${f} sheet${s.sheets === 1 ? "" : "s"}`).join(" · ")}
      </p>
      <Warnings items={run.warnings} />
      <div className="two-col">
        <div>
          <h4>Customer proof</h4>
          {proof && (
            <>
              <a href={fileUrl(run, proof.name)} target="_blank" rel="noreferrer">
                <img className="proof" src={fileUrl(run, proof.name)} alt="Customer proof" />
              </a>
              <a href={fileUrl(run, proof.name, true)}>Download proof PNG</a>
            </>
          )}
        </div>
        <div>
          <h4>Sheets</h4>
          <div className="pages">
            {pages.map((p) => (
              <a key={p.name} href={fileUrl(run, p.name)} target="_blank" rel="noreferrer" title={p.name}>
                <img src={fileUrl(run, p.name)} alt={p.name} />
              </a>
            ))}
          </div>
          <table className="table small">
            <thead><tr><th>Page</th><th>Labels</th><th>X</th><th>Y</th><th>W</th><th>H</th></tr></thead>
            <tbody>
              {run.summary.pages.map((p) => (
                <tr key={p.proof}>
                  <td>{p.finish} {p.n}</td><td>{p.count}</td>
                  <td>{p.x.toFixed(2)}</td><td>{p.y.toFixed(2)}</td><td>{p.w.toFixed(2)}</td><td>{p.h.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <h4>Files</h4>
      <ul className="files">
        {files.map((f) => (
          <li key={f.name}>
            <span className="tag">{KIND_LABEL[f.kind] ?? f.kind}</span>
            <a href={fileUrl(run, f.name, true)}>{f.name}</a>
            <span className="muted"> {fmtBytes(f.size)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
