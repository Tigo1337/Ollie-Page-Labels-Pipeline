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

/** POST a FormData with upload progress (fetch cannot report it). `onProgress` gets 0..1. */
export function uploadWithProgress<T>(url: string, body: FormData, onProgress: (f: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onerror = () => reject(new ApiError("The upload failed: the connection was interrupted. Try again, or split the ZIP.", 0));
    xhr.onload = () => {
      if (xhr.status === 401) unauthorized.forEach((f) => f());
      let j: { detail?: unknown } | null = null;
      try { j = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(j as T);
      const msg = j && typeof j.detail === "string" ? j.detail
        : xhr.status === 413 ? "The ZIP is too large for the server. Split it into a few smaller ZIPs."
        : `Upload failed (${xhr.status}).`;
      reject(new ApiError(msg, xhr.status));
    };
    xhr.send(body);
  });
}

export const api = {
  get: <T>(url: string) => request<T>("GET", url),
  post: <T>(url: string, body?: unknown) => request<T>("POST", url, body),
  patch: <T>(url: string, body?: unknown) => request<T>("PATCH", url, body),
  put: <T>(url: string, body?: unknown) => request<T>("PUT", url, body),
  del: <T>(url: string) => request<T>("DELETE", url),
};

// ---- types mirrored from the API ----
export interface Size {
  id: string; label: string; shape: "rrect" | "circle" | "pair"; w: number; h: number; r: number;
  gap: number | null; pair: { each_w: number; gap: number } | null;
  is_rect: boolean; dims: string; layout_id: string | null; per_half: number; per_sheet: number;
}
export interface Pack {
  id: string; label: string; contents: Record<string, number>; total: number;
  halves_by_size: Record<string, number>; halves: number; batched: number; alone: number; error?: string;
}
export interface Finish { id: string; label: string; media: string; laminate: string; notch: boolean; cost_per_sheet: number | null }
export interface FontSpec { id: number; name: string; repo_dir: string; file: string; weight: number | null; mini_ok: boolean }
export interface Catalog { production: Record<string, number | boolean>; sheet: Record<string, number | boolean>; sizes: Size[]; packs: Pack[]; finishes: Finish[]; fonts: FontSpec[] }

export interface PresetData { source: "wide" | "square"; center: [number, number]; height: number; text: [number, number, number, number] }
export interface Design {
  id: string; name: string; fill: string; stroke: string; char_end: number; stroke_ratio: number | null;
  effective_stroke_ratio: number; cap_frac: number; position: number; presets: Record<string, PresetData>;
  review: Record<string, string>; mini_start: number; square_text: [number, number, number, number]; no_character_sizes: string[];
  art: { wide: boolean; square: boolean; wide_size: [number, number] | null; square_size: [number, number] | null;
         wide_version: string | null; square_version: string | null };
}
export interface Preview { image: string; cap_mm: number[]; warnings: string[]; preset: PresetData; preset_is_auto: boolean; min_cap_mm: number }
export interface RunFile { name: string; size: number; kind: string }
export interface RunHalf { order: string; size: string; name: string; finish: string; index: number; of: number; bonus: boolean; tag: string }
export interface RunSheet { n: number; finish: string; layout_id: string; size: string; pdf: string; page: number; proof: string; top: RunHalf; bottom: RunHalf | null }
export interface Run {
  id: string; title: string; prefix: string; created_at: string; request: Record<string, unknown>;
  files: RunFile[]; warnings: string[];
  summary: { finishes: Record<string, { sheets: number; labels: number }>; sheets?: RunSheet[]; waiting?: RunHalf[];
             templates?: { layout_id: string; studio3: boolean }[] };
}
export interface FontStatus { id: number; name: string; installed: boolean; licence: string | null; mini_ok: boolean; weight: number | null; file: string }

export const fileUrl = (run: Run, name: string, download = false) =>
  `/api/runs/${encodeURIComponent(run.id)}/files/${encodeURIComponent(name)}${download ? "?download=1" : ""}`;
