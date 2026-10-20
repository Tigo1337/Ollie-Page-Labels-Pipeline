"""Max-density half-sheet layout (printed/portrait view). Bottom half = mirror of top half about the trim line.
Rows are placed at a fixed pitch; each row is centred independently inside the x-range left free by the
mark corners (ink zone for bleed, cut zone for cut lines). usage: python tools/sheet_opt.py sizes.json"""
import json, math, sys
PW, PH = 215.9, 279.4
INSET, LEN, THICK, PAD = 10.0, 10.0, 1.0, 1.5
INK_K = INSET + LEN + PAD          # 21.5: no ink (bleed) inside this corner square
NOTCH = 22.0                       # laminate notch square
CUT_K = NOTCH + 1.5                # 23.5: no cut line inside this corner square (laminate hand tolerance)
K = INK_K                          # for previews
EDGE, TRIM, GAP, BLEED = 10.0, 5.0, 2.5, 1.25
ROUND_GAP = 2.0                    # circles: 2.0 mm between cut lines (lets 4 staggered rows of 5 fit per half)
TOP = (EDGE, EDGE, PW - EDGE, PH / 2 - TRIM)

def corner_sq(k): return [(0, 0, k, k), (PW - k, 0, PW, k)]
CORNERS = corner_sq(INK_K)

def hit(r, z): return r[0] < z[2] and r[2] > z[0] and r[1] < z[3] and r[3] > z[1]

def ok(x, y, w, h):
    if any(hit((x - BLEED, y - BLEED, x + w + BLEED, y + h + BLEED), z) for z in corner_sq(INK_K)): return False
    if any(hit((x, y, x + w, y + h), z) for z in corner_sq(CUT_K)): return False
    return True

def corner_clear(cx, cy, rad, k, PHs=(0,)):
    """true-circle clearance (mm) from a circle to the 4 page-corner squares of side k (negative = intrudes)."""
    best = 1e9
    for qx in (cx, PW - cx):
        for qy in (cy, PH - cy):
            best = min(best, math.hypot(max(0.0, qx - k), max(0.0, qy - k)) - rad)
    return best

def round_ok(x, y, d):
    cx, cy, r = x + d / 2, y + d / 2, d / 2
    return corner_clear(cx, cy, r + BLEED, INK_K) >= 0 and corner_clear(cx, cy, r, CUT_K) >= 0

def round_stagger(d, n=5, rows=4):
    """circles: `rows` staggered rows of `n`, top row centred on the page (it sits between the two mark corners),
    the next row shifted by s. Picks the s / y / x that gives the most corner clearance. Returns cells or []."""
    x0, y0, x1, y1 = TOP
    P = d + ROUND_GAP; W = (n - 1) * P + d
    xc = (PW - W) / 2                                        # centred row
    best = None
    for s20 in range(0, int(P / 2 * 20) + 1):
      s = s20 / 20
      v = math.sqrt(max(0.0, P * P - s * s)) + 0.002       # + rounding margin
      if (rows - 1) * v + d > y1 - y0 + 1e-9: continue
      for k in range(-20, 21):                                # top row may sit up to 1 mm off centre
        xa = xc + k * 0.05
        for xb in (xa - s, xa + s):
            if xb < x0 - 1e-9 or xb + W > x1 + 1e-9: continue
            for y10 in range(0, int(((y1 - y0) - (rows - 1) * v - d) * 10) + 1):
                yt = y0 + y10 / 10
                cells = [(round((xa if r % 2 == 0 else xb) + i * P, 3), round(yt + r * v, 3)) for r in range(rows) for i in range(n)]
                cl = min(min(corner_clear(x + d/2, y + d/2, d/2 + BLEED, INK_K), corner_clear(x + d/2, y + d/2, d/2, CUT_K)) for x, y in cells)
                if cl >= 0 and (best is None or cl > best[0]): best = (cl, cells)
    return best[1] if best else []

def row_cells(w, h, y, stagger=0.0):
    """max cells in a row at height y; centred in the free x-interval (allowing a stagger offset for hex)."""
    x0, _, x1, _ = TOP
    lo, hi = x0, x1
    # shrink interval where this row meets a corner zone
    for k, pad in ((INK_K, BLEED), (CUT_K, 0.0)):
        if y - pad < k:                                   # row overlaps corner band vertically
            lo, hi = max(lo, k + pad), min(hi, PW - k - pad)
    n = math.floor((hi - lo + GAP) / (w + GAP))
    if n <= 0: return []
    gw = n * w + (n - 1) * GAP
    ox = lo + (hi - lo - gw) / 2
    return [(round(ox + i * (w + GAP), 3), round(y, 3)) for i in range(n) if ok(ox + i * (w + GAP), y, w, h)]

def layout(w, h, hexr, dy):
    _, y0, _, y1 = TOP
    py = (h + GAP) * (math.sqrt(3) / 2 if hexr else 1)
    if hexr: py = max(py, h + GAP - 0) if False else py
    rows = math.floor((y1 - y0 - h) / py) + 1
    gh = (rows - 1) * py + h
    oy = y0 + (y1 - y0 - gh) / 2 + dy
    cells = []
    prev = None
    for r in range(rows):
        y = oy + r * py
        if y < y0 - 1e-6 or y + h > y1 + 1e-6: continue
        rc = row_cells(w, h, y)
        if hexr and prev is not None:
            # hex: this row's centres must sit between previous row's centres (or be far enough vertically)
            rc = hex_fix(rc, prev, w, h, py)
        cells += rc; prev = rc
    return cells

