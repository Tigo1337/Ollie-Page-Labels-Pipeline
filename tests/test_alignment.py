"""The print PDF and the DXF line up: rasterise the PDF, draw the cut paths from the
DXF, and check every cut line falls inside the bleed of its label."""
import math

import numpy as np
import pypdfium2 as pdfium
import pytest

from engine.cutfiles import parse_dxf_polylines
from engine.orders import Order, OrderLine

DPI = 600


def outward_samples(path, d):
    """Points offset by d mm along the outward normal of each vertex (polygon is convex)."""
    cx = sum(p[0] for p in path) / len(path)
    cy = sum(p[1] for p in path) / len(path)
    out = []
    n = len(path)
    for i, (x, y) in enumerate(path):
        (x0, y0), (x1, y1) = path[i - 1], path[(i + 1) % n]
        tx, ty = x1 - x0, y1 - y0
        L = math.hypot(tx, ty)
        nx, ny = ty / L, -tx / L
        if (x - cx) * nx + (y - cy) * ny < 0:
            nx, ny = -nx, -ny
        out.append((x + nx * d, y + ny * d))
        # midpoint of the next edge too, so straight edges are covered
        mx, my = (x + x1) / 2, (y + y1) / 2
        out.append((mx + nx * d, my + ny * d))
    return out


@pytest.fixture(scope="module")
def produced(ws, tmp_path_factory):
    out = tmp_path_factory.mktemp("align")
    lines = [OrderLine("solid", "school", "matte", "Léo", "", 1),
             OrderLine("solid", "square12", "matte", "Zoë", "", 1)]
    res = ws.producer.run([Order("align", lines)], out, customer_proofs=False)
    return res, out


def test_pdf_and_dxf_line_up(ws, produced):
    res, out = produced
    prod = ws.catalog.production
    pdf = pdfium.PdfDocument(str(out / "align_matte_print.pdf"))
    assert len(pdf) == len(res.sheets["matte"])
    k = DPI / 25.4
    checked = 0
    for i, page in enumerate(pdf):
        w_pt, h_pt = page.get_size()
        assert w_pt == pytest.approx(prod.page_w / 25.4 * 72, abs=0.01)
        assert h_pt == pytest.approx(prod.page_h / 25.4 * 72, abs=0.01)
        img = np.asarray(page.render(scale=DPI / 72).to_pil().convert("RGB")).astype(int)
        ink = img.min(axis=2) < 200
        H, W = ink.shape

        def at(pt):
            x, y = int(round(pt[0] * k)), int(round(pt[1] * k))
            return ink[min(max(y, 0), H - 1), min(max(x, 0), W - 1)]

        dxf = (out / f"align_matte_p{i + 1}_cut.dxf").read_text()
        paths = [[(x, prod.page_h - y) for x, y in p] for p in parse_dxf_polylines(dxf)]
        assert len(paths) == len(res.sheets["matte"][i].placements)
        for path in paths:
            for d in (0.0, 0.5, 1.0):      # on the cut line and well inside the 1.25 mm bleed
                bad = [p for p in outward_samples(path, d) if not at(p)]
                assert not bad, f"cut line +{d} mm not on ink at {bad[:3]}"
            # just past the bleed (and before any neighbour's bleed) the paper is white
            bad = [p for p in outward_samples(path, 1.5) if at(p)]
            assert not bad, f"ink found 1.5 mm outside the cut line at {bad[:3]}"
            checked += 1
        # nothing printed in the margins or the keep-out squares
        m = int(prod.margin * k) - 1
        assert not ink[:m].any() and not ink[-m:].any() and not ink[:, :m].any() and not ink[:, -m:].any()
        for x0, y0, x1, y1 in prod.keepout_rects():
            assert not ink[int(y0 * k):int(y1 * k) - 1, int(x0 * k):int(x1 * k) - 1].any()
    assert checked == 132 + 12


def test_info_sheet_xy_is_cut_bbox(ws, produced):
    res, out = produced
    prod = ws.catalog.production
    for p in res.pages:
        paths = parse_dxf_polylines((out / p.dxf).read_text())
        xs = [x for path in paths for x, _ in path]
        ys = [prod.page_h - y for path in paths for _, y in path]
        assert min(xs) == pytest.approx(p.x, abs=1e-3) and min(ys) == pytest.approx(p.y, abs=1e-3)
        assert max(xs) - min(xs) == pytest.approx(p.w, abs=1e-3)
        assert max(ys) - min(ys) == pytest.approx(p.h, abs=1e-3)
        txt = (out / "align_info_sheet.txt").read_text()
        assert f"{p.x:8.2f}" in txt and f"{p.y:8.2f}" in txt
