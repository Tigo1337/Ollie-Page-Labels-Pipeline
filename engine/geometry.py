"""Shapes, cut paths and unit conversion. All geometry is in millimetres, y down."""
from __future__ import annotations

import math

from PIL import Image, ImageDraw

from .config import Size

MM_PER_INCH = 25.4
PT_PER_MM = 72.0 / MM_PER_INCH

Point = tuple[float, float]


def mm_to_px(mm: float, dpi: int) -> float:
    return mm * dpi / MM_PER_INCH


def px(mm: float, dpi: int) -> int:
    return int(round(mm_to_px(mm, dpi)))


def rrect_points(x: float, y: float, w: float, h: float, r: float, seg: int = 12) -> list[Point]:
    """Closed rounded rectangle (last point not repeated), clockwise on screen."""
    r = max(0.0, min(r, w / 2, h / 2))
    if r == 0:
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    pts: list[Point] = []
    # corner centres and start angles (screen coords, y down; angle 0 = +x, 90 = +y)
    corners = [
        (x + w - r, y + r, 270.0),   # top-right, from top edge going to right edge
        (x + w - r, y + h - r, 0.0),  # bottom-right
        (x + r, y + h - r, 90.0),     # bottom-left
        (x + r, y + r, 180.0),        # top-left
    ]
    for cx, cy, a0 in corners:
        for i in range(seg + 1):
            a = math.radians(a0 + 90.0 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def circle_points(cx: float, cy: float, radius: float, seg: int = 96) -> list[Point]:
    return [(cx + radius * math.cos(2 * math.pi * i / seg), cy + radius * math.sin(2 * math.pi * i / seg))
            for i in range(seg)]


def cut_path(size: Size, x: float, y: float, rrect_seg: int = 12, circle_seg: int = 96) -> list[Point]:
    """Cut path for a label whose cut bounding box has its top-left corner at (x, y)."""
    if size.shape == "circle":
        return circle_points(x + size.w / 2, y + size.h / 2, size.w / 2, circle_seg)
    return rrect_points(x, y, size.w, size.h, size.r, rrect_seg)


def offset_shape(size: Size, d: float) -> tuple[float, float, float]:
    """(w, h, r) of the label shape grown outwards by d mm (negative shrinks)."""
    if size.shape == "circle":
        return size.w + 2 * d, size.h + 2 * d, size.w / 2 + d
    return size.w + 2 * d, size.h + 2 * d, max(0.0, size.r + d)


def point_in_shape(size: Size, px_: float, py: float, inset: float = 0.0) -> bool:
    """Is (px, py) — label coords, origin at cut-box top-left — inside the shape inset by `inset` mm?"""
    if size.shape == "circle":
        R = size.w / 2 - inset
        return math.hypot(px_ - size.w / 2, py - size.h / 2) <= R + 1e-9
    w, h, r = size.w - 2 * inset, size.h - 2 * inset, max(0.0, size.r - inset)
    x, y = px_ - inset, py - inset
    if x < -1e-9 or y < -1e-9 or x > w + 1e-9 or y > h + 1e-9:
        return False
    # distance to the nearest corner centre when inside a corner square
    cx = min(max(x, r), w - r)
    cy = min(max(y, r), h - r)
    return math.hypot(x - cx, y - cy) <= r + 1e-9


def rect_in_shape(size: Size, rect: tuple[float, float, float, float], inset: float) -> bool:
    """Shapes are convex, so a rectangle is inside when its four corners are."""
    x0, y0, x1, y1 = rect
    return all(point_in_shape(size, a, b, inset) for a, b in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))


def shape_mask(size: Size, grow: float, canvas_mm: tuple[float, float], origin_mm: tuple[float, float],
               dpi: int, supersample: int = 1) -> Image.Image:
    """'L' mask of the label shape grown by `grow` mm, drawn on a canvas.

    `origin_mm` is where the cut box's top-left sits on the canvas.
    """
    s = supersample
    W, H = px(canvas_mm[0], dpi), px(canvas_mm[1], dpi)
    m = Image.new("L", (W * s, H * s), 0)
    d = ImageDraw.Draw(m)
    w, h, r = offset_shape(size, grow)
    x0 = origin_mm[0] - grow
    y0 = origin_mm[1] - grow
    k = dpi * s / MM_PER_INCH
    box = [x0 * k, y0 * k, (x0 + w) * k - 1, (y0 + h) * k - 1]
    if size.shape == "circle":
        d.ellipse(box, fill=255)
    else:
        d.rounded_rectangle(box, radius=r * k, fill=255)
    if s > 1:
        m = m.resize((W, H), Image.Resampling.LANCZOS)
    return m


def bbox(points: list[Point]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)
