"""Layout gallery: one preview PNG per layout, in the printed view (portrait, as the sheet is held).

Shows the cut lines (red) over their bleed (pink), the corner ink keep-outs hatched with the
cut keep-out outlined, the laminate notches (blue), the marks, the trim line with its gutter
and ticks, and the counts. Drawn in the Studio frame, then turned to the printed view
(the same 90° turn as the PDF's /Rotate 270).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import Sheet, Size
from .frames import to_printed
from .geometry import mm_to_px
from .layout import Layout, cell_labels
from .marks import mark_rects, notch_corners

RED = (220, 0, 0)
PINK = (255, 214, 222)
BLUE = (0, 90, 255)
GREY = (150, 150, 150)
LIGHT = (205, 205, 205)


class _Fonts:
    """The UI font if given, else DejaVu Sans, else Pillow's built-in font (ASCII only)."""

    def __init__(self, path: Path | None):
        self.path: str | None = None
        for cand in ([str(path)] if path else []) + ["DejaVuSans.ttf"]:
            try:
                ImageFont.truetype(cand, 10)
            except OSError:
                continue
            self.path = cand
            break
        self.ascii_only = self.path is None

    def get(self, size: int) -> ImageFont.ImageFont:
        return ImageFont.truetype(self.path, size) if self.path else ImageFont.load_default(size=size)

    def text(self, s: str) -> str:
        return s.replace("×", "x").replace("Ø", "dia.").replace("·", "-") if self.ascii_only else s


def _hatch(d: ImageDraw.ImageDraw, box: tuple[float, float, float, float], step: float) -> None:
    x0, y0, x1, y1 = box
    d.rectangle(box, fill=(228, 228, 228))
    w, h = x1 - x0, y1 - y0
    t = -h
    while t < w:                                   # 45° lines clipped to the box
        a0, b0 = max(0.0, t), max(0.0, -t)
        a1 = min(w, t + h)
        d.line([(x0 + a0, y0 + b0), (x0 + a1, y0 + a1 - t)], fill=(160, 160, 160), width=1)
        t += step


def _dashed(d: ImageDraw.ImageDraw, p0, p1, dash: float, fill, width: int = 1) -> None:
    (x0, y0), (x1, y1) = p0, p1
    n = max(1, int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 // dash))
    for i in range(0, n, 2):
        a, b = i / n, min(1.0, (i + 1) / n)
        d.line([(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a), (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)],
               fill=fill, width=width)


def render_layout(layout: Layout, size: Size, sheet: Sheet, dpi: int = 150,
                  font_path: Path | None = None) -> Image.Image:
    k = mm_to_px(1, dpi)
    PW, PH = sheet.paper_w, sheet.paper_h
    img = Image.new("RGB", (int(round(PW * k)), int(round(PH * k))), "white")
    d = ImageDraw.Draw(img)

    def box(x0, y0, x1, y1):
        return (x0 * k, y0 * k, x1 * k, y1 * k)

    # trim gutter and edge margin
    T, tm, e = sheet.trim_x, sheet.trim_margin, sheet.edge_margin
    d.rectangle(box(T - tm, 0, T + tm, PH), fill=(246, 246, 248))
    corners = [(e, e), (PW - e, e), (PW - e, PH - e), (e, PH - e)]
    for a, b_ in zip(corners, corners[1:] + corners[:1]):
        _dashed(d, (a[0] * k, a[1] * k), (b_[0] * k, b_[1] * k), 2 * k, LIGHT)
    # keep-outs (ink hatched, cut outlined), laminate notches, marks
    for z in sheet.corner_squares(sheet.ink_keepout):
        _hatch(d, box(*z), 2.5 * k)
    for z in sheet.corner_squares(sheet.cut_keepout):
        d.rectangle(box(*z), outline=GREY, width=1)
    for z in notch_corners(sheet):
        d.rectangle(box(*z), outline=BLUE, width=2)
    for r in mark_rects(sheet):
        d.rectangle(box(*r), fill=(0, 0, 0))
    # trim line: dashed guide + ticks
    _dashed(d, (T * k, 8 * k), (T * k, (PH - 8) * k), 3 * k, GREY, 1)
    d.line([(T * k, 0), (T * k, sheet.trim_ticks * k)], fill=(0, 0, 0), width=2)
    d.line([(T * k, (PH - sheet.trim_ticks) * k), (T * k, PH * k)], fill=(0, 0, 0), width=2)

    b = sheet.bleed
    for pass_ in ("bleed", "cut"):                  # all bleed first, so no cut line gets painted over
        for cell in layout.cells:
            for sx, sy, sw, sh in cell_labels(cell, size, sheet):
                if pass_ == "bleed":
                    bx = box(sx - b, sy - b, sx + sw + b, sy + sh + b)
                    if size.shape == "circle":
                        d.ellipse(bx, fill=PINK)
                    else:
                        d.rounded_rectangle(bx, radius=(size.r + b) * k, fill=PINK)
                elif size.shape == "circle":
                    d.ellipse(box(sx, sy, sx + sw, sy + sh), outline=RED, width=2)
                else:
                    d.rounded_rectangle(box(sx, sy, sx + sw, sy + sh), radius=size.r * k, outline=RED, width=2)

    img = img.transpose(Image.Transpose.ROTATE_90)   # Studio frame -> printed view

    # header and notes, in the printed view
    head = int(26 * k)
    out = Image.new("RGB", (img.width, img.height + head), "white")
    out.paste(img, (0, head))
    d = ImageDraw.Draw(out)
    d.rectangle([0, head, img.width - 1, out.height - 1], outline=(60, 60, 60), width=1)
    fonts = _Fonts(font_path)
    f1, f2, f3 = fonts.get(int(5.2 * k)), fonts.get(int(3.4 * k)), fonts.get(int(2.6 * k))
    unit = " pairs" if size.shape == "pair" else ""
    lines = [(layout.layout_id, f1, (0, 0, 0), 3),
             (f"{size.label} · {size.dims_label} · {layout.arrangement}", f2, (40, 40, 40), 11),
             (f"{layout.per_half}{unit} per half · {layout.per_sheet}{unit} per sheet · rows "
              + " + ".join(str(r) for r in layout.rows), f2, (40, 40, 40), 17)]
    for txt, f, col, y in lines:
        d.text((4 * k, y * k), fonts.text(txt), font=f, fill=col)
    trim_y = head + (PW - T) * k
    for txt, dy in ((f"TOP HALF ({layout.per_half}{unit})", -4.0),
                    (f"BOTTOM HALF ({layout.per_half}{unit})", 1.2)):
        tw = d.textlength(txt, font=f3)
        d.text(((img.width - tw) / 2, trim_y + dy * k), txt, font=f3, fill=(110, 110, 110))
    if size.shape == "pair":                       # gauche / droite, as the shoes sit side by side
        f = fonts.get(int(4 * k))
        for cell in layout.cells:
            parts = sorted(to_printed(*r, studio_w=PW) for r in cell_labels(cell, size, sheet))  # type: ignore[misc]
            for (x, y, w, h), letter in zip(parts, "GD"):
                tw = d.textlength(letter, font=f)
                d.text(((x + w / 2) * k - tw / 2, head + (y + h / 2 - 2.5) * k), letter, font=f,
                       fill=(170, 60, 80))
    return out


def write_gallery(layouts: list[tuple[Layout, Size]], sheet: Sheet, out_dir: Path, dpi: int = 150,
                  font_path: Path | None = None) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for lay, size in layouts:
        p = out_dir / f"{lay.layout_id}.png"
        render_layout(lay, size, sheet, dpi, font_path).save(p)
        paths.append(p)
    return paths
