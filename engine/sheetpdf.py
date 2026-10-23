"""PDF pages in the Studio frame, like SCM's proxy PDFs.

Every page is landscape Letter (792 × 612 pt) with /Rotate 270, so it opens and prints in
portrait (the printed view) while all geometry stays in the Studio frame (see frames.py).
The document asks viewers not to scale when printing (/ViewerPreferences /PrintScaling /None).

Label art is given in the label's own orientation (as the renderer makes it: cut size plus
bleed, name reading left to right). On the page it is turned into the Studio frame:
  * a normal cell: the label reads normally on the printed sheet, so the image is turned
    90° clockwise into the Studio frame;
  * a rotated cell (`rotated` in the layout, e.g. pencil labels standing upright): the label
    is turned 90° counter-clockwise on the printed sheet (name reads bottom to top), which
    is exactly the Studio frame orientation, so the image goes in as is.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from .config import Sheet, Size
from .geometry import PT_PER_MM as PT
from .layout import Layout, cell_labels
from .marks import mark_rects

HEADER_END = (181.0, 212.0)  # header baseline end (Studio mm): bottom margin, right-aligned so it ends
                             # before the upper trim line (X 186.267) and its tick. Calibration sheets only:
                             # the print sheets carry no text (only marks, art and trim marks)


def studio_image(img: Image.Image, rotated: bool) -> Image.Image:
    """A label-orientation image turned into the Studio frame."""
    return img if rotated else img.transpose(Image.Transpose.ROTATE_270)  # ROTATE_270 = 90° clockwise


class SheetPDF:
    def __init__(self, path, sheet: Sheet, title: str = "", keywords: str = "", invariant: bool = False):
        """`path`: a file path or a binary file object."""
        self.sheet = sheet
        self.H = sheet.paper_h
        # ReportLab writes MediaBox [0 0 h w] for pages rotated 90/270 (content untouched), so pass
        # the size swapped to get MediaBox [0 0 792 612] with /Rotate 270, like SCM.
        w, h = sheet.paper_w * PT, sheet.paper_h * PT
        size = (h, w) if sheet.pdf_rotate % 180 else (w, h)
        self.c = rl_canvas.Canvas(str(path) if isinstance(path, (str, Path)) else path, pagesize=size,
                                  invariant=int(invariant), pageCompression=1)
        if title:
            self.c.setTitle(title)
        if keywords:
            self.c.setKeywords(keywords)
        self.c.setViewerPreference("PrintScaling", "None")
        self._readers: dict[tuple[int, bool], ImageReader] = {}

    # -- primitives (Studio mm, y down) --------------------------------------
    def _rect(self, x0: float, y0: float, x1: float, y1: float, fill: int = 1, stroke: int = 0) -> None:
        self.c.rect(x0 * PT, (self.H - y1) * PT, (x1 - x0) * PT, (y1 - y0) * PT, fill=fill, stroke=stroke)

    def _line(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self.c.line(x0 * PT, (self.H - y0) * PT, x1 * PT, (self.H - y1) * PT)

    # -- page furniture --------------------------------------------------------
    def marks(self) -> None:
        self.c.setFillColorRGB(0, 0, 0)
        for r in mark_rects(self.sheet):
            self._rect(*r)

    def trim(self) -> None:
        """Black ticks at both edges and a light dashed guide along every trim line."""
        s, c = self.sheet, self.c
        c.saveState()
        for T in s.trims:
            c.setStrokeColorRGB(0, 0, 0)
            c.setLineWidth(0.6)
            c.setDash()
            self._line(T, 0, T, s.trim_ticks)
            self._line(T, s.paper_h - s.trim_ticks, T, s.paper_h)
            if s.trim_guide:
                c.setStrokeColorRGB(0.6, 0.6, 0.65)
                c.setLineWidth(0.3)
                c.setDash(3, 3)
                self._line(T, s.edge_margin - 2, T, s.paper_h - s.edge_margin + 2)
        c.restoreState()

    def header(self, text: str, font: str = "Helvetica") -> None:
        c = self.c
        c.saveState()
        c.setFillColorRGB(0.4, 0.4, 0.45)
        c.setFont(font, 7)
        c.drawRightString(HEADER_END[0] * PT, (self.H - HEADER_END[1]) * PT, text)
        c.restoreState()

    # -- cells -----------------------------------------------------------------
    def art(self, layout: Layout, images: list[Image.Image | None], size: Size) -> None:
        """Place each cell's art (label orientation, cut size + bleed) at its cell, true size.

        RGBA images keep their alpha (a circle's bleed is a circle). Where neighbouring bleeds
        would overlap (round labels: 2.0 mm gap < 2 × 1.25 mm bleed), each cell's art is also
        clipped at the midline between the two cut lines, so each label owns half the gap
        instead of the last one drawn covering its neighbour's bleed."""
        b = self.sheet.bleed
        split = size.shape == "circle" and size.gap_on(self.sheet) < 2 * b
        for i, ((X, Y, w, h, rot), img) in enumerate(zip(layout.cells, images)):
            if img is None:
                continue
            key = (id(img), rot)
            rd = self._readers.get(key)
            if rd is None:
                rd = self._readers[key] = ImageReader(studio_image(img, rot))
            if split:
                self.c.saveState()
                self._clip(_voronoi_cell(i, layout.cells, b))
            self.c.drawImage(rd, (X - b) * PT, (self.H - (Y + h + b)) * PT, width=(w + 2 * b) * PT,
                             height=(h + 2 * b) * PT, mask="auto" if img.mode == "RGBA" else None)
            if split:
                self.c.restoreState()

    def _clip(self, poly: list[tuple[float, float]]) -> None:
        path = self.c.beginPath()
        path.moveTo(poly[0][0] * PT, (self.H - poly[0][1]) * PT)
        for x, y in poly[1:]:
            path.lineTo(x * PT, (self.H - y) * PT)
        path.close()
        self.c.clipPath(path, stroke=0, fill=0)

    def outlines(self, layout: Layout, size: Size, rgb=(0.55, 0.55, 0.55), width_mm: float = 0.2) -> None:
        """Every label's cut outline as a hairline (calibration sheets)."""
        c = self.c
        c.saveState()
        c.setStrokeColorRGB(*rgb)
        c.setLineWidth(width_mm * PT)
        for cell in layout.cells:
            for X, Y, w, h in cell_labels(cell, size, self.sheet):
                if size.shape == "circle":
                    c.circle((X + w / 2) * PT, (self.H - Y - h / 2) * PT, w / 2 * PT, stroke=1, fill=0)
                else:
                    c.roundRect(X * PT, (self.H - Y - h) * PT, w * PT, h * PT, size.r * PT, stroke=1, fill=0)
        c.restoreState()

    def end_page(self) -> None:
        self.c.setPageRotation(self.sheet.pdf_rotate)
        self.c.showPage()

    def save(self) -> None:
        self.c.save()


def _voronoi_cell(i: int, cells, b: float) -> list[tuple[float, float]]:
    """Cell i's bleed box cut by the perpendicular bisector to every neighbour whose bleed box
    overlaps it (cells are equal shapes, so the bisector is the midline of the gap)."""
    X, Y, w, h, _ = cells[i]
    cx, cy = X + w / 2, Y + h / 2
    poly = [(X - b, Y - b), (X + w + b, Y - b), (X + w + b, Y + h + b), (X - b, Y + h + b)]
    for j, (X2, Y2, w2, h2, _) in enumerate(cells):
        if j == i or X2 - b >= X + w + b or X - b >= X2 + w2 + b or Y2 - b >= Y + h + b or Y - b >= Y2 + h2 + b:
            continue
        nx, ny = X2 + w2 / 2 - cx, Y2 + h2 / 2 - cy          # keep points closer to our centre
        mx, my = cx + nx / 2, cy + ny / 2
        poly = _clip_half_plane(poly, lambda x, y: (x - mx) * nx + (y - my) * ny)
    return poly


def _clip_half_plane(poly, f):
    """Sutherland–Hodgman: keep the part of a convex polygon where f(x, y) <= 0."""
    out = []
    for k in range(len(poly)):
        p, q = poly[k], poly[(k + 1) % len(poly)]
        fp, fq = f(*p), f(*q)
        if fp <= 0:
            out.append(p)
        if (fp < 0 < fq) or (fq < 0 < fp):
            t = fp / (fp - fq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return out
