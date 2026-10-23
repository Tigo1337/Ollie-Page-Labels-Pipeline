"""Fixed piece layouts (engine/layout.py): counts, translating / mirroring, keep-outs, gaps, frames, versions."""
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

# the minimum the optimizer must reach on the top third (reference/sheet-layout-plan.md)
PER_PIECE = {"pencil": 17, "small": 19, "medium": 8, "large": 6, "tag": 34, "round": 10, "shoe": 4}
ROWS = {"pencil": [2, 3, 3, 3, 3, 3], "small": [3, 4, 4, 4, 4], "medium": [2, 3, 3], "large": [6],
        "tag": [6, 7, 7, 7, 7], "round": [5, 5], "shoe": [4]}
ARRANGEMENT = {"pencil": "normal", "small": "normal", "medium": "normal", "large": "rotated", "tag": "normal",
               "round": "normal", "shoe": "rotated"}
# the half-sheet layouts (v1), for `pieces: 2`
PER_HALF_V1 = {"pencil": 30, "small": 31, "medium": 15, "large": 11, "tag": 55, "round": 20, "shoe": 8}


def lay(sid):
    return current_layout(SHEET, CAT.sizes[sid], LAYOUTS)


def with_marks(n):
    raw = json.loads(json.dumps(SHEET.raw))
    raw["registration"]["marks"] = n
    return Sheet.from_dict(raw)


def with_pieces(n):
    raw = json.loads(json.dumps(SHEET.raw))
    raw["trim"]["pieces"] = n
    return Sheet.from_dict(raw)


def test_trim_lines_are_computed_thirds():
    assert SHEET.pieces == 3
    assert SHEET.trims == [93.133, 186.267]
    assert "x" not in SHEET.raw["trim"]                       # never typed in
    assert with_pieces(2).trims == [139.7]
    assert with_pieces(4).trims == [69.85, 139.7, 209.55]
    with pytest.raises(ValueError):
        with_pieces(1)


@pytest.mark.parametrize("sid", list(PER_PIECE))
def test_counts_match_or_beat_the_plan(sid):
    L = lay(sid)
    assert L.layout_id == f"chels-{sid}-v2"
    assert L.n_pieces == 3
    assert L.per_piece >= PER_PIECE[sid]
    assert all(len(p) == L.per_piece for p in L.pieces)       # every piece holds the same count
    assert L.per_sheet == 3 * L.per_piece
    assert L.rows == ROWS[sid]
    assert L.arrangement == ARRANGEMENT[sid]


@pytest.mark.parametrize("sid", list(PER_PIECE))
def test_two_pieces_reproduce_the_v1_half_sheet_layouts(sid):
    """`pieces: 2` gives exactly today's half layouts (same cells as the published v1 files)."""
    v1 = Layout.load(LAYOUTS / f"chels-{sid}-v1.json")
    assert v1.n_pieces == 2 and v1.per_piece == PER_HALF_V1[sid]             # v1 files read as two pieces
    two = with_pieces(2)
    L = optimize(two, CAT.sizes[sid], 1)
    assert L.same_cells(v1, tol=1e-9)
    assert check_layout(v1, CAT.sizes[sid], two) == []


def test_round_v1_is_the_staggered_grid():
    L = Layout.load(LAYOUTS / "chels-round-v1.json")
    assert L.arrangement == "stagger"
    rows = {}
    for x, y, w, h in sorted(to_printed(*c[:4]) for c in L.pieces[0]):
        rows.setdefault(round(y, 3), []).append(x)
    ys = sorted(rows)
    pitch = ys[1] - ys[0]
    assert pitch == pytest.approx(30.9, abs=0.2)
    first, second = min(rows[ys[0]]), min(rows[ys[1]])
    assert first - second == pytest.approx(14.2, abs=0.5)         # next row shifted toward the left
    row_w = max(rows[ys[0]]) + 32 - first                          # top row centred on the page
    assert first + row_w / 2 == pytest.approx(SHEET.paper_h / 2, abs=1.0)


@pytest.mark.parametrize("sid", list(PER_PIECE))
def test_published_layout_matches_the_optimizer(sid):
    """The committed file is what the optimizer gives today (so the port is deterministic)."""
    L = lay(sid)
    assert optimize(SHEET, CAT.sizes[sid], L.version).same_cells(L, tol=1e-3)


