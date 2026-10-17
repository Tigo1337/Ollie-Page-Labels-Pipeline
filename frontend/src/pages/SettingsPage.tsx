import { useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import { ErrorBox } from "../ui";

interface Shop { default_finish: string }

export default function SettingsPage() {
  const { catalog } = useApp();
  const [shop, setShop] = useState<Shop | null>(null);
  const [err, setErr] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => { api.get<Shop>("/api/shop").then(setShop).catch((e) => setErr(e.message)); }, []);
  const update = async (patch: Partial<Shop>) => {
    setErr("");
    try {
      setShop(await api.patch<Shop>("/api/shop", patch));
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  if (!shop) return err ? <ErrorBox message={err} /> : null;
  const finish = catalog.finishes.find((f) => f.id === shop.default_finish);
  return (
    <div>
      <h2>Settings</h2>
      <section className="card">
        <h3>Finish</h3>
        <p className="muted">Orders don't choose a finish yet: every order uses this one.</p>
        <label>Finish for all orders
          <select value={shop.default_finish} onChange={(e) => update({ default_finish: e.target.value })}>
            {catalog.finishes.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select>
        </label>
        {finish && (
          <p className="muted small">
            {finish.media} with {finish.laminate}.{" "}
            {finish.notch ? "The laminate is notched at the three mark corners (a laminate_notches.dxf is included)." : "No laminate notch needed."}
          </p>
        )}
        {saved && <span className="ok">Saved</span>}
        {err && <ErrorBox message={err} />}
      </section>
    </div>
  );
}
