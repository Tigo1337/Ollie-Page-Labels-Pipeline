import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import { ErrorBox, Progress, Warnings } from "../ui";

interface Group { id: string; code: string; name: string; designs: string[]; tags: string[] }
interface Cfg {
  shop_name: string; ship_time: string; sku_prefix: string; asset_prefix: string; asset_base_url: string; sample_names: string[];
  pack_short: Record<string, string>; pack_code: Record<string, string>; prices: Record<string, string>;
  csv: Record<string, string>; variation_names: Record<string, string>;
  personalization: { columns: boolean; required: boolean; char_count_max: number; instructions: string };
  title_template: string; tags_base: string[]; description_template: string; groups: Group[];
}
interface Img { file: string; variant: string; generated_at?: string; uploaded_at?: string; url?: string }
interface Job {
  id: string; status: "running" | "done" | "error"; mode: "render" | "upload"; done: number; total: number;
  current: string; errors: string[]; uploaded: number; purged: boolean | null;
}
interface Status {
  cfg: Cfg; problems: string[]; image_notes: string[]; groups: { id: string; title: string; images: Img[] }[];
  unassigned: string[]; designs: Record<string, string>; asset_base: string;
  r2: { configured: boolean; public_base: string | null; cdn_purge: boolean }; job: Job | null;
  item?: { item_weight: string; item_length: string; item_width: string; item_height: string; basis: string | null;
           postage: string | null };
}

const SHOP_FIELDS: [string, string, string][] = [
  ["shipping_profile_id", "Shipping profile ID", "Etsy → Settings → Shipping settings (number in the profile's URL)"],
  ["return_policy_id", "Return policy ID", ""],
  ["readiness_state_id", "Processing profile ID", "readiness_state_id in the CSV"],
  ["shop_section_id", "Shop section ID", "optional"],
  ["taxonomy_id", "Taxonomy ID", "Etsy category number (optional if the connector maps the category)"],
  ["category", "Category", ""],
  ["quantity", "Quantity in stock", "per bundle"],
  ["materials", "Materials", "comma separated"],
];

const slug = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
const imgUrl = (f: string, w = 0, v = "") => `/api/listings/images/${encodeURIComponent(f)}${w ? `?w=${w}&v=${encodeURIComponent(v)}` : ""}`;

