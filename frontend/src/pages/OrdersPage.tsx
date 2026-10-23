import { useCallback, useEffect, useMemo, useState } from "react";
import { api, Design, Run } from "../api";
import { useApp } from "../App";
import { ErrorBox, Spinner, useAsync, useDebounced, Warnings } from "../ui";
import { RunResult } from "./MakePage";

interface OrderLine {
  design: string; pack: string; name: string; line2: string; font: number; finish: string;
  personalization: string; sku: string; review: string[]; problems?: string[];
  checked?: boolean;   // editor only: the notes were looked at, cleared on save
}
interface Order {
  id: string; created_at: string | null; order_date: string; customer: string; lang: string;
  status: "new" | "made" | "shipped" | "cancelled"; lines: OrderLine[]; source: string; runs: string[];
  notes: string; ready: boolean;
}
interface Job { id: string; status: "running" | "done" | "error"; orders: string[]; run: Run | null; error: string | null }
interface ImportReport { rows: number; added: string[]; already_imported: string[]; skipped: string[]; to_check: number }
interface Envelope { order: string; pieces: number; bonus: number; bonus_in_envelope: boolean; weight_g: number; lettermail: string; kind: string }
interface Plan {
  orders: string[]; sheets: number; sheets_alone: number; sheets_by_size: Record<string, number>; bonus: number;
  blank: number; envelopes: Envelope[];
}

const TABS: [Order["status"] | "all", string][] = [
  ["new", "To make"], ["made", "Made"], ["shipped", "Shipped"], ["cancelled", "Cancelled"], ["all", "All"],
];
const EMPTY_LINE: OrderLine = { design: "", pack: "starter", name: "", line2: "", font: 1, finish: "matte", personalization: "", sku: "", review: [] };

