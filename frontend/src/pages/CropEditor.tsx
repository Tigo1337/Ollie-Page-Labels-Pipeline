import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, Design, PresetData, Preview, Size } from "../api";
import { useApp } from "../App";
import { snapEdge, snapSpan } from "../snap";
import { ErrorBox, Spinner, useAsync, useDebounced, Warnings } from "../ui";

interface SizePreset { size: string; preset: PresetData | null; auto: PresetData | null; is_auto: boolean; review: string | null }
interface PresetsResp { sizes: SizePreset[]; art: Record<string, [number, number]>; bleed: number; safe: number }

const TEST_NAMES = ["Léo", "Maximilien"];
const GRID_STEPS = [0.5, 1, 2];
const SNAP_TOL_PX = 8;   // how close (screen px) an edge must be to a guide to jump onto it

function loadPref<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}
function savePref(key: string, v: unknown) {
  try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* private mode */ }
}
const MAX_STAGE_W = 760;
const MAX_STAGE_H = 480;

// ---- the same crop maths as engine/art.py:crop_window -------------------------
function cropWindow(p: PresetData, sw: number, sh: number, aspect: number) {
  let ch = Math.max(1e-6, p.height) * sh;
  let cw = ch * aspect;
  if (cw > sw) { cw = sw; ch = cw / aspect; }
  if (ch > sh) { ch = sh; cw = ch * aspect; }
  const cx = p.center[0] * sw, cy = p.center[1] * sh;
  const x0 = Math.min(Math.max(cx - cw / 2, 0), sw - cw);
  const y0 = Math.min(Math.max(cy - ch / 2, 0), sh - ch);
  return { x0, y0, cw, ch };
}
const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);
const round = (v: number) => Math.round(v * 10000) / 10000;

/** Re-centre a preset on its clamped window so the stored fractions match what is shown. */
function normalise(p: PresetData, sw: number, sh: number, aspect: number): PresetData {
  const w = cropWindow(p, sw, sh, aspect);
  return { ...p, center: [round((w.x0 + w.cw / 2) / sw), round((w.y0 + w.ch / 2) / sh)], height: round(w.ch / sh) };
}

type Drag =
  | { kind: "crop"; px: number; py: number; x0: number; y0: number }
  | { kind: "box"; px: number; py: number; text: PresetData["text"] }
  | { kind: "corner"; corner: 0 | 1 | 2 | 3; text: PresetData["text"] };

