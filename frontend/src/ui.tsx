import { useEffect, useRef, useState } from "react";

export function ErrorBox({ message }: { message: string }) {
  return <div className="error" role="alert">{message}</div>;
}

export function Warnings({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="warnings">
      {items.map((w) => <li key={w}>{w}</li>)}
    </ul>
  );
}

export function Spinner({ label = "Working…" }: { label?: string }) {
  return <span className="spinner" aria-live="polite">{label}</span>;
}

/** Debounced value: changes `delay` ms after the input stops changing. */
export function useDebounced<T>(value: T, delay = 350): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}

/** Run an async loader whenever `deps` change; ignores stale results. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<{ data?: T; error?: string; loading: boolean }>({ loading: true });
  const seq = useRef(0);
  useEffect(() => {
    const my = ++seq.current;
    setState((s) => ({ ...s, loading: true, error: undefined }));
    fn().then(
      (data) => my === seq.current && setState({ data, loading: false }),
      (e: Error) => my === seq.current && setState({ error: e.message, loading: false }),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

export function fmtBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function Progress({ value, label }: { value: number; label: string }) {
  return (
    <div className="progress" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <div className="progress-bar"><div style={{ width: `${Math.max(2, value * 100)}%` }} /></div>
      <span className="muted small">{label}</span>
    </div>
  );
}
