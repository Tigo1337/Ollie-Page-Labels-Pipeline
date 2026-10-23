import { useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import { ErrorBox } from "../ui";

interface Production { piece_weight_g: number; envelope_weight_g: number; piece_thickness_mm: number }

const FIELDS: [keyof Production, string, string][] = [
  ["piece_weight_g", "Weight of one third (g)", "Weigh a real laminated third with its backing and put the number here."],
  ["envelope_weight_g", "Weight of an empty #10 envelope (g)", ""],
  ["piece_thickness_mm", "Thickness of one third (mm)", "Standard Lettermail is at most 5 mm thick."],
];

export default function SettingsPage() {
  const { catalog, reloadCatalog } = useApp();
  const [prod, setProd] = useState<Production | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    api.get<Production>("/api/production").then((p) => {
      setProd(p);
      setDraft(Object.fromEntries(FIELDS.map(([k]) => [k, String(p[k])])));
    }).catch((e) => setErr(e.message));
  }, []);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    try {
      const p = await api.patch<Production>("/api/production", Object.fromEntries(FIELDS.map(([k]) => [k, Number(draft[k])])));
      setProd(p);
      reloadCatalog();
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  const finish = catalog.finishes[0];
  return (
    <div>
      <h2>Settings</h2>
      <section className="card">
        <h3>Finish</h3>
        {finish && (
          <p>
            <strong>{finish.label}</strong> on every label: {finish.media} with {finish.laminate}.{" "}
            {finish.notch ? "The laminate is notched at the three mark corners (a laminate_notches.dxf is included)." : ""}
          </p>
        )}
      </section>
      <section className="card">
        <h3>Envelope estimate</h3>
        <p className="muted">Every third ships flat in a #10 envelope. The Make page estimates the envelope's weight
          (thirds × weight of a third + the envelope) and its Canada Post Lettermail class.</p>
        {prod && (
          <form onSubmit={save} className="grid-form">
            {FIELDS.map(([k, label, hint]) => (
              <label key={k}>{label}{hint && <small className="muted">{hint}</small>}
                <input type="number" step="any" min="0" value={draft[k] ?? ""}
                       onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} />
              </label>
            ))}
            <div className="span2 actions">
              <button className="primary">Save</button>
              {saved && <span className="ok">Saved</span>}
            </div>
          </form>
        )}
        {err && <ErrorBox message={err} />}
      </section>
    </div>
  );
}
