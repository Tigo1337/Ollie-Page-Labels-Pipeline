"""Fixed half-sheet layouts (engine/layout.py): counts, mirroring, keep-outs, gaps, frames, versions."""
import dataclasses
import json
import math
import shutil

import pytest

from engine.cli import main
from engine.config import Sheet, geometry_hash, load_catalog
from engine.frames import to_printed, to_studio
from engine.layout import (Layout, LayoutError, check_layout, current_layout, optimize, published, rebuild,
                           stale_sizes)
from engine.workspace import REPO

CAT = load_catalog(REPO / "config")
SHEET = CAT.sheet
LAYOUTS = REPO / "layouts"

# the minimum the optimizer must reach (reference/sheet-layout-plan.md)
PER_HALF = {"pencil": 30, "small": 31, "medium": 15, "large": 11, "tag": 55, "round": 20, "shoe": 8}
ROWS = {"pencil": [14, 16], "small": [3] + [4] * 7, "medium": [3] * 5, "large": [2, 3, 3, 3],
        "tag": [6] + [7] * 7, "round": [5] * 4, "shoe": [2, 3, 3]}


def lay(sid):
    return current_layout(SHEET, CAT.sizes[sid], LAYOUTS)


def with_marks(n):
    raw = json.loads(json.dumps(SHEET.raw))
    raw["registration"]["marks"] = n
    return Sheet.from_dict(raw)


@pytest.mark.parametrize("sid", list(PER_HALF))
def test_counts_match_or_beat_the_plan(sid):
    L = lay(sid)
    assert L.per_half >= PER_HALF[sid]
    assert L.per_sheet == 2 * L.per_half
    assert L.rows == ROWS[sid]


def test_round_is_the_staggered_grid():
    L = lay("round")
    assert L.arrangement == "stagger"
    rows = {}
    for x, y, w, h in sorted(to_printed(*c[:4]) for c in L.top):
        rows.setdefault(round(y, 3), []).append(x)
    ys = sorted(rows)
    pitch = ys[1] - ys[0]
    assert pitch == pytest.approx(30.9, abs=0.2)
    first, second = min(rows[ys[0]]), min(rows[ys[1]])
    assert first - second == pytest.approx(14.2, abs=0.5)         # next row shifted toward the left
    row_w = max(rows[ys[0]]) + 32 - first                          # top row centred on the page
    assert first + row_w / 2 == pytest.approx(SHEET.paper_h / 2, abs=1.0)


@pytest.mark.parametrize("sid", list(PER_HALF))
def test_published_layout_matches_the_optimizer(sid):
    """The committed file is what the optimizer gives today (so the port is deterministic)."""
    L = lay(sid)
    assert optimize(SHEET, CAT.sizes[sid], L.version).same_cells(L, tol=1e-3)


@pytest.mark.parametrize("sid", list(PER_HALF))
def test_bottom_half_mirrors_top_half(sid):
    L = lay(sid)
    assert len(L.top) == len(L.bottom)
    T = SHEET.trim_x
    for a, b in zip(L.top, L.bottom):
        assert b[0] == pytest.approx(2 * T - a[0] - a[2], abs=0.01)  # Studio: mirror about X = trim
        assert b[1:4] == pytest.approx(a[1:4], abs=0.01)
        assert b[4] == a[4]
        # printed view: y_bottom = 279.4 − y_top − h, x unchanged
        pa, pb = to_printed(*a[:4]), to_printed(*b[:4])
        assert pb[1] == pytest.approx(SHEET.paper_w - pa[1] - pa[3], abs=0.01)
        assert pb[0] == pytest.approx(pa[0], abs=0.01)


@pytest.mark.parametrize("marks", [3, 4])
@pytest.mark.parametrize("sid", list(PER_HALF))
def test_rules_hold_with_3_and_4_marks(sid, marks):
    sheet = with_marks(marks)
    L = lay(sid)
    assert check_layout(L, CAT.sizes[sid], sheet) == []


