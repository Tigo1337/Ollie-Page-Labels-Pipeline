"""The two page frames, and the only place that converts between them.

* **Studio frame**: Silhouette Studio's landscape Letter page, 279.4 × 215.9 mm, origin
  top-left, y down. All geometry (marks, keep-outs, layout cells, cut files, PDF content)
  lives here. The print PDF is a landscape page with /Rotate 270, like SCM's proxy PDFs.
* **Printed view**: the portrait sheet as it comes out of the printer (after /Rotate 270),
  215.9 × 279.4 mm, origin top-left, y down. Used for human wording (top half / bottom
  half), proofs and previews, and by the layout optimizer, which reasons in it.

    point: printed (x, y)  <->  Studio (X, Y) = (W − y, x)          W = Studio width, 279.4
    rect:  printed (x, y, w, h)  ->  Studio (W − y − h, x, h, w)

The Studio square mark at top-left lands at the printed bottom-left; the printed top half
is the Studio right half (X > trim).
"""
from __future__ import annotations

STUDIO_W = 279.4
STUDIO_H = 215.9

Point = tuple[float, float]
Rect = tuple[float, float, float, float]  # x, y, w, h


def to_studio(x: float, y: float, w: float | None = None, h: float | None = None,
              studio_w: float = STUDIO_W) -> Point | Rect:
    """Printed view -> Studio frame. A point (x, y), or a rect (x, y, w, h) when w and h are given."""
    if w is None or h is None:
        return studio_w - y, x
    return studio_w - y - h, x, h, w


def to_printed(X: float, Y: float, W: float | None = None, H: float | None = None,
               studio_w: float = STUDIO_W) -> Point | Rect:
    """Studio frame -> printed view (inverse of `to_studio`)."""
    if W is None or H is None:
        return Y, studio_w - X
    return Y, studio_w - X - W, H, W
