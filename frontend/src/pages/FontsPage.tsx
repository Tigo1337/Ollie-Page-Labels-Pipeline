import { useEffect, useState } from "react";
import { api, FontStatus } from "../api";
import { ErrorBox, Spinner } from "../ui";

interface FontsResp { fonts: FontStatus[]; job: { running: boolean; report: string[] } }

export default function FontsPage() {
  const [data, setData] = useState<FontsResp | null>(null);
  const [err, setErr] = useState("");
  const [chartLang, setChartLang] = useState("en");
  const load = () => api.get<FontsResp>("/api/fonts").then(setData).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!data?.job.running) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [data?.job.running]);

  const download = async (force = false) => {
    try {
      await api.post(`/api/fonts/download${force ? "?force=true" : ""}`);
      setTimeout(load, 300);
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  if (err) return <ErrorBox message={err} />;
  if (!data) return <Spinner label="Loading…" />;
  const missing = data.fonts.filter((f) => !f.installed).length;
  return (
    <div>
      <div className="row-between">
        <h2>Fonts</h2>
        <div className="actions">
          {data.job.running ? <Spinner label="Downloading fonts…" /> : (
            <>
              <button className={missing ? "primary" : ""} onClick={() => download(false)}>Download missing</button>
              <button onClick={() => download(true)}>Re-download all</button>
            </>
          )}
        </div>
      </div>
      <p className="muted">Free Google Fonts (SIL OFL / Apache 2.0), stored with their licence files.</p>
      <table className="table">
        <thead><tr><th>#</th><th>Font</th><th>File</th><th>Weight</th><th>Minis</th><th>Licence</th><th>Status</th></tr></thead>
        <tbody>
          {data.fonts.map((f) => (
            <tr key={f.id}>
              <td>{f.id}</td><td>{f.name}</td><td><code>{f.file}</code></td><td>{f.weight ?? "–"}</td>
              <td>{f.mini_ok ? "ok" : <span className="bad">warn</span>}</td>
              <td>{f.licence ?? "–"}</td>
              <td>{f.installed ? <span className="ok">installed</span> : <span className="bad">missing</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.job.report.length > 0 && (
        <details><summary>Last download report</summary><pre>{data.job.report.join("\n")}</pre></details>
      )}
      <section className="card">
        <div className="row-between">
          <h3>Font chart</h3>
          <div className="actions">
            <select value={chartLang} onChange={(e) => setChartLang(e.target.value)}>
              <option value="en">English</option><option value="fr">Français</option>
            </select>
            <a className="button" href={`/api/fontchart.png?lang=${chartLang}&download=1`}>Download PNG</a>
          </div>
        </div>
        {missing === 0 ? <img className="review" src={`/api/fontchart.png?lang=${chartLang}`} alt="Font chart" />
          : <p className="muted">Install all fonts to render the chart.</p>}
      </section>
    </div>
  );
}
