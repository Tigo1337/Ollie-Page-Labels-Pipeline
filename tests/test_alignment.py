"""A real run's print PDFs line up with the layout templates in its bundle: rasterise every page
in the Studio frame, draw the template's cut paths, and check every cut line falls inside the
printed art of its label. The only ink in the corner keep-outs is the registration marks."""
import io
import math
import zipfile

import numpy as np
import pypdfium2 as pdfium
import pytest

from engine.orders import Order, OrderLine

DPI = 300
K = DPI / 25.4


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
    lines = [OrderLine("solid", p, "matte", "Léo", "", 1) for p in ("school", "large18", "daycare")]
    res = ws.producer.run([Order("align", lines)], out, customer_proofs=False)
    return res, out


def studio_pages(path):
    for page in pdfium.PdfDocument(str(path)):
        printed = np.asarray(page.render(scale=DPI / 72).to_pil().convert("RGB")).astype(int)
        yield np.rot90(printed, k=-1)          # printed view -> Studio frame


def test_every_sheet_is_cut_on_its_art(ws, produced):
    from engine.layout import published
    from engine.templates import cut_shapes, flatten
    res, out = produced
    sheet = ws.catalog.sheet
    lays = {lay.layout_id: lay for v in published(ws.producer.layouts_dir).values() for lay in v}
    band = {sid: min(sheet.bleed, s.gap_on(sheet) / 2) for sid, s in ws.catalog.sizes.items()}
    checked = 0
    with zipfile.ZipFile(res.zip_path) as z:
        bundle = set(z.namelist())
    for pdf in sorted({sh["pdf"] for sh in res.summary["sheets"]}):
        sheets = [sh for sh in res.summary["sheets"] if sh["pdf"] == pdf]
        for sh, img in zip(sheets, studio_pages(out / pdf)):
            lay = lays[sh["layout_id"]]
            size = ws.catalog.sizes[lay.size]
            assert f"templates/{lay.layout_id}.svg" in bundle
            ink = img.min(axis=2) < 200
            H, W = ink.shape

            def at(p):
                x, y = int(round(p[0] * K)), int(round(p[1] * K))
                return ink[min(max(y, 0), H - 1), min(max(x, 0), W - 1)]

            for shape in cut_shapes(lay, size, sheet):
                path = flatten(shape, tol=0.05)
                for d in (-0.4, 0.0, 0.4, band[lay.size] - 0.3):
                    bad = [p for p in outward_samples(path, d) if not at(p)]
                    assert not bad, f"{pdf} sheet {sh['n']}: cut line +{d} mm off the art at {bad[:3]}"
                checked += 1
            # nothing but the marks inside the corner ink keep-outs
            for x0, y0, x1, y1 in sheet.corner_squares(sheet.ink_keepout):
                win = ink[int(y0 * K) + 1:int(y1 * K) - 1, int(x0 * K) + 1:int(x1 * K) - 1].copy()
                mark = np.zeros_like(win)
                from engine.marks import mark_rects
                for m in mark_rects(sheet):
                    a0, b0 = int((m[0] - 0.4 - x0) * K), int((m[1] - 0.4 - y0) * K)
                    a1, b1 = int((m[2] + 0.4 - x0) * K) + 1, int((m[3] + 0.4 - y0) * K) + 1
                    mark[max(b0, 0):max(b1, 0), max(a0, 0):max(a1, 0)] = True
                assert not (win & ~mark).any(), f"ink inside the keep-out {x0, y0} on {pdf}"
    labels = sum(len(lay.cells) * (2 if ws.catalog.sizes[lay.size].shape == "pair" else 1)
                 for sh in res.summary["sheets"] for lay in [lays[sh["layout_id"]]])
    assert checked == labels


def test_pdf_pages_are_landscape_rotated_and_unscaled(produced):
    res, out = produced
    for f in {sh["pdf"] for sh in res.summary["sheets"]}:
        data = (out / f).read_bytes()
        for page in pdfium.PdfDocument(io.BytesIO(data)):
            assert tuple(round(v, 2) for v in page.get_mediabox()) == (0, 0, 792, 612)
            assert page.get_rotation() == 270
        assert b"/PrintScaling /None" in data