export default function CropEditor({ id }: { id: string }) {
  const { catalog } = useApp();
  const [tick, setTick] = useState(0);
  const design = useAsync(() => api.get<Design>(`/api/designs/${encodeURIComponent(id)}`), [id]);
  const presets = useAsync(() => api.get<PresetsResp>(`/api/designs/${encodeURIComponent(id)}/presets`), [id, tick]);
  const [sizeId, setSizeId] = useState(catalog.sizes[0].id);
  const [edit, setEdit] = useState<PresetData | null>(null);
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const size = catalog.sizes.find((s) => s.id === sizeId)!;
  const entry = presets.data?.sizes.find((s) => s.size === sizeId);

  // load the size's preset into the editor (unless there are unsaved edits for it)
  useEffect(() => {
    if (!entry) return;
    setEdit(entry.preset);
    setDirty(false);
  }, [entry]);

  const chooseSize = (sid: string) => {
    if (dirty && !window.confirm("You have unsaved changes for this size. Discard them?")) return;
    setMsg("");
    setErr("");
    setSizeId(sid);
  };

  const act = async (fn: () => Promise<unknown>, done: string) => {
    setErr("");
    setMsg("");
    try {
      await fn();
      setMsg(done);
      setDirty(false);
      setTick((t) => t + 1);
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  if (design.error || presets.error) return <ErrorBox message={(design.error || presets.error)!} />;
  if (!design.data || !presets.data) return <Spinner label="Loading…" />;
  const d = design.data;
  const art = presets.data.art;
  if (!art.wide && !art.square) {
    return (
      <div>
        <p><a href={`#/designs/${encodeURIComponent(id)}`}>← {d.name}</a></p>
        <ErrorBox message="Upload the wide and square artwork first." />
      </div>
    );
  }

  return (
    <div>
      <p><a href={`#/designs/${encodeURIComponent(id)}`}>← {d.name}</a></p>
      <h2>Crop &amp; name position · {d.name}</h2>
      <p className="muted">
        Set this once per size. Every order uses the saved setting until you change it. Drag the crop window to move it,
        use the slider or mouse wheel to zoom, and drag or resize the dashed name box.
      </p>
      <div className="tabs">
        {catalog.sizes.map((s) => {
          const e = presets.data!.sizes.find((x) => x.size === s.id);
          return (
            <button key={s.id} className={s.id === sizeId ? "tab active" : "tab"} onClick={() => chooseSize(s.id)}>
              {s.label}<br />
              {e?.review
                ? <small className="bad">à revoir</small>
                : <small className={e?.is_auto ? "muted" : "ok"}>{e?.is_auto ? "automatic" : "saved"}</small>}
            </button>
          );
        })}
      </div>
      {entry?.review && <Warnings items={[`${size.label}: ${entry.review}. Check the crop and save it again.`]} />}
      {edit ? (
        <Editor key={sizeId} size={size} preset={edit} art={art} bleed={presets.data.bleed} safe={presets.data.safe}
          design={d}
          onChange={(p) => { setEdit(p); setDirty(true); setMsg(""); }}
          isAuto={!!entry?.is_auto} dirty={dirty}
          onSave={() => act(() => api.put(`/api/designs/${id}/presets/${sizeId}`, edit), `Saved the ${size.label} crop.`)}
          onReset={() => act(() => api.del(`/api/designs/${id}/presets/${sizeId}`), `${size.label} is back to the automatic layout.`)}
          onCopy={() => act(async () => {
            if (dirty) await api.put(`/api/designs/${id}/presets/${sizeId}`, edit);
            await api.post(`/api/designs/${id}/presets/${sizeId}/copy-to-rect`);
          }, "Copied to all rectangular sizes.")}
        />
      ) : (
        <ErrorBox message={`Upload the ${size.is_rect ? "wide" : "square"} artwork to set up this size.`} />
      )}
      {msg && <div className="okbox">{msg}</div>}
      {err && <ErrorBox message={err} />}
    </div>
  );
}

function Editor(props: {
  size: Size; preset: PresetData; art: Record<string, [number, number]>; bleed: number; safe: number; design: Design;
  isAuto: boolean; dirty: boolean;
  onChange: (p: PresetData) => void; onSave: () => void; onReset: () => void; onCopy: () => void;
}) {
  const { size, preset: p, art, bleed: b, safe, design, onChange } = props;
  const { catalog } = useApp();
  const [sw, sh] = art[p.source] ?? [1, 1];
  const aspect = (size.w + 2 * b) / (size.h + 2 * b);
  const scale = Math.min(MAX_STAGE_W / sw, MAX_STAGE_H / sh);
  const DW = sw * scale, DH = sh * scale;
  const win = cropWindow(p, sw, sh, aspect);
  const W = { x: win.x0 * scale, y: win.y0 * scale, w: win.cw * scale, h: win.ch * scale };
  const k = W.w / (size.w + 2 * b);            // display px per mm inside the window
  const hMax = Math.min(1, sw / (aspect * sh));
  const version = p.source === "wide" ? design.art.wide_version : design.art.square_version;

  // label mm -> display px
  const lx = (mm: number) => W.x + (b + mm) * k;
  const ly = (mm: number) => W.y + (b + mm) * k;
  // the name box is a fraction of one label: for a shoe pair, the left label (the right one mirrors it)
  const pair = size.shape === "pair" && size.pair ? size.pair : null;
  const LW = pair ? pair.each_w : size.w, LH = size.h;
  const rightX = pair ? pair.each_w + pair.gap : 0;
  const [tx0, ty0, tx1, ty1] = p.text;
  const box = { x: lx(tx0 * LW), y: ly(ty0 * LH), w: (tx1 - tx0) * LW * k, h: (ty1 - ty0) * LH * k };

  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<Drag | null>(null);

  // snapping: a millimetre grid plus magnetic guides (label centre, safe-zone edges)
  const [snap, setSnapState] = useState<boolean>(() => loadPref("crop.snap", true));
  const [gridMm, setGridState] = useState<number>(() => loadPref("crop.grid", 1));
  const setSnap = (v: boolean) => { setSnapState(v); savePref("crop.snap", v); };
  const setGrid = (v: number) => { setGridState(v); savePref("crop.grid", v); };
  const [hit, setHit] = useState<{ x?: number; y?: number }>({});
  const guides = {
    x: [safe, LW / 2, LW - safe],
    y: [safe, LH / 2, LH - safe],
  };
  const tol = SNAP_TOL_PX / k;
  const pt = (e: React.PointerEvent) => {
    const r = svgRef.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  const start = (e: React.PointerEvent, dr: Drag) => {
    e.stopPropagation();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    svgRef.current!.setPointerCapture(e.pointerId);
    drag.current = dr;
  };
  const move = (e: React.PointerEvent) => {
    const dr = drag.current;
    if (!dr) return;
    const q = pt(e);
    if (dr.kind === "crop") {
      const x0 = clamp(dr.x0 + (q.x - dr.px) / scale, 0, sw - win.cw);
      const y0 = clamp(dr.y0 + (q.y - dr.py) / scale, 0, sh - win.ch);
      onChange({ ...p, center: [round((x0 + win.cw / 2) / sw), round((y0 + win.ch / 2) / sh)] });
    } else if (dr.kind === "box") {
      // work in label mm so the grid is physical and the same on every size
      const [a, bb, c, dd] = dr.text;
      let x0 = a * LW + (q.x - dr.px) / k, x1 = c * LW + (q.x - dr.px) / k;
      let y0 = bb * LH + (q.y - dr.py) / k, y1 = dd * LH + (q.y - dr.py) / k;
      const free = !snap || e.altKey;
      const sx = free ? { delta: 0 } : snapSpan(x0, x1, guides.x, gridMm, tol);
      const sy = free ? { delta: 0 } : snapSpan(y0, y1, guides.y, gridMm, tol);
      x0 += sx.delta; x1 += sx.delta; y0 += sy.delta; y1 += sy.delta;
      const mx = clamp(0, -x0, LW - x1), my = clamp(0, -y0, LH - y1);
      setHit({ x: mx === 0 ? sx.guide : undefined, y: my === 0 ? sy.guide : undefined });
      onChange({ ...p, text: [round((x0 + mx) / LW), round((y0 + my) / LH), round((x1 + mx) / LW), round((y1 + my) / LH)] });
    } else {
      const free = !snap || e.altKey;
      let ex = clamp((q.x - W.x) / k - b, 0, LW);
      let ey = clamp((q.y - W.y) / k - b, 0, LH);
      const sx = free ? { value: ex } : snapEdge(ex, guides.x, gridMm, tol);
      const sy = free ? { value: ey } : snapEdge(ey, guides.y, gridMm, tol);
      ex = clamp(sx.value, 0, LW);
      ey = clamp(sy.value, 0, LH);
      setHit({ x: sx.guide, y: sy.guide });
      const fx = ex / LW, fy = ey / LH;
      let [a, bb, c, dd] = dr.text;
      const min = 0.06;
      if (dr.corner === 0 || dr.corner === 3) a = Math.min(fx, c - min); else c = Math.max(fx, a + min);
      if (dr.corner === 0 || dr.corner === 1) bb = Math.min(fy, dd - min); else dd = Math.max(fy, bb + min);
      onChange({ ...p, text: [round(a), round(bb), round(c), round(dd)] });
    }
  };
  const end = () => { drag.current = null; setHit({}); };

  const setHeight = (h: number) => onChange(normalise({ ...p, height: clamp(h, 0.05, hMax) }, sw, sh, aspect));
  const wheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
    setHeight(p.height * (e.deltaY > 0 ? 1.06 : 1 / 1.06));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p, sw, sh, aspect, hMax]);
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [wheel]);

  const switchSource = (src: "wide" | "square") => {
    if (src === p.source || !art[src]) return;
    const [w2, h2] = art[src];
    onChange(normalise({ ...p, source: src, center: [0.5, 0.5], height: Math.min(1, w2 / (aspect * h2)) }, w2, h2, aspect));
  };

  // cut line and safe zone inside the window
  const labelXs = pair ? [0, rightX] : [0];
  const cut = size.shape === "circle"
    ? <circle cx={lx(size.w / 2)} cy={ly(size.h / 2)} r={(size.w / 2) * k} />
    : <>{labelXs.map((x0) => <rect key={x0} x={lx(x0)} y={ly(0)} width={LW * k} height={LH * k} rx={size.r * k} />)}</>;
  const safeShape = size.shape === "circle"
    ? <circle cx={lx(size.w / 2)} cy={ly(size.h / 2)} r={(size.w / 2 - safe) * k} />
    : <>{labelXs.map((x0) => <rect key={x0} x={lx(x0 + safe)} y={ly(safe)} width={(LW - 2 * safe) * k} height={(LH - 2 * safe) * k} rx={Math.max(0, size.r - safe) * k} />)}</>;

  // live preview with the real engine
  const [font, setFont] = useState(1);
  const [extra, setExtra] = useState("");
  const names = useMemo(() => [...TEST_NAMES, ...(extra.trim() ? [extra.trim()] : [])], [extra]);
  const previewKey = useDebounced(JSON.stringify({ p, names, font }), 300);
  const [previews, setPreviews] = useState<{ name: string; r?: Preview; err?: string }[]>([]);
  useEffect(() => {
    const { p: pp, names: nn, font: ff } = JSON.parse(previewKey);
    let stale = false;
    (async () => {
      const out: { name: string; r?: Preview; err?: string }[] = [];
      for (const name of nn as string[]) {
        try {
          const r = await api.post<Preview>("/api/preview", { design: design.id, size: size.id, name, font: ff, preset: pp, scale: Math.min(12, 380 / size.w) });
          out.push({ name, r });
        } catch (e) {
          out.push({ name, err: (e as Error).message });
        }
        if (stale) return;
        setPreviews([...out]);
      }
    })();
    return () => { stale = true; };
  }, [previewKey, design.id, size.id, size.w]);

  return (
    <div className="crop-layout">
      <section className="card">
        <div className="row-between">
          <div className="actions">
            <span className="muted">Image:</span>
            {(["wide", "square"] as const).map((src) => (
              <button key={src} className={p.source === src ? "primary" : ""} disabled={!art[src]} onClick={() => switchSource(src)}>
                {src === "wide" ? "Wide strip" : "Square"}
              </button>
            ))}
          </div>
          <div className="actions snap-controls">
            <label className="inline"><input type="checkbox" checked={snap} onChange={(e) => setSnap(e.target.checked)} /> Snap name box</label>
            <select value={gridMm} disabled={!snap} onChange={(e) => setGrid(Number(e.target.value))} aria-label="Grid size">
              {GRID_STEPS.map((g) => <option key={g} value={g}>{g} mm grid</option>)}
            </select>
          </div>
          <label className="zoom">Zoom
            <input type="range" min={0.05} max={hMax} step={0.001} value={hMax + 0.05 - Math.min(p.height, hMax)}
              onChange={(e) => setHeight(hMax + 0.05 - Number(e.target.value))} />
          </label>
        </div>
        <div className="stage" style={{ width: DW, height: DH }}>
          <img src={`/api/designs/${design.id}/art/${p.source}?w=1600&v=${version}`} width={DW} height={DH} alt="" draggable={false} />
          <svg ref={svgRef} width={DW} height={DH} onPointerMove={move} onPointerUp={end} onPointerCancel={end}>
            <path fillRule="evenodd" fill="rgba(20,20,30,0.55)"
              d={`M0 0H${DW}V${DH}H0Z M${W.x} ${W.y}h${W.w}v${W.h}h${-W.w}Z`} />
            <rect className="crop-window" x={W.x} y={W.y} width={W.w} height={W.h}
              onPointerDown={(e) => start(e, { kind: "crop", px: pt(e).x, py: pt(e).y, x0: win.x0, y0: win.y0 })} />
            {pair && (
              <g className="pair-split" pointerEvents="none">
                <rect x={lx(pair.each_w)} y={ly(-b)} width={pair.gap * k} height={(LH + 2 * b) * k} />
                <line x1={lx(pair.each_w + pair.gap / 2)} x2={lx(pair.each_w + pair.gap / 2)} y1={ly(-b)} y2={ly(LH + b)} />
              </g>
            )}
            <g className="cut-line">{cut}</g>
            <g className="safe-line">{safeShape}</g>
            {snap && (
              <g className="grid" pointerEvents="none">
                {Array.from({ length: Math.floor(LW / gridMm) + 1 }, (_, i) => i * gridMm).map((x) => (
                  <line key={`gx${x}`} x1={lx(x)} x2={lx(x)} y1={ly(0)} y2={ly(LH)} />
                ))}
                {Array.from({ length: Math.floor(LH / gridMm) + 1 }, (_, i) => i * gridMm).map((y) => (
                  <line key={`gy${y}`} x1={lx(0)} x2={lx(LW)} y1={ly(y)} y2={ly(y)} />
                ))}
                <line className="centre" x1={lx(LW / 2)} x2={lx(LW / 2)} y1={ly(0)} y2={ly(LH)} />
                <line className="centre" x1={lx(0)} x2={lx(LW)} y1={ly(LH / 2)} y2={ly(LH / 2)} />
              </g>
            )}
            {pair && <rect className="name-box ghost" x={box.x + rightX * k} y={box.y} width={box.w} height={box.h} pointerEvents="none" />}
            <rect className="name-box" x={box.x} y={box.y} width={box.w} height={box.h}
              onPointerDown={(e) => start(e, { kind: "box", px: pt(e).x, py: pt(e).y, text: p.text })} />
            {[[box.x, box.y], [box.x + box.w, box.y], [box.x + box.w, box.y + box.h], [box.x, box.y + box.h]].map(([x, y], i) => (
              <rect key={i} className="handle" x={x - 6} y={y - 6} width={12} height={12}
                onPointerDown={(e) => start(e, { kind: "corner", corner: i as 0 | 1 | 2 | 3, text: p.text })} />
            ))}
            <g className="snap-hit" pointerEvents="none">
              {hit.x !== undefined && <line x1={lx(hit.x)} x2={lx(hit.x)} y1={ly(-b)} y2={ly(size.h + b)} />}
              {hit.y !== undefined && <line x1={lx(-b)} x2={lx(size.w + b)} y1={ly(hit.y)} y2={ly(hit.y)} />}
            </g>
          </svg>
        </div>
        <p className="muted small legend">
          <span className="key cut" /> cut line <span className="key bleed" /> crop window (label + 1.25 mm bleed)
          <span className="key safe" /> 1 mm safe zone <span className="key name" /> name box
          {pair && <> · shoe pair: one picture split into two labels ({pair.gap} mm gap); set the name box on the left label, the right one copies it</>}
        </p>
        {snap && (
          <p className="muted small">
            The name box snaps to the {gridMm} mm grid, the label centre (orange) and the safe zone. Hold Alt to move it freely.
          </p>
        )}
        <div className="actions">
          <button className="primary" onClick={props.onSave} disabled={!props.dirty && !props.isAuto}>
            {props.isAuto && !props.dirty ? "Save this automatic layout" : "Save preset"}
          </button>
          <button onClick={props.onReset} disabled={props.isAuto && !props.dirty}>Reset to automatic</button>
          {size.is_rect && <button onClick={props.onCopy} disabled={props.isAuto && !props.dirty}>Copy to all rectangular sizes</button>}
          {props.dirty && <span className="bad small">Unsaved changes</span>}
        </div>
      </section>
      <section className="card">
        <h3>{size.label} <span className="muted small">{size.dims}</span></h3>
        <div className="actions">
          <select value={font} onChange={(e) => setFont(Number(e.target.value))}>
            {catalog.fonts.map((f) => <option key={f.id} value={f.id}>{f.id} · {f.name}</option>)}
          </select>
          <input placeholder="Try another name" value={extra} onChange={(e) => setExtra(e.target.value)} />
        </div>
        {previews.length === 0 && <Spinner label="Rendering…" />}
        {previews.map(({ name, r, err }) => (
          <div key={name} className="crop-preview">
            {err ? <ErrorBox message={err} /> : r && (
              <>
                <img src={r.image} alt={name} />
                <div className={r.cap_mm.some((c) => c < r.min_cap_mm) ? "bad" : "muted"}>
                  "{name}" · caps {r.cap_mm.map((c) => c.toFixed(1)).join(" / ")} mm
                  {r.cap_mm.some((c) => c < r.min_cap_mm) && ` — below ${r.min_cap_mm} mm, hard to read`}
                </div>
                <Warnings items={r.warnings.filter((w) => !w.includes("cap height"))} />
              </>
            )}
          </div>
        ))}
      </section>
    </div>
  );
}
