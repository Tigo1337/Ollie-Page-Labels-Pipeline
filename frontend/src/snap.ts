/**
 * Snapping for the crop editor's name box. Everything is in label millimetres
 * (origin at the top-left of the cut line).
 *
 * Guides (label centre, 1 mm safe-zone edges) are magnetic: an edge or the box
 * centre within `tol` mm jumps onto them. Otherwise positions step on the grid.
 */
export interface SnapResult { value: number; guide?: number }

const nearest = (v: number, step: number) => Math.round(v / step) * step;

/** Snap one edge (used when resizing). */
export function snapEdge(v: number, guides: number[], grid: number, tol: number): SnapResult {
  let best: SnapResult | null = null;
  for (const g of guides) {
    if (Math.abs(g - v) <= tol && (!best || Math.abs(g - v) < Math.abs(best.value - v))) best = { value: g, guide: g };
  }
  if (best) return best;
  return { value: grid > 0 ? nearest(v, grid) : v };
}

/** Snap a moving span [lo, hi] (used when dragging the box): returns the offset to apply. */
export function snapSpan(lo: number, hi: number, guides: number[], grid: number, tol: number): { delta: number; guide?: number } {
  let best: { delta: number; guide?: number } | null = null;
  const mid = (lo + hi) / 2;
  for (const g of guides) {
    for (const v of [lo, hi, mid]) {
      const d = g - v;
      if (Math.abs(d) <= tol && (!best || Math.abs(d) < Math.abs(best.delta))) best = { delta: d, guide: g };
    }
  }
  if (best) return best;
  return { delta: grid > 0 ? nearest(lo, grid) - lo : 0 };
}