@pytest.mark.parametrize("sid", list(PER_HALF))
def test_rules_independently(sid):
    """Re-check the main rules here with plain geometry, apart from check_layout."""
    L, size = lay(sid), CAT.sizes[sid]
    b, e, T, tm = SHEET.bleed, SHEET.edge_margin, SHEET.trim_x, SHEET.trim_margin
    W, H = SHEET.paper_w, SHEET.paper_h

    def overlaps(r, z):
        return r[0] < z[2] - 1e-6 and r[2] > z[0] + 1e-6 and r[1] < z[3] - 1e-6 and r[3] > z[1] + 1e-6

    for X, Y, w, h, _ in L.cells:
        assert e - 1e-6 <= X and X + w <= W - e + 1e-6 and e - 1e-6 <= Y and Y + h <= H - e + 1e-6
        assert X + w <= T - tm + 1e-6 or X >= T + tm - 1e-6               # nothing cut in the trim gutter
        assert X - b >= 0 and X + w + b <= W and Y - b >= 0 and Y + h + b <= H  # bleed stays on the page
        assert not (X - b < T < X + w + b)                               # bleed never crosses the trim line
        if size.shape == "circle":
            cx, cy, r = X + w / 2, Y + h / 2, w / 2
            for k, rad in ((SHEET.ink_keepout, r + b), (SHEET.cut_keepout, r)):
                for qx in (cx, W - cx):
                    for qy in (cy, H - cy):
                        assert math.hypot(max(0, qx - k), max(0, qy - k)) >= rad - 1e-6
        else:
            for z in SHEET.corner_squares(SHEET.ink_keepout):
                assert not overlaps((X - b, Y - b, X + w + b, Y + h + b), z)
            for z in SHEET.corner_squares(SHEET.cut_keepout):
                assert not overlaps((X, Y, X + w, Y + h), z)
    gap = size.gap_on(SHEET)
    cells = L.cells
    for i, a in enumerate(cells):
        for c in cells[i + 1:]:
            if size.shape == "circle":
                d = math.hypot(a[0] - c[0], a[1] - c[1])
                assert d >= a[2] + gap - 1e-6                            # centre distance >= Ø + 2.0
            else:
                sep = max(c[0] - (a[0] + a[2]), a[0] - (c[0] + c[2]), c[1] - (a[1] + a[3]), a[1] - (c[1] + c[3]))
                assert sep >= gap - 1e-6


def test_round_gap_is_2mm_and_others_use_the_sheet_gap():
    assert CAT.sizes["round"].gap_on(SHEET) == 2.0
    assert all(CAT.sizes[s].gap_on(SHEET) == 2.5 for s in PER_HALF if s != "round")


def test_check_layout_catches_broken_layouts():
    size = CAT.sizes["small"]
    L = lay("small")
    bad = dataclasses.replace(L, top=[(10.0, 10.0) + L.top[0][2:]] + L.top[1:])   # into the marked corner
    assert any("keep-out" in p for p in check_layout(bad, size, SHEET))
    bad = dataclasses.replace(L, bottom=L.bottom[:-1])
    assert any("different counts" in p for p in check_layout(bad, size, SHEET))
    X, Y, w, h, r = L.top[0]
    bad = dataclasses.replace(L, top=[(X, Y + 0.5, w, h, r)] + L.top[1:])
    assert any("mirror" in p for p in check_layout(bad, size, SHEET))
    rnd = lay("round")
    X, Y, w, h, r = rnd.top[1]
    near = (X, Y - 1.0, w, h, r)
    bad = dataclasses.replace(rnd, top=[rnd.top[0], near] + rnd.top[2:])
    assert any("circles closer" in p for p in check_layout(bad, CAT.sizes["round"], SHEET))


def test_frames_round_trip_and_mark_corners():
    for p in [(0, 0), (12.5, 200.0), (215.9, 279.4)]:
        assert to_printed(*to_studio(*p)) == pytest.approx(p)
    r = (20.0, 30.0, 57.0, 9.5)
    assert to_printed(*to_studio(*r)) == pytest.approx(r)
    assert to_studio(*r) == pytest.approx((279.4 - 30 - 9.5, 20.0, 9.5, 57.0))
    # Studio marks: square TL, L at TR, L at BL -> printed: square BL, L TL, L BR
    W, H = SHEET.paper_w, SHEET.paper_h
    def printed_corner(X, Y):
        x, y = to_printed(X, Y)
        return ("top" if y < H / 2 else "bottom") + "-" + ("left" if x < W / 2 * H / W else "right")
    assert printed_corner(12.5, 12.5) == "bottom-left"       # square
    assert printed_corner(W - 10, 10) == "top-left"           # L (┌)
    assert printed_corner(10, H - 10) == "bottom-right"       # L (┘)
    assert printed_corner(W - 10, H - 10) == "top-right"      # no mark
    # printed top half = Studio right half
    top = lay("small").top
    assert all(c[0] > SHEET.trim_x for c in top)


