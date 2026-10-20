"""Cut templates: one set per layout, made once and reused for every order of that size.

For each layout (layouts/<layout_id>.json):
  <layout_id>.svg               main cut file: true shapes (<circle>, <rect rx ry>, one <path> per
                                shoe label) in the Studio frame, 0.1 mm red hairline, plus two
                                0.01 mm anchor dots at the page corners
  <layout_id>.dxf               fallback for Silhouette Studio Basic (no SVG import): R12, mm,
                                closed POLYLINEs on layer CUT (arcs flattened), anchors on ANCHOR
  <layout_id>.json              cut-group bounding box (anchors excluded) for placing by hand
  <layout_id>_calibration.pdf   marks + every cut outline as a grey hairline, no art

The anchors make the selection exactly the page (0, 0)–(279.4, 215.9): select all, place at
X 0 / Y 0 in Transformer, and every cut lands where the print PDF put its label.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .config import Sheet, Size
from .cutfiles import dxf_r12_layers
from .geometry import Point
from .layout import Layout, cell_labels
from .sheetpdf import SheetPDF

CHORD_TOL = 0.01      # mm: flattened arcs stay within this of the true arc (spec: ≤ 0.1)
ANCHOR = 0.01         # mm: anchor dot side
SVG_STROKE = 0.1      # mm
KINDS = ("svg", "dxf", "json", "calibration.pdf")


@dataclass(frozen=True)
class CutShape:
    kind: str            # "circle" | "rect" | "pair-label"
    x: float             # bounding box, Studio frame (mm)
    y: float
    w: float
    h: float
    r: float             # corner radius (circle: radius)


def cut_shapes(layout: Layout, size: Size, sheet: Sheet) -> list[CutShape]:
    """Every cut label of the layout, in cell order (a pair gives two)."""
    kind = {"circle": "circle", "pair": "pair-label"}.get(size.shape, "rect")
    r = size.w / 2 if size.shape == "circle" else size.r
    return [CutShape(kind, X, Y, w, h, r) for cell in layout.cells for X, Y, w, h in cell_labels(cell, size, sheet)]


def anchor_rects(sheet: Sheet) -> list[tuple[float, float, float, float]]:
    """(x, y, w, h) of the two anchor dots, inside the page so the selection is exactly the page."""
    W, H = sheet.paper_w, sheet.paper_h
    return [(0.0, 0.0, ANCHOR, ANCHOR), (W - ANCHOR, H - ANCHOR, ANCHOR, ANCHOR)]


def cut_bbox(shapes: list[CutShape]) -> tuple[float, float, float, float]:
    x0 = min(s.x for s in shapes)
    y0 = min(s.y for s in shapes)
    x1 = max(s.x + s.w for s in shapes)
    y1 = max(s.y + s.h for s in shapes)
    return round(x0, 3), round(y0, 3), round(x1 - x0, 3), round(y1 - y0, 3)


def _n(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------
def rrect_path_d(x: float, y: float, w: float, h: float, r: float) -> str:
    """Rounded rectangle as a path with true arcs, clockwise on screen (y down)."""
    n = _n
    return (f"M{n(x + r)} {n(y)} H{n(x + w - r)} A{n(r)} {n(r)} 0 0 1 {n(x + w)} {n(y + r)} "
            f"V{n(y + h - r)} A{n(r)} {n(r)} 0 0 1 {n(x + w - r)} {n(y + h)} "
            f"H{n(x + r)} A{n(r)} {n(r)} 0 0 1 {n(x)} {n(y + h - r)} "
            f"V{n(y + r)} A{n(r)} {n(r)} 0 0 1 {n(x + r)} {n(y)} Z")


def svg_text(layout: Layout, size: Size, sheet: Sheet) -> str:
    W, H, n = sheet.paper_w, sheet.paper_h, _n
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<!-- {layout.layout_id} · geometry {layout.geometry_hash} · Studio frame (landscape Letter), mm, y down. "
        "Select all, place at X 0 / Y 0, then delete the two anchor dots. -->",
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{n(W)}mm" height="{n(H)}mm" viewBox="0 0 {n(W)} {n(H)}" '
        f'data-layout-id="{layout.layout_id}" data-geometry-hash="{layout.geometry_hash}">',
        f'<g id="cut" fill="none" stroke="#FF0000" stroke-width="{n(SVG_STROKE)}">',
    ]
    for s in cut_shapes(layout, size, sheet):
        if s.kind == "circle":
            out.append(f'<circle cx="{n(s.x + s.w / 2)}" cy="{n(s.y + s.h / 2)}" r="{n(s.r)}"/>')
        elif s.kind == "rect":
            out.append(f'<rect x="{n(s.x)}" y="{n(s.y)}" width="{n(s.w)}" height="{n(s.h)}" '
                       f'rx="{n(s.r)}" ry="{n(s.r)}"/>')
        else:
            out.append(f'<path d="{rrect_path_d(s.x, s.y, s.w, s.h, s.r)}"/>')
    out.append("</g>")
    out.append('<g id="anchors" fill="#000000" stroke="none">')
    for x, y, w, h in anchor_rects(sheet):
        out.append(f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}"/>')
    out += ["</g>", "</svg>"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# DXF
# ---------------------------------------------------------------------------
def arc_segments(r: float, sweep: float, tol: float = CHORD_TOL) -> int:
    """Segments for an arc of radius r and `sweep` radians so the chord error is ≤ tol."""
    if r <= tol:
        return 1
    return max(1, math.ceil(sweep / (2 * math.acos(1 - tol / r))))


def flatten(s: CutShape, tol: float = CHORD_TOL) -> list[Point]:
    """Closed polygon (vertices on the true outline, last point not repeated), clockwise on screen."""
    if s.kind == "circle":
        n = 4 * arc_segments(s.r, math.pi / 2, tol)          # a multiple of 4: the extremes are vertices
        cx, cy = s.x + s.w / 2, s.y + s.h / 2
        return [(cx + s.r * math.cos(2 * math.pi * i / n), cy + s.r * math.sin(2 * math.pi * i / n))
                for i in range(n)]
    r = max(0.0, min(s.r, s.w / 2, s.h / 2))
    if r == 0:
        return [(s.x, s.y), (s.x + s.w, s.y), (s.x + s.w, s.y + s.h), (s.x, s.y + s.h)]
    seg = arc_segments(r, math.pi / 2, tol)
    pts: list[Point] = []
    for cx, cy, a0 in ((s.x + s.w - r, s.y + r, 270.0), (s.x + s.w - r, s.y + s.h - r, 0.0),
                       (s.x + r, s.y + s.h - r, 90.0), (s.x + r, s.y + r, 180.0)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90.0 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def dxf_text(layout: Layout, size: Size, sheet: Sheet, anchors: bool = True) -> str:
    layers = {"CUT": [flatten(s) for s in cut_shapes(layout, size, sheet)]}
    if anchors:
        layers["ANCHOR"] = [[(x, y), (x + w, y), (x + w, y + h), (x, y + h)] for x, y, w, h in anchor_rects(sheet)]
    return dxf_r12_layers(layers, sheet.paper_w, sheet.paper_h,
                          comments=[f"{layout.layout_id} geometry {layout.geometry_hash}",
                                    "Studio frame, landscape Letter, mm. Layer ANCHOR: delete after placing at X 0 / Y 0."])


# ---------------------------------------------------------------------------
# JSON + calibration PDF
# ---------------------------------------------------------------------------
def info(layout: Layout, size: Size, sheet: Sheet) -> dict:
    shapes = cut_shapes(layout, size, sheet)
    x, y, w, h = cut_bbox(shapes)
    return {
        "layout_id": layout.layout_id, "size": layout.size, "geometry_hash": layout.geometry_hash,
        "cells": layout.per_sheet, "cut_labels": len(shapes),
        "page": {"w": sheet.paper_w, "h": sheet.paper_h, "orientation": "landscape"},
        "cut_bbox": {"x": x, "y": y, "w": w, "h": h},
        "anchors": [[0.0, 0.0], [sheet.paper_w, sheet.paper_h]],
        "registration": {"type": 1, "marks": sheet.marks, "length": sheet.mark_length,
                         "thickness": sheet.mark_thickness, "inset": sheet.mark_inset},
        "files": {k: file_name(layout.layout_id, k) for k in KINDS},
    }


def json_text(layout: Layout, size: Size, sheet: Sheet) -> str:
    return json.dumps(info(layout, size, sheet), indent=1, ensure_ascii=False) + "\n"


def calibration_pdf(layout: Layout, size: Size, sheet: Sheet, path):
    """Marks + every cell's cut outline as a 0.2 mm grey hairline, no art. Cut it on plain paper
    with the layout's template: every cut should land on its hairline."""
    pdf = SheetPDF(path, sheet, title=f"Calibration {layout.layout_id}",
                   keywords=f"layout_id={layout.layout_id}; geometry_hash={layout.geometry_hash}", invariant=True)
    pdf.marks()
    pdf.outlines(layout, size)
    pdf.header(f"calibration · template: {layout.layout_id}")
    pdf.end_page()
    pdf.save()


