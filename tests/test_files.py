import re

import ezdxf
import pytest

from engine.cutfiles import dxf_r12, parse_dxf_polylines, svg
from engine.geometry import cut_path
from engine.production import laminate_outline


def test_dxf_is_r12_mm_closed_polylines_on_cut(ws, tmp_path):
    cat = ws.catalog
    paths = [cut_path(cat.sizes["medium"], 20, 30), cut_path(cat.sizes["round"], 100, 50)]
    p = tmp_path / "x.dxf"
    p.write_text(dxf_r12(paths, cat.sheet.paper_h, cat.sheet.paper_w))
    doc = ezdxf.readfile(p)
    assert doc.dxfversion == "AC1009"
    ents = list(doc.modelspace())
    assert len(ents) == 2
    assert all(e.dxftype() == "POLYLINE" and e.is_closed and e.dxf.layer == "CUT" for e in ents)
    assert len(list(ents[0].vertices)) == 4 * 13          # 12 segments per rounded corner
    assert len(list(ents[1].vertices)) == 96               # 96 per circle
    # y flipped: top edge of the medium label (y = 30) is at page_h - 30
    ys = [v.dxf.location.y for v in ents[0].vertices]
    assert max(ys) == pytest.approx(cat.sheet.paper_h - 30)
    assert min(ys) == pytest.approx(cat.sheet.paper_h - 30 - cat.sizes["medium"].h)
    assert parse_dxf_polylines(p.read_text())[0][0][0] == pytest.approx(paths[0][0][0])


def test_svg_paths_red_02mm_viewbox_in_mm(ws):
    cat = ws.catalog
    s = svg([cut_path(cat.sizes["pencil"], 15, 15)], cat.sheet.paper_w, cat.sheet.paper_h)
    assert 'viewBox="0 0 279.4 215.9"' in s and 'width="279.4mm"' in s
    assert 'stroke="#FF0000"' in s and 'stroke-width="0.2"' in s
    assert len(re.findall("<path ", s)) == 1


def test_laminate_outline_has_22mm_notches_at_the_mark_corners(ws):
    import dataclasses
    sheet = ws.catalog.sheet
    pts = laminate_outline(sheet)
    W, H = sheet.paper_w, sheet.paper_h
    assert pts == [(0, 22), (22, 22), (22, 0), (W - 22, 0), (W - 22, 22), (W, 22),
                   (W, H), (22, H), (22, H - 22), (0, H - 22)]
    four = laminate_outline(dataclasses.replace(sheet, marks=4))
    assert len(four) == 12 and (W - 22, H - 22) in four


def test_calibration_sheet(ws, tmp_path):
    from engine.calibration import write_calibration
    from engine.workspace import REPO
    p = write_calibration(ws.catalog, "chels-small-v2", tmp_path, REPO / "layouts")
    assert p.name == "chels-small-v2_calibration.pdf" and p.stat().st_size > 0
    with pytest.raises(ValueError, match="No layout"):
        write_calibration(ws.catalog, "chels-mini-v1", tmp_path, REPO / "layouts")