def test_keepouts_add_up():
    assert SHEET.ink_keepout == pytest.approx(SHEET.mark_inset + SHEET.mark_length + SHEET.mark_padding)
    assert SHEET.cut_keepout >= SHEET.notch


def test_layout_file_round_trip(tmp_path):
    L = lay("shoe")
    p = tmp_path / "x.json"
    p.write_text(L.to_json())
    assert Layout.load(p).same_cells(L, tol=0)
    d = json.loads(p.read_text())
    assert d["layout_id"] == "chels-shoe-v1" and d["frame"] == "studio"
    assert all(len(c) == 5 and isinstance(c[4], bool) for c in d["top"] + d["bottom"])


def test_every_size_has_a_current_layout():
    assert stale_sizes(SHEET, CAT.sizes, LAYOUTS) == []
    assert {lay.size for v in published(LAYOUTS).values() for lay in v} >= set(CAT.sizes)


def test_hash_check_fails_when_sheet_changes_without_a_new_version(tmp_path):
    raw = json.loads(json.dumps(SHEET.raw))
    raw["gap"] = 2.6
    changed = Sheet.from_dict(raw)
    assert geometry_hash(changed, CAT.sizes["small"]) != geometry_hash(SHEET, CAT.sizes["small"])
    # round keeps its own 2.0 gap, but the whole sheet.json feeds the hash, so it is stale too
    assert stale_sizes(changed, CAT.sizes, LAYOUTS) == list(CAT.sizes)
    with pytest.raises(LayoutError):
        current_layout(changed, CAT.sizes["small"], LAYOUTS)
    # a size change only affects that size
    sizes = dict(CAT.sizes, small=dataclasses.replace(CAT.sizes["small"], w=45.0))
    assert stale_sizes(SHEET, sizes, LAYOUTS) == ["small"]
    # renaming a size is not a geometry change
    sizes = dict(CAT.sizes, small=dataclasses.replace(CAT.sizes["small"], label="Petites"))
    assert stale_sizes(SHEET, sizes, LAYOUTS) == []


def test_rebuild_writes_a_new_version_and_never_touches_published_files(tmp_path):
    d = tmp_path / "layouts"
    shutil.copytree(LAYOUTS, d)
    before = {p.name: p.read_bytes() for p in d.iterdir()}
    rows = rebuild(SHEET, CAT.sizes, d)
    assert all(r.status == "unchanged" for r in rows)
    assert {p.name: p.read_bytes() for p in d.iterdir()} == before
    raw = json.loads(json.dumps(SHEET.raw))
    raw["edge_margin"] = 10.5
    changed = Sheet.from_dict(raw)
    rows = rebuild(changed, CAT.sizes, d)
    assert all(r.status == "new" and r.layout.layout_id.endswith("-v2") for r in rows)
    for name, data in before.items():
        assert (d / name).read_bytes() == data
    assert current_layout(changed, CAT.sizes["small"], d).layout_id == "chels-small-v2"
    assert current_layout(SHEET, CAT.sizes["small"], d).layout_id == "chels-small-v1"


def test_cli_layouts_and_gallery(tmp_path, capsys):
    d = tmp_path / "layouts"
    shutil.copytree(LAYOUTS, d)
    assert main(["layouts", "--layouts", str(d)]) == 0
    out = capsys.readouterr().out
    assert "chels-round-v1" in out and "stagger" in out
    assert main(["layout-gallery", "--layouts", str(d), "--out", str(tmp_path / "g"), "--dpi", "60"]) == 0
    pngs = sorted(p.name for p in (tmp_path / "g").glob("*.png"))
    assert pngs == sorted(f"chels-{s}-v1.png" for s in CAT.sizes)
