"""The cut templates match the print PDF exactly.

For every layout: render a print page (each label filled with its own colour), rasterise it at
600 dpi, turn it back into the Studio frame (undoing /Rotate 270), then parse the layout's SVG
and DXF templates and check every cut path runs inside its *own* label's bleed band. Also:
cell counts, bounding boxes, the marks' positions, and that all files come from the same
layouts/*.json.
"""
import io
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import ezdxf
import numpy as np
import pypdfium2 as pdfium
import pytest
from PIL import Image

from engine.config import load_catalog
from engine.geometry import circle_points, px, rrect_points, shape_mask
from engine.layout import current_layout
from engine.sheetpdf import SheetPDF
from engine.templates import KINDS, file_name, template_bytes
from engine.workspace import REPO

from .test_alignment import outward_samples

DPI = 600
K = DPI / 25.4
CAT = load_catalog(REPO / "config")
SHEET = CAT.sheet
TEMPLATES = REPO / "templates"
FIXTURE = Path(__file__).parent / "fixtures" / "scm_letter_v6_marks.pdf"
SIZES = list(CAT.sizes)
SVG_NS = "{http://www.w3.org/2000/svg}"


def colour(i: int) -> tuple[int, int, int]:
    """A distinct, mid-tone colour per cut label (never white, grey or black)."""
    return 70 + 30 * (i % 6), 70 + 30 * ((i // 6) % 6), 70 + 20 * ((i // 36) % 7)


def label_images(size, layout):
    """One RGBA image per cell, label orientation, bleed shape masked by alpha; a pair's two
    labels get different colours (split down the middle of the gap)."""
    b = SHEET.bleed
    W, H = size.w + 2 * b, size.h + 2 * b
    mask = shape_mask(size, b, (W, H), (b, b), DPI)
    out, n = [], 0
    for _ in layout.cells:
        img = Image.new("RGBA", mask.size, colour(n) + (255,))
        if size.shape == "pair":
            split = px(b + size.pair["each_w"] + size.pair["gap"] / 2, DPI)
            img.paste(colour(n + 1) + (255,), (split, 0, img.width, img.height))
            n += 2
        else:
            n += 1
        img.putalpha(mask)
        out.append(img)
    return out


def studio_raster(pdf_bytes: bytes) -> np.ndarray:
    """Page 1 at 600 dpi as the viewer shows it (printed view), turned back into the Studio frame."""
    page = pdfium.PdfDocument(pdf_bytes)[0]
    printed = np.asarray(page.render(scale=DPI / 72).to_pil().convert("RGB"))
    return np.rot90(printed, k=-1)   # printed view -> Studio frame (90° clockwise)


def parse_svg(text: str):
    root = ET.fromstring(text)
    cut = root.find(f"{SVG_NS}g[@id='cut']")
    anchors = root.find(f"{SVG_NS}g[@id='anchors']")
    shapes = []
    for el in cut:
        tag = el.tag.replace(SVG_NS, "")
        f = {k: float(v) for k, v in el.attrib.items() if re.fullmatch(r"-?[\d.]+", v)}
        if tag == "circle":
            shapes.append(("circle", f["cx"] - f["r"], f["cy"] - f["r"], 2 * f["r"], 2 * f["r"], f["r"]))
        elif tag == "rect":
            assert f["rx"] == f["ry"]
            shapes.append(("rect", f["x"], f["y"], f["width"], f["height"], f["rx"]))
        elif tag == "path":
            d = el.attrib["d"]
            nums = [float(v) for v in re.findall(r"-?[\d.]+", d)]
            radii = {float(r) for r in re.findall(r"A(-?[\d.]+) ", d)}
            assert len(radii) == 1 and d.endswith("Z")
            # endpoints of M/H/V/A segments: the bbox of a rounded rect path is its endpoints' bbox
            xs, ys = _path_endpoints(d)
            shapes.append(("rect", min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys), radii.pop()))
            assert nums
        else:
            raise AssertionError(f"unexpected element {tag} in the cut group")
    return root, shapes, anchors


def _path_endpoints(d: str):
    xs, ys, x, y = [], [], 0.0, 0.0
    for cmd, args in re.findall(r"([MHVAZ])([^MHVAZ]*)", d):
        v = [float(a) for a in args.split()]
        if cmd == "M":
            x, y = v
        elif cmd == "H":
            x = v[0]
        elif cmd == "V":
            y = v[0]
        elif cmd == "A":
            x, y = v[5], v[6]
        else:
            continue
        xs.append(x)
        ys.append(y)
    return xs, ys


def outline(shape):
    kind, x, y, w, h, r = shape
    if kind == "circle":
        return circle_points(x + w / 2, y + h / 2, r, 96)
    return rrect_points(x, y, w, h, r, 12)


def own_band(size) -> float:
    """How far a label's own art reaches past its cut line toward a neighbour: the bleed, or half
    the gap where the gap is narrower than two bleeds (round: 2.0 mm gap -> 1.0 mm each)."""
    return min(SHEET.bleed, size.gap_on(SHEET) / 2)


def assert_in_own_bleed(img: np.ndarray, path, rgb, what: str, band: float):
    H, W = img.shape[:2]

    def at(p):
        x, y = int(round(p[0] * K)), int(round(p[1] * K))
        return img[min(max(y, 0), H - 1), min(max(x, 0), W - 1)].astype(int)

    want = np.array(rgb)
    for d in (-0.5, 0.0, 0.5, band - 0.2):   # inside, on the cut line, and well inside its own bleed
        bad = [p for p in outward_samples(path, d) if np.abs(at(p) - want).max() > 10]
        assert not bad, f"{what}: cut line +{d} mm is not on its own label's art at {bad[:3]}"
    bad = [p for p in outward_samples(path, 1.6) if np.abs(at(p) - want).max() <= 10]
    assert not bad, f"{what}: its art reaches 1.6 mm past the cut line at {bad[:3]}"


@pytest.fixture(scope="module", params=SIZES)
def case(request, tmp_path_factory):
    size = CAT.sizes[request.param]
    lay = current_layout(SHEET, size, REPO / "layouts")
    buf = io.BytesIO()
    pdf = SheetPDF(buf, SHEET, keywords=f"layout_id={lay.layout_id}; geometry_hash={lay.geometry_hash}")
    pdf.marks()
    pdf.trim()
    pdf.art(lay, label_images(size, lay), size)
    pdf.header(f"sheet: 1 · template: {lay.layout_id}")
    pdf.end_page()
    pdf.save()
    return size, lay, buf.getvalue(), studio_raster(buf.getvalue())


def test_pdf_page_is_landscape_rotated_and_unscaled(case):
    _, _, data, _ = case
    page = pdfium.PdfDocument(data)[0]
    assert tuple(round(v, 2) for v in page.get_mediabox()) == (0, 0, 792, 612)
    assert page.get_rotation() == 270
    assert b"/PrintScaling /None" in data


def test_svg_cuts_fall_in_their_own_bleed(case):
    size, lay, _, img = case
    _, shapes, _ = parse_svg((TEMPLATES / file_name(lay.layout_id, "svg")).read_text())
    n_labels = lay.per_sheet * (2 if size.shape == "pair" else 1)
    assert len(shapes) == n_labels
    for i, s in enumerate(shapes):
        assert_in_own_bleed(img, outline(s), colour(i), f"{lay.layout_id} SVG shape {i}", own_band(size))


def test_dxf_cuts_fall_in_their_own_bleed(case):
    size, lay, _, img = case
    doc = ezdxf.readfile(TEMPLATES / file_name(lay.layout_id, "dxf"))
    assert doc.dxfversion == "AC1009"
    ents = list(doc.modelspace())
    assert all(e.dxftype() == "POLYLINE" and e.is_closed for e in ents)
    cut = [e for e in ents if e.dxf.layer == "CUT"]
    anchors = [e for e in ents if e.dxf.layer == "ANCHOR"]
    assert len(cut) == lay.per_sheet * (2 if size.shape == "pair" else 1)
    for i, e in enumerate(cut):
        path = [(v.dxf.location.x, SHEET.paper_h - v.dxf.location.y) for v in e.vertices]
        assert_in_own_bleed(img, path, colour(i), f"{lay.layout_id} DXF polyline {i}", own_band(size))
        # flattened arcs: every vertex on the true outline, chords within 0.1 mm of it
        for (x0, y0), (x1, y1) in zip(path, path[1:] + path[:1]):
            assert math.hypot(x1 - x0, y1 - y0) <= 2 * math.sqrt(2 * size.r * 0.1) + 1e-6 or (
                abs(x1 - x0) < 1e-6 or abs(y1 - y0) < 1e-6)
    boxes = sorted((min(v.dxf.location.x for v in e.vertices), SHEET.paper_h - max(v.dxf.location.y for v in e.vertices))
                   for e in anchors)
    assert len(anchors) == 2 and boxes[0] == pytest.approx((0, 0), abs=1e-6)
    assert max(v.dxf.location.x for v in anchors[-1].vertices) == pytest.approx(SHEET.paper_w)


def test_bounding_boxes_match_the_json(case):
    size, lay, _, _ = case
    info = __import__("json").loads((TEMPLATES / file_name(lay.layout_id, "json")).read_text())
    bb = info["cut_bbox"]
    root, shapes, anchors = parse_svg((TEMPLATES / file_name(lay.layout_id, "svg")).read_text())
    sx0 = min(s[1] for s in shapes); sy0 = min(s[2] for s in shapes)
    sx1 = max(s[1] + s[3] for s in shapes); sy1 = max(s[2] + s[4] for s in shapes)
    assert (sx0, sy0, sx1 - sx0, sy1 - sy0) == pytest.approx((bb["x"], bb["y"], bb["w"], bb["h"]), abs=0.01)
    doc = ezdxf.readfile(TEMPLATES / file_name(lay.layout_id, "dxf"))
    pts = [(v.dxf.location.x, SHEET.paper_h - v.dxf.location.y)
           for e in doc.modelspace() if e.dxf.layer == "CUT" for v in e.vertices]
    dx0 = min(p[0] for p in pts); dy0 = min(p[1] for p in pts)
    dx1 = max(p[0] for p in pts); dy1 = max(p[1] for p in pts)
    assert (dx0, dy0, dx1 - dx0, dy1 - dy0) == pytest.approx((bb["x"], bb["y"], bb["w"], bb["h"]), abs=0.01)
    # anchors make the whole selection exactly the page
    a = [(float(r.get("x")), float(r.get("y")), float(r.get("width")), float(r.get("height"))) for r in anchors]
    assert min(r[0] for r in a) == 0 and min(r[1] for r in a) == 0
    assert max(r[0] + r[2] for r in a) == pytest.approx(SHEET.paper_w)
    assert max(r[1] + r[3] for r in a) == pytest.approx(SHEET.paper_h)
    assert root.get("width") == "279.4mm" and root.get("height") == "215.9mm"
    assert root.get("viewBox") == "0 0 279.4 215.9"


def test_all_files_come_from_the_same_layout(case):
    size, lay, data, _ = case
    for kind in KINDS:
        committed = (TEMPLATES / file_name(lay.layout_id, kind)).read_bytes()
        assert committed == template_bytes(lay, size, SHEET, kind), \
            f"templates/{file_name(lay.layout_id, kind)} is out of date: run python -m engine templates"
    svg = (TEMPLATES / file_name(lay.layout_id, "svg")).read_text()
    dxf = (TEMPLATES / file_name(lay.layout_id, "dxf")).read_text()
    js = __import__("json").loads((TEMPLATES / file_name(lay.layout_id, "json")).read_text())
    cal = (TEMPLATES / file_name(lay.layout_id, "calibration.pdf")).read_bytes()
    for blob in (svg, dxf, data.decode("latin-1"), cal.decode("latin-1")):
        assert lay.layout_id in blob and lay.geometry_hash in blob
    assert js["layout_id"] == lay.layout_id and js["geometry_hash"] == lay.geometry_hash


def _ink_bbox(img, x0, y0, x1, y1):
    """Bounding box (mm) of black ink inside a Studio-frame window (mm)."""
    win = img[int(y0 * K):int(y1 * K), int(x0 * K):int(x1 * K)]
    ys, xs = np.nonzero(win.max(axis=2) < 60)   # label colours never go below 70
    if len(xs) == 0:
        return None
    return (x0 + xs.min() / K, y0 + ys.min() / K, x0 + (xs.max() + 1) / K, y0 + (ys.max() + 1) / K)


def expected_marks():
    """Ink boxes (Studio mm) from SCM's code: 5 mm square + 1 mm stroke; L arms from t/2 behind the
    corner point to `length` in front of it. Computed here from sheet.json, not from engine/marks.py."""
    i, L, t, W, H = SHEET.mark_inset, SHEET.mark_length, SHEET.mark_thickness, SHEET.paper_w, SHEET.paper_h
    return {
        "square": (i - t / 2, i - t / 2, i + 5 + t / 2, i + 5 + t / 2),
        "top-right L": (W - i - L, i - t / 2, W - i + t / 2, i + L),
        "bottom-left L": (i - t / 2, H - i - L, i + L, H - i + t / 2),
    }


WINDOWS = {"square": (0, 0, 30, 30), "top-right L": (249.4, 0, 279.4, 30), "bottom-left L": (0, 185.9, 30, 215.9)}


def test_marks_rasterize_where_scm_puts_them(case):
    _, _, _, img = case
    for name, want in expected_marks().items():
        got = _ink_bbox(img, *WINDOWS[name])
        assert got is not None, f"no {name} mark"
        assert got == pytest.approx(want, abs=0.2), f"{name}: {got} vs {want}"
    assert _ink_bbox(img, 249.4, 185.9, 279.4, 215.9) is None   # no 4th mark
    # nothing else inside the ink keep-outs; no art in the trim gutter's middle
    marks = expected_marks()
    for z in SHEET.corner_squares(SHEET.ink_keepout):
        win = img[int(z[1] * K):int(z[3] * K), int(z[0] * K):int(z[2] * K)].copy()
        for m in marks.values():
            a = (int((m[0] - 0.3 - z[0]) * K), int((m[1] - 0.3 - z[1]) * K))
            b = (int((m[2] + 0.3 - z[0]) * K), int((m[3] + 0.3 - z[1]) * K))
            win[max(a[1], 0):max(b[1], 0), max(a[0], 0):max(b[0], 0)] = 255
        assert win.min() > 200, f"ink inside the keep-out {z}"
    for T in SHEET.trims:
        gutter = img[int(12 * K):int((SHEET.paper_h - 12) * K), int((T - 3.5) * K):int((T + 3.5) * K)]
        coloured = (gutter.max(axis=2).astype(int) - gutter.min(axis=2)) > 15
        assert not coloured.any(), f"label art inside the trim gutter at X {T}"


def test_printed_view_has_the_square_bottom_left(case):
    _, _, data, _ = case
    printed = np.asarray(pdfium.PdfDocument(data)[0].render(scale=100 / 72).to_pil().convert("L"))
    h, w = printed.shape
    k = 100 / 25.4
    # printed view: square at bottom-left, L at top-left and bottom-right, top-right empty
    def ink(x0, y0, x1, y1):
        return (printed[int(y0 * k):int(y1 * k), int(x0 * k):int(x1 * k)] < 80).any()
    assert ink(5, 279.4 - 20, 20, 279.4 - 5)          # square, bottom-left
    assert ink(5, 5, 25, 25)                          # ┌ top-left
    assert ink(215.9 - 25, 279.4 - 25, 215.9 - 5, 279.4 - 5)  # ┘ bottom-right
    assert not ink(215.9 - 25, 5, 215.9 - 5, 25)      # top-right: no mark
    assert (w, h) == (round(215.9 * k), round(279.4 * k))


# Windows that hold only the marks: clear of SCM's card art (it starts ~1 mm from the marks) and of
# our labels (inside our 21.5 mm ink keep-outs). Studio mm (x0, y0, x1, y1).
FIXTURE_WINDOWS = {"square": (5, 5, 20, 17), "top-right L": (258, 5, 279.4, 17.5),
                   "bottom-left L": (5, 198, 21, 211)}


@pytest.fixture(scope="module")
def scm():
    if not FIXTURE.exists():
        pytest.skip("SCM fixture tests/fixtures/scm_letter_v6_marks.pdf missing")
    data = FIXTURE.read_bytes()
    page = pdfium.PdfDocument(data)[0]
    assert tuple(round(v, 2) for v in page.get_mediabox()) == (0, 0, 792, 612) and page.get_rotation() == 270
    return data, studio_raster(data)


def test_marks_match_the_scm_fixture(case, scm):
    """Same square and L corner points as SCM's proxy PDF, within 0.2 mm (arm length is the only
    allowed difference: ours 10 mm, SCM v6 8.04 mm)."""
    _, _, _, ours = case
    _, theirs = scm
    sq_ours, sq_theirs = _ink_bbox(ours, *FIXTURE_WINDOWS["square"]), _ink_bbox(theirs, *FIXTURE_WINDOWS["square"])
    assert sq_ours == pytest.approx(sq_theirs, abs=0.2)
    # L marks: compare the outer corner (the end that does not depend on the arm length)
    o, t = _ink_bbox(ours, *FIXTURE_WINDOWS["top-right L"]), _ink_bbox(theirs, *FIXTURE_WINDOWS["top-right L"])
    assert (o[2], o[1]) == pytest.approx((t[2], t[1]), abs=0.2)
    o, t = _ink_bbox(ours, *FIXTURE_WINDOWS["bottom-left L"]), _ink_bbox(theirs, *FIXTURE_WINDOWS["bottom-left L"])
    assert (o[0], o[3]) == pytest.approx((t[0], t[3]), abs=0.2)
    # and SCM's arms really are shorter: the only difference allowed
    o, t = _ink_bbox(ours, *FIXTURE_WINDOWS["top-right L"]), _ink_bbox(theirs, *FIXTURE_WINDOWS["top-right L"])
    assert o[0] < t[0] - 1.5


def test_scm_fixture_prints_with_the_square_bottom_left(scm):
    data, _ = scm
    printed = np.asarray(pdfium.PdfDocument(data)[0].render(scale=100 / 72).to_pil().convert("L"))
    k = 100 / 25.4

    def ink(x0, y0, x1, y1):
        return (printed[int(y0 * k):int(y1 * k), int(x0 * k):int(x1 * k)] < 60).any()
    assert ink(8, 279.4 - 17, 17, 279.4 - 8)                    # square, bottom-left
    assert ink(8, 8, 12, 18)                                    # L, top-left (vertical arm)
    assert ink(215.9 - 12, 279.4 - 18, 215.9 - 8, 279.4 - 8)    # L, bottom-right (vertical arm)
    assert not ink(215.9 - 18, 3, 215.9 - 3, 9)                 # top-right: no mark
