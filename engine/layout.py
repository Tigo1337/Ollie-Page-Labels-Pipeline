"""Fixed, maximum-density half-sheet layouts: one per label size, two identical halves per sheet.

Port of reference/sheet_opt.py (the prototype that produced the counts in
reference/sheet-layout-plan.md). The optimizer reasons in the printed view (portrait,
see `frames.py`) and only for the printed **top** half; the bottom half is every top cell
mirrored about the trim line. Cells are then converted to the Studio frame, which is what
the layout files, PDFs and cut templates use.

Candidates for the top half (keep the one with the most cells):
  * normal grid, rotated grid (non-square sizes), and for circles a row-wise hex packing;
    rows sit at a fixed pitch, the block is centred vertically (shifted ±5 mm in 0.25 mm
    steps) and each row is centred on its own in the x-range the corner zones leave free
  * circles: the classic hex grid shifted in x and y, and the staggered grid (4 rows of 5,
    the top row centred between the mark corners, each next row shifted toward the left)
    picked for the most corner clearance

Corner keep-outs: the bleed box stays out of the ink squares and the cut box out of the cut
squares, on all four corners. Circles are checked against the real circle, not its box.

A published layout file (layouts/<layout_id>.json) is never rewritten: when sheet.json or a
size's geometry changes, `rebuild` writes the next version (-v2, ...) next to it.
"""
from __future__ import annotations

import itertools
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import Sheet, Size, geometry_hash
from .frames import to_printed, to_studio

EPS = 1e-6
LAYOUT_PREFIX = "chels"
ROUND_MARGIN = 0.002  # added to diagonal row pitches so cells rounded to 0.001 mm keep the full gap

PRect = tuple[float, float, float, float]  # x0, y0, x1, y1


def _hit(r: PRect, z: PRect) -> bool:
    return r[0] < z[2] and r[2] > z[0] and r[1] < z[3] and r[3] > z[1]