export default function OrdersPage() {
  const { catalog } = useApp();
  const [tab, setTab] = useState<Order["status"] | "all">("new");
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [importing, setImporting] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [unpaired, setUnpaired] = useState<"bonus" | "blank">("bonus");
  const designs = useAsync(() => api.get<Design[]>("/api/designs"), []);

  const reload = useCallback(() => {
    api.get<{ orders: Order[]; job: Job | null }>("/api/orders").then((r) => {
      setOrders(r.orders);
      setJob((j) => j ?? (r.job && r.job.status === "running" ? r.job : null));
    }).catch((e) => setErr(e.message));
  }, []);
  useEffect(reload, [reload]);

  // follow a running batch
  useEffect(() => {
    if (!job || job.status !== "running") return;
    const t = setTimeout(() => {
      api.get<Job>(`/api/orders/batch/${job.id}`).then((j) => {
        setJob(j);
        if (j.status === "done") {
          setRun(j.run);
          setSelected([]);
          setMsg(`Made ${j.orders.length} order${j.orders.length === 1 ? "" : "s"}: the files are below.`);
          reload();
        } else if (j.status === "error") {
          setErr(j.error ?? "The batch failed.");
        }
      }).catch((e) => setErr(e.message));
    }, 1000);
    return () => clearTimeout(t);
  }, [job, reload]);

  const shown = useMemo(() => (orders ?? []).filter((o) => tab === "all" || o.status === tab), [orders, tab]);
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: (orders ?? []).length };
    for (const o of orders ?? []) c[o.status] = (c[o.status] ?? 0) + 1;
    return c;
  }, [orders]);
  const designName = (id: string) => (designs.data ?? []).find((d) => d.id === id)?.name ?? (id || "?");
  const packLabel = (id: string) => catalog.packs.find((p) => p.id === id)?.label ?? id;
  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const selectable = shown.filter((o) => o.status !== "cancelled");
  const allSelected = selectable.length > 0 && selectable.every((o) => selected.includes(o.id));

  const importCsv = async (f: File) => {
    setErr(""); setMsg(""); setReport(null); setImporting(true);
    const fd = new FormData();
    fd.append("file", f);
    try {
      setReport(await api.post<ImportReport>("/api/orders/import", fd));
      setTab("new");
      reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setImporting(false);
    }
  };

  const setStatus = async (status: Order["status"]) => {
    setErr(""); setMsg("");
    try {
      const r = await api.post<{ changed: number }>("/api/orders/status", { orders: selected, status });
      setMsg(`${r.changed} order${r.changed === 1 ? "" : "s"} marked ${status}.`);
      setSelected([]);
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete ${selected.length} order(s)? Their production files stay in the runs.`)) return;
    setErr("");
    try {
      for (const id of selected) await api.del(`/api/orders/${encodeURIComponent(id)}`);
      setSelected([]);
      reload();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const openRun = async (id: string) => {
    setErr("");
    try {
      setRun(await api.get<Run>(`/api/runs/${encodeURIComponent(id)}`));
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const selectedOrders = (orders ?? []).filter((o) => selected.includes(o.id));
  const canMake = selectedOrders.length > 0 && selectedOrders.every((o) => o.ready && o.status !== "cancelled");
  const making = job?.status === "running";

  return (
    <div>
      <section className="card">
        <div className="row-between">
          <h2>Orders</h2>
          <div className="actions">
            <label className="button">
              {importing ? "Importing…" : "Import Etsy orders (CSV)"}
              <input type="file" accept=".csv,text/csv" hidden disabled={importing}
                onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) importCsv(f); }} />
            </label>
            <button onClick={() => { setAdding(true); setEditing(null); }}>Add an order</button>
          </div>
        </div>
        <p className="muted small">
          Import Etsy's <strong>Sold Order Items</strong> file (Shop Manager → Settings → Options → Download Data → Orders,
          type "Order Items"). Orders already imported are never added twice. Select several orders and make them
          together: pieces of different orders share sheets, so a batch prints fewer sheets and fewer free bonus copies.
        </p>
        {report && (
          <div className="okbox">
            {report.added.length} order{report.added.length === 1 ? "" : "s"} added
            {report.to_check > 0 && <> · <strong>{report.to_check} to check</strong> (see the notes on their lines)</>}
            {report.already_imported.length > 0 && <> · {report.already_imported.length} already imported</>}
            {report.skipped.length > 0 && <> · {report.skipped.length} row{report.skipped.length === 1 ? "" : "s"} skipped (not labels)</>}
          </div>
        )}
        {report && report.skipped.length > 0 && <Warnings items={report.skipped} />}
        {making && selected.length === 0 && <p><Spinner label="A batch is being made…" /></p>}
        {msg && <div className="okbox">{msg}</div>}
        {err && <ErrorBox message={err} />}
        {adding && (
          <OrderEditor order={null} designs={designs.data ?? []}
            onDone={(o) => { setAdding(false); if (o) { setMsg(`Order ${o.id} added.`); reload(); } }} />
        )}
      </section>

      {selected.length > 0 && (
        <BatchBar selected={selectedOrders} canMake={canMake} making={making} unpaired={unpaired}
          setUnpaired={setUnpaired}
          onMake={async () => {
            setErr(""); setMsg(""); setRun(null);
            try {
              setJob(await api.post<Job>("/api/orders/batch", { orders: selected, unpaired }));
            } catch (e) {
              setErr((e as Error).message);
            }
          }}
          onStatus={setStatus} onDelete={remove} onClear={() => setSelected([])} />
      )}

      <section className="card">
        <div className="tabs">
          {TABS.map(([id, label]) => (
            <button key={id} className={tab === id ? "tab active" : "tab"} onClick={() => { setTab(id); setSelected([]); }}>
              {label} <span className="muted small">({counts[id] ?? 0})</span>
            </button>
          ))}
        </div>
        {!orders ? <Spinner label="Loading orders…" /> : shown.length === 0 ? (
          <p className="muted">{tab === "new" ? "No orders to make. Import Etsy's order file or add an order." : "No orders here."}</p>
        ) : (
          <table className="table orders">
            <thead>
              <tr>
                <th><input type="checkbox" aria-label="Select all" checked={allSelected}
                  onChange={() => setSelected(allSelected ? [] : selectable.map((o) => o.id))} /></th>
                <th>Order</th><th>Customer</th><th>Labels</th><th>State</th><th></th>
              </tr>
            </thead>
            <tbody>
              {shown.map((o) => (
                <OrderRowView key={o.id} o={o} checked={selected.includes(o.id)} toggle={() => toggle(o.id)}
                  designName={designName} packLabel={packLabel} editing={editing === o.id}
                  onEdit={() => { setEditing(editing === o.id ? null : o.id); setAdding(false); }}
                  onSaved={() => { setEditing(null); reload(); }} openRun={openRun} designs={designs.data ?? []} />
              ))}
            </tbody>
          </table>
        )}
      </section>

      {run && <RunResult run={run} />}
    </div>
  );
}

function OrderRowView(props: {
  o: Order; checked: boolean; toggle: () => void; designName: (id: string) => string; packLabel: (id: string) => string;
  editing: boolean; onEdit: () => void; onSaved: () => void; openRun: (id: string) => void; designs: Design[];
}) {
  const { o } = props;
  const problems = o.lines.flatMap((l) => l.problems ?? []);
  const toCheck = o.lines.some((l) => l.review.length > 0);
  const state = o.status !== "new" ? o.status
    : problems.length ? "cannot be made" : toCheck ? "to check" : "ready";
  return (
    <>
      <tr className={props.checked ? "selected" : ""}>
        <td>{o.status !== "cancelled" && <input type="checkbox" checked={props.checked} onChange={props.toggle} aria-label={`Select ${o.id}`} />}</td>
        <td>
          <strong>#{o.id}</strong>
          <div className="muted small">{o.order_date || (o.created_at ? new Date(o.created_at).toLocaleDateString() : "")}
            {o.source === "manual" ? " · added by hand" : ""}</div>
        </td>
        <td>{o.customer || <span className="muted">—</span>} {o.lang === "fr" && <span className="pill lang">FR</span>}</td>
        <td>
          {o.lines.map((l, i) => (
            <div key={i} className={(l.problems ?? []).length ? "bad small" : l.review.length ? "warn-text small" : "small"}>
              {props.packLabel(l.pack)} · {props.designName(l.design)} · <strong>{l.name || "(no name)"}</strong>
              {l.line2 ? ` / ${l.line2}` : ""} · font {l.font}
            </div>
          ))}
        </td>
        <td>
          <span className={`pill state-${state.replace(/ /g, "-")}`}>{state}</span>
          {o.runs.length > 0 && (
            <div className="small">
              {o.runs.map((r, i) => (
                <button key={r} className="link" onClick={() => props.openRun(r)}>{i === o.runs.length - 1 ? "files" : `earlier files ${i + 1}`}</button>
              ))}
            </div>
          )}
        </td>
        <td><button onClick={props.onEdit}>{props.editing ? "Close" : toCheck || problems.length ? "Check" : "Edit"}</button></td>
      </tr>
      {props.editing && (
        <tr className="editor-row">
          <td colSpan={6}>
            <OrderEditor order={o} designs={props.designs} onDone={(saved) => saved ? props.onSaved() : props.onEdit()} />
          </td>
        </tr>
      )}
    </>
  );
}

function OrderEditor({ order, designs, onDone }: { order: Order | null; designs: Design[]; onDone: (o: Order | null) => void }) {
  const { catalog } = useApp();
  const [id, setId] = useState("");
  const [customer, setCustomer] = useState(order?.customer ?? "");
  const [lang, setLang] = useState(order?.lang ?? "en");
  const [notes, setNotes] = useState(order?.notes ?? "");
  const [lines, setLines] = useState<OrderLine[]>(order ? order.lines.map((l) => ({ ...l })) : [{ ...EMPTY_LINE }]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // editing a line counts as checking it: its notes go away when the order is saved
  const edit = (i: number, patch: Partial<OrderLine>) =>
    setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch, checked: true } : l)));
  const save = async () => {
    setBusy(true); setErr("");
    try {
      const body = {
        customer, lang, notes,
        lines: lines.map(({ problems: _p, checked, ...l }) => (checked ? { ...l, review: [] } : l)),
      };
      const saved = order
        ? await api.patch<Order>(`/api/orders/${encodeURIComponent(order.id)}`, body)
        : await api.post<Order>("/api/orders", { ...body, id: id.trim() });
      onDone(saved);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const ready = designs.filter((d) => d.art.wide && d.art.square);
  return (
    <div className="order-editor">
      <div className="grid-form">
        {!order && (
          <label>Order number <small className="muted">(empty = a number is made up)</small>
            <input value={id} onChange={(e) => setId(e.target.value)} placeholder="Etsy order #" />
          </label>
        )}
        <label>Customer<input value={customer} onChange={(e) => setCustomer(e.target.value)} /></label>
        <label>Proof language
          <select value={lang} onChange={(e) => setLang(e.target.value)}>
            <option value="en">English</option><option value="fr">Français</option>
          </select>
        </label>
        <label className="span2">Notes<input value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
      </div>
      {lines.map((l, i) => (
        <div key={i} className="order-line">
          <div className="grid-form line-fields">
            <label>Design
              <select value={l.design} onChange={(e) => edit(i, { design: e.target.value })}>
                <option value="">— choose —</option>
                {ready.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                {designs.filter((d) => !(d.art.wide && d.art.square)).map((d) => <option key={d.id} value={d.id}>{d.name} (no art yet)</option>)}
              </select>
            </label>
            <label>Bundle
              <select value={l.pack} onChange={(e) => edit(i, { pack: e.target.value })}>
                {catalog.packs.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
              </select>
            </label>
            <label>Name<input value={l.name} onChange={(e) => edit(i, { name: e.target.value })} /></label>
            <label>Second line<input value={l.line2} onChange={(e) => edit(i, { line2: e.target.value })} /></label>
            <label>Font
              <select value={l.font} onChange={(e) => edit(i, { font: Number(e.target.value) })}>
                {catalog.fonts.map((f) => <option key={f.id} value={f.id}>{f.id} · {f.name}</option>)}
              </select>
            </label>
            <div className="actions line-actions">
              {l.review.length > 0 && !l.checked && (
                <button onClick={() => setLines((ls) => ls.map((x, j) => (j === i ? { ...x, checked: true } : x)))}>Looks right</button>
              )}
              {lines.length > 1 && <button onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>Remove line</button>}
            </div>
          </div>
          {l.personalization && <p className="muted small">The buyer wrote: “{l.personalization}”{l.sku ? ` · SKU ${l.sku}` : ""}</p>}
          {l.review.length > 0 && !l.checked && <Warnings items={l.review.map((r) => `To check: ${r}`)} />}
          {l.review.length > 0 && l.checked && <p className="ok small">Checked: the notes go away when you save.</p>}
          {(l.problems ?? []).length > 0 && <ErrorBox message={(l.problems ?? []).join(" ")} />}
        </div>
      ))}
      <div className="actions">
        <button onClick={() => setLines((ls) => [...ls, { ...EMPTY_LINE }])}>Add a line</button>
        <button className="primary" disabled={busy} onClick={save}>{order ? "Save" : "Add the order"}</button>
        <button onClick={() => onDone(null)}>Cancel</button>
        {busy && <Spinner label="Saving…" />}
      </div>
      {err && <ErrorBox message={err} />}
    </div>
  );
}

function BatchBar(props: {
  selected: Order[]; canMake: boolean; making: boolean; unpaired: "bonus" | "blank"; setUnpaired: (u: "bonus" | "blank") => void;
  onMake: () => void; onStatus: (s: Order["status"]) => void; onDelete: () => void; onClear: () => void;
}) {
  const { selected, canMake } = props;
  const key = useDebounced(JSON.stringify({ ids: selected.map((o) => o.id), unpaired: props.unpaired, canMake }), 250);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planErr, setPlanErr] = useState("");
  useEffect(() => {
    const k = JSON.parse(key);
    setPlan(null); setPlanErr("");
    if (!k.canMake || !k.ids.length) return;
    let stale = false;
    api.post<Plan>("/api/orders/plan", { orders: k.ids, unpaired: k.unpaired })
      .then((p) => !stale && setPlan(p)).catch((e) => !stale && setPlanErr(e.message));
    return () => { stale = true; };
  }, [key]);
  const notReady = selected.filter((o) => !o.ready || o.status === "cancelled");
  return (
    <section className="card batch-bar">
      <div className="row-between">
        <strong>{selected.length} order{selected.length === 1 ? "" : "s"} selected</strong>
        <div className="actions">
          <button onClick={() => props.onStatus("shipped")}>Mark shipped</button>
          <button onClick={() => props.onStatus("made")}>Mark made</button>
          <button onClick={() => props.onStatus("new")}>Back to “to make”</button>
          <button onClick={() => props.onStatus("cancelled")}>Cancel</button>
          <button onClick={props.onDelete}>Delete</button>
          <button className="link" onClick={props.onClear}>Clear</button>
        </div>
      </div>
      {notReady.length > 0 && (
        <Warnings items={[`Not ready to make: ${notReady.map((o) => "#" + o.id).join(", ")} (check their lines first).`]} />
      )}
      {plan && (
        <p>
          <strong>{plan.sheets} sheet{plan.sheets === 1 ? "" : "s"}</strong>
          {" "}({Object.entries(plan.sheets_by_size).map(([s, n]) => `${n} ${s}`).join(", ")})
          {plan.sheets_alone > plan.sheets
            ? <> · {plan.sheets_alone} if each order were made on its own: <strong>{plan.sheets_alone - plan.sheets} saved</strong></>
            : null}
          {plan.bonus > 0 && <> · {plan.bonus} free bonus cop{plan.bonus === 1 ? "y" : "ies"}</>}
          {plan.blank > 0 && <> · {plan.blank} blank piece{plan.blank === 1 ? "" : "s"}</>}
          <br />
          <span className="small muted">
            Envelopes: {plan.envelopes.map((e) => `#${e.order} ${e.pieces} pc ≈ ${e.weight_g} g (${e.lettermail})`).join(" · ")}
          </span>
        </p>
      )}
      {planErr && <ErrorBox message={planErr} />}
      <div className="actions">
        <label className="inline">Empty thirds
          <select value={props.unpaired} onChange={(e) => props.setUnpaired(e.target.value as "bonus" | "blank")}>
            <option value="bonus">free bonus copies</option>
            <option value="blank">blank</option>
          </select>
        </label>
        <button className="primary" disabled={!canMake || props.making} onClick={props.onMake}>
          Make {selected.length === 1 ? "this order" : `these ${selected.length} orders together`}
        </button>
        {props.making && <Spinner label="Making the batch (labels, print PDFs, proofs)…" />}
      </div>
    </section>
  );
}