def hex_fix(rc, prev, w, h, py):
    """for circles: ensure centre distance >= w+GAP to previous row; shift row by half pitch if needed."""
    def clear(row):
        return all(math.hypot((a[0]-b[0]), (a[1]-b[1])) >= w + GAP - 1e-6 for a in row for b in prev)
    if clear(rc): return rc
    for shift in (w/2 + GAP/2, -(w/2 + GAP/2)):
        cand = [(x + shift, y) for x, y in rc]
        cand = [c for c in cand if c[0] >= TOP[0] - 1e-6 and c[0] + w <= TOP[2] + 1e-6 and ok(c[0], c[1], w, h)]
        if clear(cand): return cand
    # drop to fewer cells, centred between
    return [c for c in rc if all(math.hypot(c[0]-b[0], c[1]-b[1]) >= w + GAP - 1e-6 for b in prev)]

def hex_grid(w, h, dx, dy):
    """classic hex grid: alternate rows offset by half a pitch, whole grid shifted by (dx, dy)."""
    x0, y0, x1, y1 = TOP; W, H = x1 - x0, y1 - y0
    px, py = w + GAP, (h + GAP) * math.sqrt(3) / 2
    cols = math.floor((W + GAP) / px); rows = math.floor((H - h) / py) + 1
    gw = cols * w + (cols - 1) * GAP + px / 2; gh = (rows - 1) * py + h
    ox, oy = x0 + (W - gw) / 2 + dx, y0 + (H - gh) / 2 + dy
    out = []
    for r in range(rows):
        for c in range(cols):
            x = ox + c * px + (px / 2 if r % 2 else 0); y = oy + r * py
            if x < x0 - 1e-6 or y < y0 - 1e-6 or x + w > x1 + 1e-6 or y + h > y1 + 1e-6: continue
            if ok(x, y, w, h): out.append((round(x, 3), round(y, 3)))
    return out

def best(size):
    w, h, shape = size["w"], size["h"], size.get("shape", "rect")
    cands = [("normal", w, h, False)]
    if w != h: cands.append(("rotated", h, w, False))
    if shape == "round": cands.append(("hex", w, h, True))
    res = None
    for name, cw, ch, hexr in cands:
        for i in range(0, 41):
            dy = -5 + i * 0.25
            cs = layout(cw, ch, hexr, dy)
            key = (len(cs), -abs(dy))
            if res is None or key > res[0]: res = (key, name, cw, ch, cs, dy)
    if shape == "round":
        for i in range(0, 61):
            for j in range(0, 41):
                dx, dy = -7.5 + i * 0.25, -5 + j * 0.25
                cs = hex_grid(w, h, dx, dy)
                key = (len(cs), -abs(dy))
                if key > res[0]: res = (key, "hex", w, h, cs, dy)
    if shape == "round":
        for n, rows in ((5, 4),):
            cs = round_stagger(w, n, rows)
            if len(cs) > res[0][0]: res = ((len(cs), 0), "stagger", w, h, cs, 0)
    _, name, cw, ch, cs, dy = res
    bottom = [(x, round(PH - y - ch, 3)) for x, y in cs]
    return {"arrangement": name, "cell_w": cw, "cell_h": ch, "per_half": len(cs), "per_sheet": 2 * len(cs), "top": cs, "bottom": bottom}

def validate(L, size):
    cw, ch = L["cell_w"], L["cell_h"]; cells = L["top"] + L["bottom"]
    zones_ink = corner_sq(INK_K) + [(0, PH - INK_K, INK_K, PH), (PW - INK_K, PH - INK_K, PW, PH)]
    zones_cut = corner_sq(CUT_K) + [(0, PH - CUT_K, CUT_K, PH), (PW - CUT_K, PH - CUT_K, PW, PH)]
    rnd = size.get("shape") == "round"
    for x, y in cells:
        if rnd:
            assert round_ok(x, y, cw), ("corner", x, y)
            assert x >= EDGE - 1e-6 and x + cw <= PW - EDGE + 1e-6 and y >= EDGE - 1e-6 and y + ch <= PH - EDGE + 1e-6
            assert y + ch <= PH/2 - TRIM + 1e-6 or y >= PH/2 + TRIM - 1e-6, ("trim", y)
            continue
        assert not any(hit((x-BLEED, y-BLEED, x+cw+BLEED, y+ch+BLEED), z) for z in zones_ink), ("ink", x, y)
        assert not any(hit((x, y, x+cw, y+ch), z) for z in zones_cut), ("cut", x, y)
        assert x >= EDGE - 1e-6 and x + cw <= PW - EDGE + 1e-6 and y >= EDGE - 1e-6 and y + ch <= PH - EDGE + 1e-6
        assert y + ch <= PH/2 - TRIM + 1e-6 or y >= PH/2 + TRIM - 1e-6, ("trim", y)
    for i, a in enumerate(cells):
        for b in cells[i+1:]:
            if size.get("shape") == "round":
                assert math.hypot(a[0]-b[0], a[1]-b[1]) >= cw + ROUND_GAP - 1e-6, ("round gap", a, b)
            else:
                sep = max(b[0] - (a[0]+cw), a[0] - (b[0]+cw), b[1] - (a[1]+ch), a[1] - (b[1]+ch))
                assert sep >= GAP - 1e-6, ("gap", a, b, sep)
    return True

if __name__ == "__main__":
    sizes = json.load(open(sys.argv[1]))["sizes"]
    out = {}
    for k, v in sizes.items():
        L = best(v); validate(L, v); out[k] = L
        rows = {}
        for x, y in L["top"]: rows[y] = rows.get(y, 0) + 1
        print(f"{k:8s} {v['w']}x{v['h']:<5} {L['arrangement']:8s} half {L['per_half']:3d}  sheet {L['per_sheet']:3d}  rows {list(rows.values())}")
    json.dump(out, open("out/sheet_layouts.json", "w"), indent=1)