# ---------------------------------------------------------------------------
# Optimizer (printed view, top half)
# ---------------------------------------------------------------------------
class _TopHalf:
    """The printed top half of one sheet for one size: the search space and its rules."""

    def __init__(self, sheet: Sheet, size: Size):
        self.size = size
        self.PW, self.PH = sheet.paper_h, sheet.paper_w          # printed page (portrait)
        self.trim_y = self.PH - sheet.trim_x                      # Studio X = trim  ->  printed y
        self.ink_k, self.cut_k = sheet.ink_keepout, sheet.cut_keepout
        self.bleed = sheet.bleed
        self.gap = size.gap_on(sheet)
        e = sheet.edge_margin
        self.box = (e, e, self.PW - e, self.trim_y - sheet.trim_margin)  # where cut boxes may go

    def corners(self, k: float) -> list[PRect]:
        """Corner squares on the top half's edge (printed top-left and top-right)."""
        return [(0.0, 0.0, k, k), (self.PW - k, 0.0, self.PW, k)]

    # -- rectangles ----------------------------------------------------------
    def rect_ok(self, x: float, y: float, w: float, h: float) -> bool:
        b = self.bleed
        if any(_hit((x - b, y - b, x + w + b, y + h + b), z) for z in self.corners(self.ink_k)):
            return False
        return not any(_hit((x, y, x + w, y + h), z) for z in self.corners(self.cut_k))

    def row_cells(self, w: float, h: float, y: float) -> list[tuple[float, float]]:
        """Most cells in a row at height y, centred in the x-range the corner zones leave free."""
        x0, _, x1, _ = self.box
        lo, hi = x0, x1
        for k, pad in ((self.ink_k, self.bleed), (self.cut_k, 0.0)):
            if y - pad < k:                                   # the row meets this corner band
                lo, hi = max(lo, k + pad), min(hi, self.PW - k - pad)
        n = math.floor((hi - lo + self.gap) / (w + self.gap))
        if n <= 0:
            return []
        ox = lo + (hi - lo - (n * w + (n - 1) * self.gap)) / 2
        return [(round(ox + i * (w + self.gap), 3), round(y, 3)) for i in range(n)
                if self.rect_ok(ox + i * (w + self.gap), y, w, h)]

    def rows_layout(self, w: float, h: float, hexr: bool, dy: float) -> list[tuple[float, float]]:
        _, y0, _, y1 = self.box
        py = (h + self.gap) * math.sqrt(3) / 2 + ROUND_MARGIN if hexr else h + self.gap
        rows = math.floor((y1 - y0 - h) / py) + 1
        oy = y0 + (y1 - y0 - ((rows - 1) * py + h)) / 2 + dy
        cells: list[tuple[float, float]] = []
        prev: list[tuple[float, float]] | None = None
        for r in range(rows):
            y = oy + r * py
            if y < y0 - EPS or y + h > y1 + EPS:
                continue
            rc = self.row_cells(w, h, y)
            if hexr and prev is not None:
                rc = self._hex_fix(rc, prev, w, h)
            cells += rc
            prev = rc
        return cells

    def _hex_fix(self, rc, prev, w, h):
        """Circles: keep centre distance >= w + gap to the previous row; shift by half a pitch if needed."""
        def clear(row):
            return all(math.hypot(a[0] - b[0], a[1] - b[1]) >= w + self.gap - EPS for a in row for b in prev)
        if clear(rc):
            return rc
        x0, _, x1, _ = self.box
        for shift in (w / 2 + self.gap / 2, -(w / 2 + self.gap / 2)):
            cand = [(x + shift, y) for x, y in rc]
            cand = [c for c in cand if c[0] >= x0 - EPS and c[0] + w <= x1 + EPS and self.rect_ok(c[0], c[1], w, h)]
            if clear(cand):
                return cand
        return [c for c in rc if all(math.hypot(c[0] - b[0], c[1] - b[1]) >= w + self.gap - EPS for b in prev)]

    def hex_grid(self, w: float, h: float, dx: float, dy: float) -> list[tuple[float, float]]:
        """Classic hex grid: alternate rows offset by half a pitch, the whole grid shifted by (dx, dy)."""
        x0, y0, x1, y1 = self.box
        W, H = x1 - x0, y1 - y0
        px, py = w + self.gap, (h + self.gap) * math.sqrt(3) / 2 + ROUND_MARGIN
        cols = math.floor((W + self.gap) / px)
        rows = math.floor((H - h) / py) + 1
        gw, gh = cols * w + (cols - 1) * self.gap + px / 2, (rows - 1) * py + h
        ox, oy = x0 + (W - gw) / 2 + dx, y0 + (H - gh) / 2 + dy
        out = []
        for r in range(rows):
            for c in range(cols):
                x, y = ox + c * px + (px / 2 if r % 2 else 0), oy + r * py
                if x < x0 - EPS or y < y0 - EPS or x + w > x1 + EPS or y + h > y1 + EPS:
                    continue
                if self.circle_ok(x, y, w):
                    out.append((round(x, 3), round(y, 3)))
        return out

    # -- circles ---------------------------------------------------------------
    def corner_clear(self, cx: float, cy: float, rad: float, k: float) -> float:
        """Clearance (mm) from a circle to the four page-corner squares of side k (negative = intrudes)."""
        best = 1e9
        for qx in (cx, self.PW - cx):
            for qy in (cy, self.PH - cy):
                best = min(best, math.hypot(max(0.0, qx - k), max(0.0, qy - k)) - rad)
        return best

    def circle_clearance(self, x: float, y: float, d: float) -> float:
        cx, cy, r = x + d / 2, y + d / 2, d / 2
        return min(self.corner_clear(cx, cy, r + self.bleed, self.ink_k), self.corner_clear(cx, cy, r, self.cut_k))

    def circle_ok(self, x: float, y: float, d: float) -> bool:
        return self.circle_clearance(x, y, d) >= 0

    def stagger(self, d: float, n: int = 5, rows: int = 4) -> list[tuple[float, float]]:
        """`rows` staggered rows of `n`; the top row centred on the page (between the two mark corners),
        the next row shifted by s. Picks the s / top-row x / y with the most corner clearance."""
        x0, y0, x1, y1 = self.box
        P = d + self.gap
        W = (n - 1) * P + d
        xc = (self.PW - W) / 2
        best: tuple[float, list] | None = None
        for s20 in range(0, int(P / 2 * 20) + 1):
            s = s20 / 20
            v = math.sqrt(max(0.0, P * P - s * s)) + ROUND_MARGIN
            if (rows - 1) * v + d > y1 - y0 + 1e-9:
                continue
            for k in range(-20, 21):                                # top row up to 1 mm off centre
                xa = xc + k * 0.05
                for xb in (xa - s, xa + s):
                    if xb < x0 - 1e-9 or xb + W > x1 + 1e-9:
                        continue
                    for y10 in range(0, int(((y1 - y0) - (rows - 1) * v - d) * 10) + 1):
                        yt = y0 + y10 / 10
                        cells = [(round((xa if r % 2 == 0 else xb) + i * P, 3), round(yt + r * v, 3))
                                 for r in range(rows) for i in range(n)]
                        cl = min(self.circle_clearance(x, y, d) for x, y in cells)
                        if cl >= 0 and (best is None or cl > best[0]):
                            best = (cl, cells)
        return best[1] if best else []


