import re

import ezdxf
import pytest

from engine.cutfiles import dxf_r12, parse_dxf_polylines, svg
from engine.geometry import cut_path
from engine.production import notch_paths


def test_dxf_is_r12_mm_closed_polylines_on_cut(ws, tmp_path):
    cat = ws.catalog
    paths = [cut_path(cat.sizes["medium"], 20, 30), cut_path(cat.sizes["round"], 100, 50)]
    p = tmp_path / "x.dxf"
    p.write_text(dxf_r12(paths, cat.production.page_h, cat.production.page_w))
    doc = ezdxf.readfile(p)
    assert doc.dxfversion == "AC1009"
    ents = list(doc.modelspace())
    assert len(ents) == 2
    assert all(e.dxftype() == "POLYLINE" and e.is_closed and e.dxf.layer == "CUT" for e in ents)
    assert len(list(ents[0].vertices)) == 4 * 13          # 12 segments per rounded corner
    assert len(list(ents[1].vertices)) == 96               # 96 per circle
    # y flipped: top edge of the medium label (y = 30) is at page_h - 30
    ys = [v.dxf.location.y for v in ents[0].vertices]
    assert max(ys) == pytest.approx(cat.production.page_h - 30)
    assert min(ys) == pytest.approx(cat.production.page_h - 30 - cat.sizes["medium"].h)
    assert parse_dxf_polylines(p.read_text())[0][0][0] == pytest.approx(paths[0][0][0])


def test_svg_paths_red_02mm_viewbox_in_mm(ws):
    cat = ws.catalog
    s = svg([cut_path(cat.sizes["pencil"], 15, 15)], cat.production.page_w, cat.production.page_h)
    assert 'viewBox="0 0 215.9 279.4"' in s and 'width="215.9mm"' in s
    assert 'stroke="#FF0000"' in s and 'stroke-width="0.2"' in s
    assert len(re.findall("<path ", s)) == 1


def test_notches_are_34mm_squares_at_three_mark_corners(ws):
    prod = ws.catalog.production
    sq = notch_paths(prod)
    assert len(sq) == 3
    for path in sq:
        xs, ys = [p[0] for p in path], [p[1] for p in path]
        assert max(xs) - min(xs) == pytest.approx(34) and max(ys) - min(ys) == pytest.approx(34)
    corners = {(min(p[0] for p in s) == 0, min(p[1] for p in s) == 0) for s in sq}
    assert corners == {(True, True), (False, True), (True, False)}


def test_calibration_sheet(ws, tmp_path):
    from engine.calibration import write_calibration
    info = write_calibration(ws.catalog.production, tmp_path)
    paths = parse_dxf_polylines((tmp_path / "calibration_cut.dxf").read_text())
    assert len(paths) == 6
    assert info["x"] == pytest.approx(14.0) and info["y"] == pytest.approx(14.0)
    assert (tmp_path / "calibration_print.pdf").stat().st_size > 0