@pytest.mark.parametrize("sid", list(PER_PIECE))
def test_middle_is_top_translated_and_bottom_is_top_mirrored(sid):
    L = lay(sid)
    top, middle, bottom = L.pieces
    assert len(top) == len(middle) == len(bottom)
    for a, m, b in zip(top, middle, bottom):
        pa, pm, pb = to_printed(*a[:4]), to_printed(*m[:4]), to_printed(*b[:4])
        # middle: printed y + 93.133, x unchanged
        assert pm[1] == pytest.approx(pa[1] + 93.133, abs=0.01)
        assert (pm[0], pm[2], pm[3]) == pytest.approx((pa[0], pa[2], pa[3]), abs=0.01)
        # bottom: printed y' = 279.4 − y − h, x unchanged
        assert pb[1] == pytest.approx(SHEET.paper_w - pa[1] - pa[3], abs=0.01)
        assert (pb[0], pb[2], pb[3]) == pytest.approx((pa[0], pa[2], pa[3]), abs=0.01)
        assert a[4] == m[4] == b[4]
        # Studio frame: middle is X − one piece, bottom mirrors about X = W / 2
        assert m[0] == pytest.approx(a[0] - SHEET.paper_w / 3, abs=0.01)
        assert b[0] == pytest.approx(SHEET.paper_w - a[0] - a[2], abs=0.01)


@pytest.mark.parametrize("sid", list(PER_PIECE))
def test_cuts_are_symmetric_top_to_bottom_in_studio(sid):
    """docs/studio-template-setup.md relies on this: SCM's dxf_to_studio3.py flips the selection vertically
    (Studio frame), which leaves every current layout unchanged."""
    from engine.layout import cell_labels
    L, size, H = lay(sid), CAT.sizes[sid], SHEET.paper_h
    cuts = sorted((round(x, 2), round(y, 2), round(w, 2), round(h, 2))
                  for c in L.cells for x, y, w, h in cell_labels(c, size, SHEET))
    flipped = sorted((x, round(H - y - h, 2), w, h) for x, y, w, h in cuts)
    assert all(a == pytest.approx(b, abs=0.02) for a, b in zip(cuts, flipped))


@pytest.mark.parametrize("sid", list(PER_PIECE))
def test_every_cell_lies_inside_its_own_piece(sid):
    L = lay(sid)
    for i, cells in enumerate(L.pieces):
        lo, hi = (SHEET.paper_w * (2 - i) / 3, SHEET.paper_w * (3 - i) / 3)   # printed top = Studio right
        for X, _, w, _, _ in cells:
            assert lo - 1e-6 <= X and X + w <= hi + 1e-6


@pytest.mark.parametrize("marks", [3, 4])
@pytest.mark.parametrize("sid", list(PER_PIECE))
def test_rules_hold_with_3_and_4_marks(sid, marks):
    sheet = with_marks(marks)
    L = lay(sid)
    assert check_layout(L, CAT.sizes[sid], sheet) == []


@pytest.mark.parametrize("sid", list(PER_PIECE))
def test_rules_independently(sid):
    """Re-check the main rules here with plain geometry, apart from check_layout."""
    L, size = lay(sid), CAT.sizes[sid]
    b, e, tm = SHEET.bleed, SHEET.edge_margin, SHEET.trim_margin
    W, H = SHEET.paper_w, SHEET.paper_h

    def overlaps(r, z):
        return r[0] < z[2] - 1e-6 and r[2] > z[0] + 1e-6 and r[1] < z[3] - 1e-6 and r[3] > z[1] + 1e-6

    for X, Y, w, h, _ in L.cells:
        assert e - 1e-6 <= X and X + w <= W - e + 1e-6 and e - 1e-6 <= Y and Y + h <= H - e + 1e-6
        for T in (W / 3, 2 * W / 3):
            assert X + w <= T - tm + 1e-3 or X >= T + tm - 1e-3           # nothing cut within 5 mm of a trim line
            assert not (X - b < T < X + w + b)                           # bleed never crosses a trim line
        assert X - b >= 0 and X + w + b <= W and Y - b >= 0 and Y + h + b <= H  # bleed stays on the page
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
    assert all(CAT.sizes[s].gap_on(SHEET) == 2.5 for s in PER_PIECE if s != "round")