@dataclass
class Layout:
    """One size's fixed layout. Cells are Studio-frame (X, Y, W, H, rotated) in mm.

    `rotated` is about the printed view: True when the label is turned 90° from how it reads
    (e.g. pencil labels standing upright on the printed sheet).
    """
    layout_id: str
    size: str
    version: int
    geometry_hash: str
    arrangement: str
    rows: list[int]
    top: list[tuple[float, float, float, float, bool]]
    bottom: list[tuple[float, float, float, float, bool]]
    size_geometry: dict = field(default_factory=dict)

    @property
    def per_half(self) -> int:
        return len(self.top)

    @property
    def per_sheet(self) -> int:
        return len(self.top) + len(self.bottom)

    @property
    def cells(self) -> list[tuple[float, float, float, float, bool]]:
        return self.top + self.bottom

    def same_cells(self, other: "Layout", tol: float = 1e-6) -> bool:
        if len(self.top) != len(other.top) or len(self.bottom) != len(other.bottom):
            return False
        return all(a[4] == b[4] and all(abs(p - q) <= tol for p, q in zip(a[:4], b[:4]))
                   for a, b in zip(self.cells, other.cells))

    # -- file format -----------------------------------------------------------
    def to_json(self) -> str:
        def cell(c):
            return "[" + ", ".join(f"{v:g}" if not isinstance(v, bool) else str(v).lower() for v in c) + "]"
        head = {
            "_doc": "Fixed half-sheet layout. Never edit a published layout: a geometry change makes a new "
                    "version. Cells are [X, Y, W, H, rotated] in mm, Studio frame (landscape Letter, origin "
                    "top-left, y down); 'top'/'bottom' are the halves as the printed sheet is held (printed "
                    "top = Studio right half, X > trim). bottom[i] mirrors top[i] about the trim line.",
            "layout_id": self.layout_id, "size": self.size, "version": self.version,
            "geometry_hash": self.geometry_hash, "frame": "studio", "arrangement": self.arrangement,
            "per_half": self.per_half, "per_sheet": self.per_sheet, "rows": self.rows,
            "size_geometry": self.size_geometry,
        }
        parts = ["{"] + [f" {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}," for k, v in head.items()]
        for name in ("top", "bottom"):
            cells = getattr(self, name)
            parts.append(f' "{name}": [\n' + ",\n".join("  " + cell(c) for c in cells) + "\n ]"
                         + ("," if name == "top" else ""))
        return "\n".join(parts) + "\n}\n"

    @staticmethod
    def from_dict(d: dict) -> "Layout":
        def cells(v):
            return [(float(c[0]), float(c[1]), float(c[2]), float(c[3]), bool(c[4])) for c in v]
        return Layout(layout_id=d["layout_id"], size=d["size"], version=int(d["version"]),
                      geometry_hash=d["geometry_hash"], arrangement=d["arrangement"], rows=list(d["rows"]),
                      top=cells(d["top"]), bottom=cells(d["bottom"]), size_geometry=d.get("size_geometry", {}))

    @staticmethod
    def load(path: Path) -> "Layout":
        return Layout.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def layout_id(size_id: str, version: int) -> str:
    return f"{LAYOUT_PREFIX}-{size_id}-v{version}"