def file_name(layout_id: str, kind: str) -> str:
    return f"{layout_id}_calibration.pdf" if kind == "calibration.pdf" else f"{layout_id}.{kind}"


def write_templates(layout: Layout, size: Size, sheet: Sheet, out_dir: Path) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {k: out_dir / file_name(layout.layout_id, k) for k in KINDS}
    files["svg"].write_text(svg_text(layout, size, sheet), encoding="utf-8")
    files["dxf"].write_text(dxf_text(layout, size, sheet), encoding="ascii")
    files["json"].write_text(json_text(layout, size, sheet), encoding="utf-8")
    calibration_pdf(layout, size, sheet, files["calibration.pdf"])
    return files


def template_bytes(layout: Layout, size: Size, sheet: Sheet, kind: str) -> bytes:
    """One template file, made in memory (the app serves these)."""
    if kind == "svg":
        return svg_text(layout, size, sheet).encode()
    if kind == "dxf":
        return dxf_text(layout, size, sheet).encode("ascii")
    if kind == "json":
        return json_text(layout, size, sheet).encode()
    if kind == "calibration.pdf":
        import io
        buf = io.BytesIO()
        calibration_pdf(layout, size, sheet, buf)
        return buf.getvalue()
    raise ValueError(f"Unknown template file '{kind}'.")