def test_check_layout_catches_broken_layouts():
    size = CAT.sizes["small"]
    L = lay("small")
    top, mid, bot = L.pieces

    def with_pieces_(*p):
        return dataclasses.replace(L, pieces=list(p))
    bad = with_pieces_([(10.0, 10.0) + top[0][2:]] + top[1:], mid, bot)          # into the marked corner
    assert any("keep-out" in p for p in check_layout(bad, size, SHEET))
    bad = with_pieces_(top, mid, bot[:-1])
    assert any("different counts" in p for p in check_layout(bad, size, SHEET))
    X, Y, w, h, r = top[0]
    bad = with_pieces_(top, mid, [(bot[0][0], bot[0][1] + 0.5) + bot[0][2:]] + bot[1:])
    assert any("mirror" in p for p in check_layout(bad, size, SHEET))
    bad = with_pieces_(top, [(mid[0][0] + 0.5,) + mid[0][1:]] + mid[1:], bot)
    assert any("translated" in p for p in check_layout(bad, size, SHEET))
    # a cell up against the lower trim line (inside its 5 mm), on the middle piece
    T = SHEET.trims[0]
    bad = with_pieces_(top, [(T + 2.0, mid[0][1]) + mid[0][2:]] + mid[1:], bot)
    assert any("within 5 mm of the trim line at X 93.133" in p for p in check_layout(bad, size, SHEET))
    bad = with_pieces_(top, [(T - 20.0, mid[0][1]) + mid[0][2:]] + mid[1:], bot)
    assert any("outside its own piece" in p for p in check_layout(bad, size, SHEET))
    bad = with_pieces_(top, bot)
    assert any("2 pieces" in p for p in check_layout(bad, size, SHEET))
    rnd = lay("round")
    rt = rnd.pieces[0]
    X, Y, w, h, r = rt[1]
    near = (X, Y - 1.0, w, h, r)
    bad = dataclasses.replace(rnd, pieces=[[rt[0], near] + rt[2:]] + rnd.pieces[1:])
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
    # printed top piece = Studio right third
    top = lay("small").pieces[0]
    assert all(c[0] > SHEET.trims[-1] for c in top)


def test_keepouts_add_up():
    assert SHEET.ink_keepout == pytest.approx(SHEET.mark_inset + SHEET.mark_length + SHEET.mark_padding)
    assert SHEET.cut_keepout >= SHEET.notch


def test_layout_file_round_trip(tmp_path):
    L = lay("shoe")
    p = tmp_path / "x.json"
    p.write_text(L.to_json())
    assert Layout.load(p).same_cells(L, tol=0)
    d = json.loads(p.read_text())
    assert d["layout_id"] == "chels-shoe-v2" and d["frame"] == "studio"
    assert d["per_piece"] == 4 and d["per_sheet"] == 12 and len(d["pieces"]) == 3
    assert all(len(c) == 5 and isinstance(c[4], bool) for p in d["pieces"] for c in p)
    assert "top" not in d and "bottom" not in d


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
    assert all(r.status == "new" and r.layout.layout_id.endswith("-v3") for r in rows)
    for name, data in before.items():
        assert (d / name).read_bytes() == data
    assert current_layout(changed, CAT.sizes["small"], d).layout_id == "chels-small-v3"
    assert current_layout(SHEET, CAT.sizes["small"], d).layout_id == "chels-small-v2"


def test_cli_layouts_and_gallery(tmp_path, capsys):
    d = tmp_path / "layouts"
    shutil.copytree(LAYOUTS, d)
    assert main(["layouts", "--layouts", str(d)]) == 0
    out = capsys.readouterr().out
    assert "chels-round-v2" in out and "5 + 5" in out
    assert main(["layout-gallery", "--layouts", str(d), "--out", str(tmp_path / "g"), "--dpi", "60"]) == 0
    pngs = sorted(p.name for p in (tmp_path / "g").glob("*.png"))
    assert pngs == sorted(f"chels-{s}-v2.png" for s in CAT.sizes)
