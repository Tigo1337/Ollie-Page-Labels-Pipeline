import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, ApiError, Catalog, onUnauthorized } from "./api";
import { ErrorBox } from "./ui";
import MakePage from "./pages/MakePage";
import DesignsPage from "./pages/DesignsPage";
import DesignPage from "./pages/DesignPage";
import FontsPage from "./pages/FontsPage";
import CropEditor from "./pages/CropEditor";
import SettingsPage from "./pages/SettingsPage";

interface AppCtx {
  catalog: Catalog;
  reloadCatalog: () => void;
}
const Ctx = createContext<AppCtx | null>(null);
export const useApp = () => useContext(Ctx)!;

function useHashRoute(): string[] {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
}

function Login({ onDone }: { onDone: () => void }) {
  const [secret, setSecret] = useState("");
  const [err, setErr] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.post("/api/login", { secret });
      onDone();
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <h1>Label Pipeline</h1>
        <label>
          Secret
          <input type="password" value={secret} autoFocus onChange={(e) => setSecret(e.target.value)} />
        </label>
        {err && <ErrorBox message={err} />}
        <button className="primary" type="submit">Log in</button>
      </form>
    </div>
  );
}

export default function App() {
  const route = useHashRoute();
  const [auth, setAuth] = useState<{ required: boolean; ok: boolean; warning?: string } | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [err, setErr] = useState("");

  const checkAuth = useCallback(() => {
    api.get<{ required: boolean; ok: boolean; warning?: string }>("/api/auth").then(setAuth).catch((e) => setErr(e.message));
  }, []);
  const reloadCatalog = useCallback(() => {
    api.get<Catalog>("/api/catalog").then(setCatalog).catch((e: ApiError) => e.status !== 401 && setErr(e.message));
  }, []);

  useEffect(() => {
    checkAuth();
    onUnauthorized(() => setAuth((a) => (a ? { ...a, ok: false } : a)));
  }, [checkAuth]);
  useEffect(() => {
    if (auth?.ok) reloadCatalog();
  }, [auth?.ok, reloadCatalog]);

  if (err) return <div className="page"><ErrorBox message={err} /></div>;
  if (!auth) return <div className="page muted">Loading…</div>;
  if (!auth.ok) return <Login onDone={checkAuth} />;
  if (!catalog) return <div className="page muted">Loading…</div>;

  const [top, arg, sub] = route;
  let page;
  if (top === "designs" && arg && sub === "crop") page = <CropEditor id={arg} />;
  else if (top === "designs" && arg) page = <DesignPage id={arg} />;
  else if (top === "designs") page = <DesignsPage />;
  else if (top === "fonts") page = <FontsPage />;
  else if (top === "settings") page = <SettingsPage />;
  else page = <MakePage />;

  const link = (href: string, label: string, active: boolean) => (
    <a href={href} className={active ? "active" : ""}>{label}</a>
  );
  return (
    <Ctx.Provider value={{ catalog, reloadCatalog }}>
      <header className="topbar">
        <span className="brand">Label Pipeline</span>
        <nav>
          {link("#/", "Make labels", !top || top === "make")}
          {link("#/designs", "Designs", top === "designs")}
          {link("#/fonts", "Fonts", top === "fonts")}
          {link("#/settings", "Settings", top === "settings")}
        </nav>
        {auth.required && (
          <button className="link" onClick={() => api.post("/api/logout").then(checkAuth)}>Log out</button>
        )}
      </header>
      {auth.warning && <div className="banner">{auth.warning}</div>}
      <main className="page">{page}</main>
    </Ctx.Provider>
  );
}
