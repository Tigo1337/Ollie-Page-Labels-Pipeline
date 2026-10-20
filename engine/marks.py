"""Silhouette Type 1 registration marks, drawn exactly like SCM's proxy PDFs.

Port of `page_manager.generate_reg_mark` from Alan-Cha/silhouette-card-maker (SCM),
MIT licence, Copyright (c) Alan Cha. Ported from the code, not from SPECIFICATION.md:

* SCM draws in matplotlib (y up) on the landscape page:
  - THREE marks: a 5 × 5 mm filled square with its corner at (inset, inset) from the
    top-left, outlined with a `thickness` stroke (so its ink spans inset − t/2 … inset + 5 + t/2);
    FOUR marks: an L at top-left instead of the square.
  - L marks at bottom-left and top-right (+ bottom-right with FOUR): two lines from the corner
    point at `inset` running `length − t/2` inward, `thickness` wide. matplotlib's default
    'projecting' line caps extend each end by t/2, so the ink of each arm runs from t/2 behind
    the corner point to exactly `length` in front of it.
* Here the same shapes are filled rectangles in the Studio frame (y down), so they can be
  drawn into the PDF as vectors and into previews at any resolution.

Our values come from config/sheet.json (inset 10, length 10, thickness 1; SCM v6 uses 8.04 mm
arms). The Studio template must use the same values.
"""
from __future__ import annotations

from .config import Sheet

Rect = tuple[float, float, float, float]  # x0, y0, x1, y1 (Studio frame, mm)

SQUARE = 5.0  # side of the Type 1 square, mm


def _l_mark(cx: float, cy: float, sx: int, sy: int, length: float, t: float) -> list[Rect]:
    """L with its corner point at (cx, cy); arms run toward +sx (horizontal) and +sy (vertical)."""
    h = t / 2
    xa = sorted((cx - sx * h, cx + sx * length))
    ya = sorted((cy - sy * h, cy + sy * length))
    return [(xa[0], cy - h, xa[1], cy + h), (cx - h, ya[0], cx + h, ya[1])]


def mark_rects(sheet: Sheet) -> list[Rect]:
    """Every mark as filled rectangles in the Studio frame (landscape page, y down)."""
    i, L, t = sheet.mark_inset, sheet.mark_length, sheet.mark_thickness
    W, H = sheet.paper_w, sheet.paper_h
    h = t / 2
    out: list[Rect] = []
    if sheet.marks == 3:
        out.append((i - h, i - h, i + SQUARE + h, i + SQUARE + h))     # square, top-left
    else:
        out += _l_mark(i, i, +1, +1, L, t)                            # ┌ top-left
    out += _l_mark(i, H - i, +1, -1, L, t)                             # └ bottom-left
    out += _l_mark(W - i, i, -1, +1, L, t)                             # ┐ top-right
    if sheet.marks == 4:
        out += _l_mark(W - i, H - i, -1, -1, L, t)                     # ┘ bottom-right
    return out


def mark_corner_points(sheet: Sheet) -> dict[str, tuple[float, float]]:
    """The reference point of each mark (Studio frame): the square's corner, the L corner points."""
    i, W, H = sheet.mark_inset, sheet.paper_w, sheet.paper_h
    pts = {"top-left": (i, i), "bottom-left": (i, H - i), "top-right": (W - i, i)}
    if sheet.marks == 4:
        pts["bottom-right"] = (W - i, H - i)
    return pts


def notch_corners(sheet: Sheet) -> list[Rect]:
    """Laminate notch squares at the mark corners (Studio TL, TR, BL; + BR with 4 marks)."""
    sq = sheet.corner_squares(sheet.notch)
    return sq if sheet.marks == 4 else sq[:3]
