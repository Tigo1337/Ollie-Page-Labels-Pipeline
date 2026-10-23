import { useEffect, useMemo, useState } from "react";
import { api, Design, fileUrl, pieceNames, Preview, Run, sheetPieces } from "../api";
import { useApp } from "../App";
import { ErrorBox, fmtBytes, Spinner, useAsync, useDebounced, Warnings } from "../ui";

interface GlyphCheck { ok: boolean; message?: string; alternatives?: { id: number; name: string }[] }

const KIND_LABEL: Record<string, string> = {
  zip: "Everything (ZIP)", print: "Print PDF", template: "Cut template", "page-proof": "Page proof",
  "customer-proof": "Customer proof", notch: "Laminate notches", info: "Info sheet", slip: "Packing slip",
  guide: "Packing guide",
  other: "Other",
};
const MINI_SIZES = ["pencil", "tag"];

export default function MakePage() {
  const { catalog } = useApp();
  const designs = useAsync(() => api.get<Design[]>("/api/designs"), []);
  // one finish for every order (matte laminate): shown, not chosen
  const finishId = catalog.finishes[0]?.id ?? "matte";
  const finishLabel = catalog.finishes[0]?.label ?? "Matte laminate";
  const [form, setForm] = useState({
    order_id: "", design: "", pack: "starter", font: 1, name: "", line2: "", lang: "en",
    unpaired: "bonus",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const runs = useAsync(() => api.get<Run[]>("/api/runs?limit=10"), [run?.id]);

  const hasArt = (d: Design) => d.art.wide && d.art.square;
  const ready = useMemo(() => (designs.data ?? []).filter(hasArt), [designs.data]);
  const missingArt = useMemo(() => (designs.data ?? []).filter((d) => !hasArt(d)), [designs.data]);
  useEffect(() => {   // start on a design that can be made (or the first one, to show what is missing)
    const first = ready[0] ?? missingArt[0];
    if (!form.design && first) setForm((f) => ({ ...f, design: first.id }));
  }, [ready, missingArt, form.design]);
  const chosen = (designs.data ?? []).find((d) => d.id === form.design);
  const chosenReady = !!chosen && hasArt(chosen);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm({ ...form, [k]: k === "font" ? Number(e.target.value) : e.target.value });

  const pack = catalog.packs.find((p) => p.id === form.pack);
  const sizeLabel = (id: string) => catalog.sizes.find((s) => s.id === id)?.label ?? id;

  // live preview + glyph check (debounce a string key so it only fires when inputs change)
  const liveKey = useDebounced(JSON.stringify({ design: form.design, name: form.name, line2: form.line2, font: form.font, finish: finishId, pack: form.pack }));
  const [glyph, setGlyph] = useState<GlyphCheck | null>(null);
  const [previews, setPreviews] = useState<{ size: string; p: Preview }[]>([]);
  const [previewErr, setPreviewErr] = useState("");
  useEffect(() => {
    const live = JSON.parse(liveKey);
    setGlyph(null);
    setPreviews([]);
    setPreviewErr("");
    if (!live.name.trim() || !live.design) return;
    const d = (designs.data ?? []).find((x) => x.id === live.design);
    const canRender = !!d && d.art.wide && d.art.square;
    const sizes = Object.keys(catalog.packs.find((p) => p.id === live.pack)?.contents ?? {});
    let stale = false;
    api.get<GlyphCheck>(`/api/check-name?name=${encodeURIComponent(live.name)}&line2=${encodeURIComponent(live.line2)}&font=${live.font}`)
      .then(async (g) => {
        if (stale) return;
        setGlyph(g);
        if (!g.ok || !canRender) return;
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
  }, [liveKey, catalog.packs, designs.data]);

  const fontSpec = catalog.fonts.find((f) => f.id === form.font);
  const miniSizes = pack ? MINI_SIZES.filter((s) => s in pack.contents) : [];
  const miniWarn = fontSpec && !fontSpec.mini_ok && miniSizes.length > 0;
  const piecesText = pack ? Object.entries(pack.pieces_by_size).map(([s, n]) => {
    const size = catalog.sizes.find((x) => x.id === s);
    const per = size ? `${size.per_piece}${size.shape === "pair" ? " pairs" : ""}` : "?";
    return `${n} × ${sizeLabel(s)} third (${per})`;
  }).join(", ") : "";
  const env = pack?.envelope;

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

  return (
    <div className="make">
      <section className="card">
        <h2>Make labels</h2>
        {designs.error && <ErrorBox message={designs.error} />}
        {designs.data && !ready.length && (
          <ErrorBox message="No design has its artwork yet. Upload the wide and square images in Designs (one at a time, or a ZIP of the Label Designs folder) to make labels." />
        )}
        <form onSubmit={submit} className="grid-form">
          <label>Design
            <select value={form.design} onChange={set("design")} required>
              {ready.length > 0 && (
                <optgroup label={`Ready (${ready.length})`}>
                  {ready.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </optgroup>
              )}
              {missingArt.length > 0 && (
                <optgroup label={`Artwork missing (${missingArt.length})`}>
                  {missingArt.map((d) => <option key={d.id} value={d.id}>{d.name} (no art yet)</option>)}
                </optgroup>
              )}
            </select>
            {chosen && !chosenReady && (
              <small className="bad">
                {chosen.name} has no {!chosen.art.wide && !chosen.art.square ? "wide or square" : !chosen.art.wide ? "wide" : "square"} artwork
                yet: <a href={`#/designs/${encodeURIComponent(chosen.id)}`}>upload it</a> to make labels.
              </small>
            )}
          </label>
          <label>Bundle
            <select value={form.pack} onChange={set("pack")}>
              {catalog.packs.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
            {pack && (
              <small className="muted">
                {pack.error ? <span className="bad">{pack.error}</span> : <>
                  {piecesText} · {pack.alone} sheet{pack.alone === 1 ? "" : "s"} on its own
                  ({pack.batched} of material when batched) · <a href="#/templates">cut templates</a>
                  {env && <><br />#10 envelope ≈ {env.weight_g} g ({pack.pieces} pieces): {env.lettermail}
                    {env.warning && <span className="bad"> · {env.warning}</span>}</>}
                </>}
              </small>
            )}
          </label>
          <div>Finish
            <p className="muted">{finishLabel}</p>
          </div>
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
          <label>Sheet not full
            <select value={form.unpaired} onChange={set("unpaired")}>
              <option value="bonus">Fill the empty thirds with free bonus copies</option>
              <option value="blank">Leave the empty thirds blank</option>
            </select>
            <small className="muted">A sheet holds three thirds of the same size; a size with 1 or 2 thirds in this order is printed now.</small>
          </label>
          <label>Proof language
            <select value={form.lang} onChange={set("lang")}>
              <option value="en">English</option>
              <option value="fr">Français</option>
            </select>
          </label>
          <div className="span2">
            {miniWarn && <Warnings items={[`Font ${fontSpec!.id} (${fontSpec!.name}) is hard to read on ${miniSizes.map(sizeLabel).join(" and ")} labels.`]} />}
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
            <button className="primary" disabled={busy || !chosenReady || !form.name.trim() || (glyph !== null && !glyph.ok)}>
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

export function RunResult({ run }: { run: Run }) {
  const zip = run.files.find((f) => f.kind === "zip");
  const proof = run.files.find((f) => f.kind === "customer-proof");
  const pages = run.files.filter((f) => f.kind === "page-proof");
  const order = ["zip", "print", "template", "notch", "info", "guide", "slip", "customer-proof", "page-proof", "other"];
  const files = [...run.files].sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind) || a.name.localeCompare(b.name));
  const nPieces = Math.max(2, ...(run.summary.sheets ?? []).map((sh) => sheetPieces(sh).length));
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
            <thead><tr><th>Sheet</th><th>Template</th>{pieceNames(nPieces).map((n) => <th key={n}>{n}</th>)}</tr></thead>
            <tbody>
              {(run.summary.sheets ?? []).map((sh) => (
                <tr key={sh.n}>
                  <td>{sh.n} · {sh.finish}</td><td><code>{sh.layout_id}</code></td>
                  {sheetPieces(sh).map((p, i) => (
                    <td key={i}>{p ? <>{p.tag}{p.bonus && <strong> · bonus</strong>}</> : <span className="muted">blank</span>}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {(run.summary.envelopes ?? []).length > 0 && (
            <>
              <h4>Envelopes</h4>
              <table className="table small">
                <thead><tr><th>Order</th><th>Pieces</th><th>Weight</th><th>Postage</th><th>Bonus copies</th></tr></thead>
                <tbody>
                  {run.summary.envelopes!.map((e) => (
                    <tr key={e.order}>
                      <td>#{e.order}{e.customer ? ` · ${e.customer}` : ""}</td>
                      <td>{e.pieces}</td>
                      <td>≈ {e.weight_g} g · {e.thickness_mm} mm</td>
                      <td className={e.kind === "standard" ? "" : "bad"}>{e.lettermail}</td>
                      <td>{e.bonus === 0 ? "—" : e.bonus_in_envelope ? `${e.bonus}, in the envelope` : `${e.bonus}, keep aside (would raise the postage)`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {(run.summary.look_alikes ?? []).filter((a) => !a.identical).length > 0 && (
            <Warnings items={run.summary.look_alikes!.filter((a) => !a.identical).map((a) =>
              `${a.size_label} "${a.name}": orders ${a.orders.map((o) => "#" + o).join(", ")} have look-alike pieces — see the packing guide.`)} />
          )}
          {(run.summary.waiting ?? []).length > 0 && (
            <Warnings items={(run.summary.waiting ?? []).map((h) => `Waiting for more thirds to fill a sheet: ${h.tag}`)} />
          )}
          <p className="muted small">Cut every sheet with its layout's template (<a href="#/templates">Templates</a>); no X / Y to type.</p>
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