def optimize(sheet: Sheet, size: Size, version: int = 1) -> Layout:
    """Search the candidates and return the densest layout (printed top half + its mirror)."""
    t = _TopHalf(sheet, size)
    w, h = size.w, size.h
    rnd = size.shape == "circle"
    cands = [("normal", w, h, False, False)]
    if abs(w - h) > EPS:
        cands.append(("rotated", h, w, True, False))
    if rnd:
        cands.append(("hex", w, h, False, True))
    best = None  # (key, name, cw, ch, rotated, cells)
    for name, cw, ch, rot, hexr in cands:
        for i in range(41):
            dy = -5 + i * 0.25
            cs = t.rows_layout(cw, ch, hexr, dy)
            key = (len(cs), -abs(dy))
            if best is None or key > best[0]:
                best = (key, name, cw, ch, rot, cs)
    assert best is not None
    if rnd:
        for i, j in itertools.product(range(61), range(41)):
            dx, dy = -7.5 + i * 0.25, -5 + j * 0.25
            cs = t.hex_grid(w, h, dx, dy)
            key = (len(cs), -abs(dy))
            if key > best[0]:
                best = (key, "hex", w, h, False, cs)
        cs = t.stagger(w, 5, 4)
        if len(cs) > best[0][0]:
            best = ((len(cs), 0), "stagger", w, h, False, cs)
    _, name, cw, ch, rot, cs = best
    cs = sorted(cs, key=lambda c: (c[1], c[0]))                 # printed reading order
    rows: dict[float, int] = {}
    for _, y in cs:
        rows[y] = rows.get(y, 0) + 1

    def studio(x: float, y: float) -> tuple[float, float, float, float, bool]:
        X, Y, W, H = to_studio(x, y, cw, ch, studio_w=sheet.paper_w)  # type: ignore[misc]
        return round(X, 3), round(Y, 3), round(W, 3), round(H, 3), rot

    top = [studio(x, y) for x, y in cs]
    bottom = [studio(x, round(2 * t.trim_y - y - ch, 3)) for x, y in cs]
    return Layout(layout_id=layout_id(size.id, version), size=size.id, version=version,
                  geometry_hash=geometry_hash(sheet, size), arrangement=name, rows=list(rows.values()),
                  top=top, bottom=bottom, size_geometry=size.geometry())


# ---------------------------------------------------------------------------
# Rules check (Studio frame, independent of the optimizer)
# ---------------------------------------------------------------------------
def check_layout(layout: Layout, size: Size, sheet: Sheet) -> list[str]:
    """Every rule a layout must keep. Returns the problems (empty = good)."""
    problems: list[str] = []
    b, gap, e = sheet.bleed, size.gap_on(sheet), sheet.edge_margin
    W, H, T, tm = sheet.paper_w, sheet.paper_h, sheet.trim_x, sheet.trim_margin
    ink, cut = sheet.corner_squares(sheet.ink_keepout), sheet.corner_squares(sheet.cut_keepout)
    rnd = size.shape == "circle"
    dims = {(c[2], c[3], c[4]) for c in layout.cells}
    if len(dims) != 1:
        problems.append("cells do not all have the same size and orientation")
    if len(layout.top) != len(layout.bottom):
        problems.append("the halves hold different counts")
    for i, (a, m) in enumerate(zip(layout.top, layout.bottom)):
        if not (abs(m[0] - (2 * T - a[0] - a[2])) <= 0.01 and abs(m[1] - a[1]) <= 0.01
                and abs(m[2] - a[2]) <= 0.01 and abs(m[3] - a[3]) <= 0.01 and m[4] == a[4]):
            problems.append(f"bottom cell {i} is not the mirror of top cell {i}")
    for half, cells in (("top", layout.top), ("bottom", layout.bottom)):
        for i, (X, Y, w, h, _) in enumerate(cells):
            tag = f"{half} cell {i} at ({X:g}, {Y:g})"
            cutb, inkb = (X, Y, X + w, Y + h), (X - b, Y - b, X + w + b, Y + h + b)
            if rnd:
                cx, cy, r = X + w / 2, Y + h / 2, w / 2
                for k, rad, what in ((sheet.ink_keepout, r + b, "bleed in an ink keep-out"),
                                     (sheet.cut_keepout, r, "cut line in a cut keep-out")):
                    for qx, qy in itertools.product((cx, W - cx), (cy, H - cy)):
                        if math.hypot(max(0.0, qx - k), max(0.0, qy - k)) < rad - EPS:
                            problems.append(f"{tag}: {what}")
                            break
            else:
                if any(_hit(inkb, z) for z in ink):
                    problems.append(f"{tag}: bleed in an ink keep-out")
                if any(_hit(cutb, z) for z in cut):
                    problems.append(f"{tag}: cut line in a cut keep-out")
            if X < e - EPS or Y < e - EPS or X + w > W - e + EPS or Y + h > H - e + EPS:
                problems.append(f"{tag}: cut line inside the {e:g} mm edge margin")
            if X < T + tm - EPS and X + w > T - tm + EPS:
                problems.append(f"{tag}: cut line inside the trim gutter")
            if inkb[0] < T < inkb[2]:
                problems.append(f"{tag}: bleed crosses the trim line")
            if (half == "top") != (X > T):
                problems.append(f"{tag}: on the wrong side of the trim line")
    cells = layout.cells
    for (i, a), (j, c) in itertools.combinations(enumerate(cells), 2):
        if rnd:
            dist = math.hypot((a[0] + a[2] / 2) - (c[0] + c[2] / 2), (a[1] + a[3] / 2) - (c[1] + c[3] / 2))
            if dist < a[2] + gap - EPS:
                problems.append(f"cells {i} and {j}: circles closer than {gap:g} mm")
        else:
            sep = max(c[0] - (a[0] + a[2]), a[0] - (c[0] + c[2]), c[1] - (a[1] + a[3]), a[1] - (c[1] + c[3]))
            if sep < gap - EPS:
                problems.append(f"cells {i} and {j}: cut lines {sep:.3f} mm apart (< {gap:g})")
    return problems