export default function ListingsPage() {
  const { catalog } = useApp();
  const [st, setSt] = useState<Status | null>(null);
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [dirty, setDirty] = useState(false);
  const [err, setErr] = useState("");
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    const s = await api.get<Status>("/api/listings");
    setSt(s);
    return s;
  }, []);
  useEffect(() => {
    load().then((s) => setCfg(s.cfg)).catch((e) => setErr(e.message));
  }, [load]);

  // poll while images are being made
  const running = st?.job?.status === "running";
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      api.get<Job>("/api/listings/job").then((job) => {
        setSt((s) => (s ? { ...s, job } : s));
        if (job.status !== "running") load().catch(() => undefined);
      }).catch(() => undefined);
    }, 1000);
    return () => clearInterval(t);
  }, [running, load]);

  if (!st || !cfg) return err ? <ErrorBox message={err} /> : <p className="muted">Loading…</p>;

  const edit = (patch: Partial<Cfg>) => { setCfg({ ...cfg, ...patch }); setDirty(true); setSaved(false); };
  const editGroup = (i: number, patch: Partial<Group>) =>
    edit({ groups: cfg.groups.map((g, j) => (j === i ? { ...g, ...patch } : g)) });
  const moveDesign = (d: string, to: string) =>
    edit({ groups: cfg.groups.map((g) => ({ ...g, designs: g.id === to ? [...g.designs.filter((x) => x !== d), d] : g.designs.filter((x) => x !== d) })) });
  const addGroup = () => {
    const name = prompt("Name of the new listing (it goes in the title, e.g. \"Unicorn & Rainbow\"):");
    if (!name) return;
    const id = slug(name) || `listing-${cfg.groups.length + 1}`;
    const code = name.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 4) || `G${cfg.groups.length + 1}`;
    edit({ groups: [...cfg.groups, { id, code, name, designs: [], tags: [] }] });
  };

  const save = async () => {
    setErr("");
    try {
      const s = await api.put<Status>("/api/listings", cfg);
      setSt(s);
      setCfg(s.cfg);
      setDirty(false);
      setSaved(true);
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const startImages = async (groups: string[] | null, upload_only = false) => {
    setErr("");
    if (dirty) return setErr("Save your changes first: the images use the saved listings.");
    try {
      const job = await api.post<Job>("/api/listings/images", { groups, upload_only });
      setSt({ ...st, job });
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const job = st.job;
  const imagesOf = (id: string) => st.groups.find((g) => g.id === id)?.images ?? [];
  const csvReady = !dirty && st.problems.length === 0;
  const designName = (d: string) => st.designs[d] ?? d;

  return (
    <div>
      <div className="row-between">
        <h2>Etsy listings</h2>
        <div className="actions">
          {dirty && <button className="primary" onClick={save}>Save changes</button>}
          {saved && !dirty && <span className="ok">Saved</span>}
        </div>
      </div>
      <p className="muted">
        One Etsy listing per group of designs. Buyers choose the <b>bundle</b> and the <b>design</b> (the two
        variations) and type the name and the font number in the personalization box.
      </p>
      {err && <ErrorBox message={err} />}

      <section className="card">
        <h3>1 · Export</h3>
        {st.problems.length > 0
          ? <><p>Fix these before downloading the CSV:</p><Warnings items={st.problems} /></>
          : <div className="okbox">The listings are ready for the CSV.</div>}
        {st.image_notes.length > 0 && <Warnings items={st.image_notes} />}
        <p className="muted small">
          {st.r2.configured
            ? <>Images are uploaded to Cloudflare R2 as they are made: {st.r2.public_base}{st.r2.cdn_purge ? " (the CDN cache is purged after each run)." : "."}</>
            : <>R2 is not set up, so the images stay here: add the R2_* secrets in Replit and restart the app, or
              download the ZIP and host the images yourself (fill in "Where the images are hosted" below).</>}
          {st.asset_base ? <>{" "}The CSV's image links start with {st.asset_base}/.</> : null}
        </p>
        <div className="actions">
          <button className="primary" disabled={running} onClick={() => startImages(null)}>Make all listing images</button>
          {st.r2.configured && <button disabled={running} onClick={() => startImages(null, true)}>Upload the images to R2 again</button>}
          <a className="button" href="/api/listings/images.zip">Download images (ZIP)</a>
          {csvReady
            ? <a className="button" href="/api/listings/csv">Download the Etsy CSV</a>
            : <button disabled title={dirty ? "Save your changes first" : "Fix the problems above first"}>Download the Etsy CSV</button>}
        </div>
        {job && job.status === "running" && (
          <Progress value={job.total ? job.done / job.total : 0}
            label={`${job.mode === "upload" ? "Uploading" : "Making"} image ${Math.min(job.done + 1, job.total)} of ${job.total}: ${job.current}`} />
        )}
        {job && job.status !== "running" && (
          <p className="small">
            Last run: {job.done - job.errors.length} of {job.total} images {job.mode === "upload" ? "uploaded" : "made"}
            {job.uploaded > 0 && job.mode === "render" ? `, ${job.uploaded} uploaded to R2` : ""}
            {job.purged === false ? " (the CDN purge failed: old images may show for a few minutes)" : ""}.
          </p>
        )}
        {job && job.errors.length > 0 && <Warnings items={job.errors} />}
      </section>

      <section className="card">
        <h3>2 · Bundles (variation 1: {cfg.variation_names.bundle})</h3>
        <table className="table small">
          <thead><tr><th>Bundle</th><th>Contents</th><th>Option name on Etsy</th><th>SKU code</th><th>Price</th></tr></thead>
          <tbody>
            {catalog.packs.map((p) => (
              <tr key={p.id}>
                <td>{p.label}</td>
                <td className="muted">{p.total} labels</td>
                <td><input value={cfg.pack_short[p.id] ?? ""} maxLength={20}
                  onChange={(e) => edit({ pack_short: { ...cfg.pack_short, [p.id]: e.target.value } })} /></td>
                <td><input value={cfg.pack_code[p.id] ?? ""} maxLength={8}
                  onChange={(e) => edit({ pack_code: { ...cfg.pack_code, [p.id]: e.target.value.toUpperCase() } })} /></td>
                <td><input value={cfg.prices[p.id] ?? ""} placeholder="12.50" inputMode="decimal"
                  onChange={(e) => edit({ prices: { ...cfg.prices, [p.id]: e.target.value } })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted small">The listing price is the cheapest bundle; each bundle has its own price and SKU
          ({cfg.sku_prefix}-CODE-BUNDLE).</p>
      </section>

      <section className="card">
        <h3>3 · Shop fields (same for every listing)</h3>
        <div className="grid-form">
          <label className="span2">Shop name<small className="muted">used in the description ({"{shop_name}"})</small>
            <input value={cfg.shop_name} onChange={(e) => edit({ shop_name: e.target.value })} />
          </label>
          <label className="span2">Shipping time<small className="muted">on the How-to-order image: "Your labels ship flat in an envelope within …"</small>
            <input value={cfg.ship_time ?? ""} placeholder="3-5 business days" onChange={(e) => edit({ ship_time: e.target.value })} />
          </label>
          {SHOP_FIELDS.map(([k, label, hint]) => (
            <label key={k}>{label}{hint && <small className="muted">{hint}</small>}
              <input value={cfg.csv[k] ?? ""} onChange={(e) => edit({ csv: { ...cfg.csv, [k]: e.target.value } })} />
            </label>
          ))}
          {st.item && (
            <p className="span2 muted small">
              Item size and weight in the CSV (computed): {st.item.item_length} × {st.item.item_width} × {st.item.item_height} cm,
              {" "}{st.item.item_weight} kg: a #10 envelope with the heaviest bundle
              {st.item.basis ? ` (${catalog.packs.find((p) => p.id === st.item!.basis)?.label ?? st.item.basis}${st.item.postage ? `, ${st.item.postage.toLowerCase()}` : ""})` : ""}.
              Etsy takes one weight per listing; it follows the piece and envelope weights in Settings.
            </p>
          )}
          {!st.r2.configured && (
            <label className="span2">Where the images are hosted<small className="muted">used when R2 is not set up, e.g. https://images.yourshop.com</small>
              <input value={cfg.asset_base_url} placeholder="https://" onChange={(e) => edit({ asset_base_url: e.target.value })} />
            </label>
          )}
          <label className="inline span2">
            <input type="checkbox" checked={cfg.personalization.columns}
              onChange={(e) => edit({ personalization: { ...cfg.personalization, columns: e.target.checked } })} />
            Add the personalization columns to the CSV (turn off if the Etsy Connector refuses them)
          </label>
          <label className="span2">Personalization instructions (shown to the buyer)
            <textarea rows={3} value={cfg.personalization.instructions}
              onChange={(e) => edit({ personalization: { ...cfg.personalization, instructions: e.target.value } })} />
          </label>
        </div>
        <details>
          <summary>Title, description and base tags</summary>
          <div className="grid-form" style={{ marginTop: 12 }}>
            <label className="span2">Title<small className="muted">{"{group_name}"} is the listing's name; at most 140 characters once filled in</small>
              <input value={cfg.title_template} onChange={(e) => edit({ title_template: e.target.value })} />
            </label>
            <label className="span2">Description
              <small className="muted">{"{shop_name} {group_name} {designs} {design_count} {bundles} {sizes} {fonts} {font_count} {sku}"}</small>
              <textarea rows={18} value={cfg.description_template} onChange={(e) => edit({ description_template: e.target.value })} />
            </label>
            <label className="span2">Tags for every listing<small className="muted">comma separated; each listing's own tags come first, 13 in total</small>
              <input value={cfg.tags_base.join(", ")}
                onChange={(e) => edit({ tags_base: e.target.value.split(",").map((t) => t.trimStart()) })} />
            </label>
          </div>
        </details>
      </section>

      <section className="card">
        <div className="row-between">
          <h3>4 · Listings (variation 2: {cfg.variation_names.design})</h3>
          <button onClick={addGroup}>New listing</button>
        </div>
        {cfg.groups.map((g, i) => {
          const imgs = imagesOf(g.id);
          const title = cfg.title_template.split("{group_name}").join(g.name);
          return (
            <div key={i} className="listing">
              <div className="listing-head">
                <label>Name<input value={g.name} onChange={(e) => editGroup(i, { name: e.target.value })} /></label>
                <label className="code">SKU code<input value={g.code} maxLength={8}
                  onChange={(e) => editGroup(i, { code: e.target.value.toUpperCase() })} /></label>
                <div className="actions">
                  <button disabled={running || dirty} onClick={() => startImages([g.id])}>Make images</button>
                  {g.designs.length === 0 && (
                    <button onClick={() => edit({ groups: cfg.groups.filter((_, j) => j !== i) })}>Remove</button>
                  )}
                </div>
              </div>
              <p className={`small ${title.length > 140 ? "bad" : "muted"}`}>{title} ({title.length}/140)</p>
              <label>Tags for this listing<small className="muted">{g.tags.filter(Boolean).length} of 13, then the shop's tags</small>
                <input value={g.tags.join(", ")}
                  onChange={(e) => editGroup(i, { tags: e.target.value.split(",").map((t) => t.trimStart()) })} />
              </label>
              <div className="chips">
                {g.designs.map((d, n) => (
                  <span key={d} className="chip">
                    <b>{n + 1}.</b> {designName(d)}
                    <select value="" title="Move to another listing" onChange={(e) => e.target.value && moveDesign(d, e.target.value)}>
                      <option value="">Move…</option>
                      {cfg.groups.filter((o) => o.id !== g.id).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                    </select>
                  </span>
                ))}
              </div>
              {imgs.some((x) => x.generated_at) && (
                <div className="thumbs">
                  {imgs.map((x) => x.generated_at
                    ? <a key={x.file} href={imgUrl(x.file)} target="_blank" rel="noreferrer" title={`${x.variant}${x.url ? " · on R2" : ""}`}>
                        <img src={imgUrl(x.file, 240, x.generated_at)} alt={x.variant} loading="lazy" />
                      </a>
                    : <span key={x.file} className="thumb-missing">{x.variant.replace("_", " ")}</span>)}
                </div>
              )}
            </div>
          );
        })}
        {st.unassigned.length > 0 && (
          <div className="listing">
            <h4>Designs in no listing</h4>
            <div className="chips">
              {st.unassigned.filter((d) => !cfg.groups.some((g) => g.designs.includes(d))).map((d) => (
                <span key={d} className="chip">
                  {designName(d)}
                  <select value="" onChange={(e) => e.target.value && moveDesign(d, e.target.value)}>
                    <option value="">Add to…</option>
                    {cfg.groups.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                  </select>
                </span>
              ))}
            </div>
          </div>
        )}
        {dirty && <div className="actions"><button className="primary" onClick={save}>Save changes</button></div>}
      </section>
    </div>
  );
}
