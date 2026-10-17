export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

type Listener = () => void;
const unauthorized: Listener[] = [];
export function onUnauthorized(fn: Listener) {
  unauthorized.push(fn);
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError("Cannot reach the server. Is the app running?", 0);
  }
  if (res.status === 401) unauthorized.forEach((f) => f());
  if (!res.ok) {
    let msg = `Request failed (${res.status}).`;
    try {
      const j = await res.json();
      if (j && typeof j.detail === "string") msg = j.detail;
      else if (j && Array.isArray(j.detail)) msg = j.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* not JSON */
    }
    throw new ApiError(msg, res.status);
  }
  return (await res.json()) as T;
}

export const api = {
  get: <T>(url: string) => request<T>("GET", url),
  post: <T>(url: string, body?: unknown) => request<T>("POST", url, body),
  patch: <T>(url: string, body?: unknown) => request<T>("PATCH", url, body),
  del: <T>(url: string) => request<T>("DELETE", url),
};

// ---- types mirrored from the API ----
export interface Size {
  id: string; label: string; shape: "rrect" | "circle"; w: number; h: number; r: number;
  is_rect: boolean; dims: string; per_sheet: number;
}
export interface Pack { id: string; label: string; contents: Record<string, number>; total: number; sheets: number }
export interface Finish { id: string; label: string; media: string; laminate: string; notch: boolean; cost_per_sheet: number | null }
export interface FontSpec { id: number; name: string; repo_dir: string; file: string; weight: number | null; mini_ok: boolean }
export interface Catalog { production: Record<string, number | boolean>; sizes: Size[]; packs: Pack[]; finishes: Finish[]; fonts: FontSpec[] }

export interface PresetData { source: "wide" | "square"; center: [number, number]; height: number; text: [number, number, number, number] }
export interface Design {
  id: string; name: string; fill: string; stroke: string; char_end: number; stroke_ratio: number | null;
  effective_stroke_ratio: number; cap_frac: number; position: number; presets: Record<string, PresetData>;
  art: { wide: boolean; square: boolean; wide_size: [number, number] | null; square_size: [number, number] | null;
         wide_version: string | null; square_version: string | null };
}
export interface Preview { image: string; cap_mm: number[]; warnings: string[]; preset: PresetData; preset_is_auto: boolean; min_cap_mm: number }
export interface RunFile { name: string; size: number; kind: string }
export interface Run {
  id: string; title: string; prefix: string; created_at: string; request: Record<string, unknown>;
  files: RunFile[]; warnings: string[];
  summary: { finishes: Record<string, { sheets: number; labels: number }>;
             pages: { finish: string; n: number; count: number; x: number; y: number; w: number; h: number; proof: string }[] };
}
export interface FontStatus { id: number; name: string; installed: boolean; licence: string | null; mini_ok: boolean; weight: number | null; file: string }

export const fileUrl = (run: Run, name: string, download = false) =>
  `/api/runs/${encodeURIComponent(run.id)}/files/${encodeURIComponent(name)}${download ? "?download=1" : ""}`;