def cell_labels(cell: tuple[float, float, float, float, bool], size: Size,
                sheet: Sheet) -> list[tuple[float, float, float, float]]:
    """The cut labels inside one cell, Studio-frame (X, Y, W, H): one, or two for a pair."""
    X, Y, W, H, rot = cell
    px_, py, _, _ = to_printed(X, Y, W, H, studio_w=sheet.paper_w)  # type: ignore[misc]
    out = []
    for lx, ly, lw, lh in size.label_rects():
        if rot:                                   # label turned 90° on the printed sheet
            lx, ly, lw, lh = ly, lx, lh, lw
        r = to_studio(px_ + lx, py + ly, lw, lh, studio_w=sheet.paper_w)
        out.append(tuple(round(v, 3) for v in r))  # type: ignore[union-attr]
    return out  # type: ignore[return-value]


def printed_cells(layout: Layout, sheet: Sheet) -> list[tuple[float, float, float, float]]:
    """All cells as printed-view (x, y, w, h)."""
    return [to_printed(X, Y, w, h, studio_w=sheet.paper_w) for X, Y, w, h, _ in layout.cells]  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Published layout files
# ---------------------------------------------------------------------------
_FILE = re.compile(rf"^{LAYOUT_PREFIX}-(?P<size>.+)-v(?P<v>\d+)\.json$")


def published(layouts_dir: Path) -> dict[str, list[Layout]]:
    """Layout files per size, oldest version first."""
    out: dict[str, list[Layout]] = {}
    for p in sorted(Path(layouts_dir).glob(f"{LAYOUT_PREFIX}-*.json")):
        if _FILE.match(p.name):
            lay = Layout.load(p)
            out.setdefault(lay.size, []).append(lay)
    for v in out.values():
        v.sort(key=lambda lay: lay.version)
    return out


class LayoutError(ValueError):
    pass


def current_layout(sheet: Sheet, size: Size, layouts_dir: Path) -> Layout:
    """The published layout built from today's geometry (newest matching version)."""
    want = geometry_hash(sheet, size)
    for lay in reversed(published(layouts_dir).get(size.id, [])):
        if lay.geometry_hash == want:
            return lay
    raise LayoutError(f"No published layout for size '{size.id}' matches the current sheet.json / sizes.json. "
                      "Run `python -m engine layouts` to build a new layout version.")


def stale_sizes(sheet: Sheet, sizes: dict[str, Size], layouts_dir: Path) -> list[str]:
    """Sizes whose geometry changed without a new layout version being written."""
    out = []
    for sid, size in sizes.items():
        try:
            current_layout(sheet, size, layouts_dir)
        except LayoutError:
            out.append(sid)
    return out


@dataclass
class RebuildRow:
    layout: Layout
    status: str        # "new", "unchanged", "differs"
    path: Path


def rebuild(sheet: Sheet, sizes: dict[str, Size], layouts_dir: Path) -> list[RebuildRow]:
    """Optimize every size. Writes a new version file only when no published layout has the
    current geometry hash; never rewrites a published file."""
    layouts_dir = Path(layouts_dir)
    layouts_dir.mkdir(parents=True, exist_ok=True)
    pub = published(layouts_dir)
    rows = []
    for sid, size in sizes.items():
        versions = pub.get(sid, [])
        h = geometry_hash(sheet, size)
        match = next((lay for lay in reversed(versions) if lay.geometry_hash == h), None)
        if match is not None:
            fresh = optimize(sheet, size, match.version)
            status = "unchanged" if fresh.same_cells(match, tol=1e-3) else "differs"
            rows.append(RebuildRow(match, status, layouts_dir / f"{match.layout_id}.json"))
            continue
        lay = optimize(sheet, size, (versions[-1].version + 1) if versions else 1)
        problems = check_layout(lay, size, sheet)
        if problems:
            raise LayoutError(f"Layout for '{sid}' breaks the sheet rules: " + "; ".join(problems[:5]))
        path = layouts_dir / f"{lay.layout_id}.json"
        path.write_text(lay.to_json(), encoding="utf-8")
        rows.append(RebuildRow(lay, "new", path))
    return rows
