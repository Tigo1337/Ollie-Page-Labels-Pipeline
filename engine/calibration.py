"""A one-off calibration sheet to prove print → mark reading → cut alignment on plain paper.

Each target is a printed ring 2.5 mm wide; the cut file cuts a square down the middle of
every ring. If the cut runs inside every ring, alignment is within the 1.25 mm bleed.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.pdfgen import canvas as rl_canvas

from . import cutfiles
from .config import Production
from .geometry import PT_PER_MM, bbox, rrect_points
from .production import draw_marks_pdf

TARGET = 20.0  # cut square side, mm


def target_centres(prod: Production) -> list[tuple[float, float]]:
    W, H = prod.page_w, prod.page_h
    return [(W / 2, 24.0), (24.0, H / 2), (W / 2, H / 2), (W - 24.0, H / 2), (W / 2, H - 24.0),
            (W - 24.0, H - 24.0)]


def write_calibration(prod: Production, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    b = prod.bleed
    pdf = out_dir / "calibration_print.pdf"
    c = rl_canvas.Canvas(str(pdf), pagesize=(prod.page_w * PT_PER_MM, prod.page_h * PT_PER_MM))
    c.setTitle("Calibration sheet")
    paths = []
    for cx, cy in target_centres(prod):
        x0, y0 = cx - TARGET / 2, cy - TARGET / 2
        paths.append(rrect_points(x0, y0, TARGET, TARGET, 0))
        # black ring from -1.25 to +1.25 mm around the cut line, white inside
        c.setFillColorRGB(0, 0, 0)
        c.rect((x0 - b) * PT_PER_MM, (prod.page_h - y0 - TARGET - b) * PT_PER_MM,
               (TARGET + 2 * b) * PT_PER_MM, (TARGET + 2 * b) * PT_PER_MM, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.rect((x0 + b) * PT_PER_MM, (prod.page_h - y0 - TARGET + b) * PT_PER_MM,
               (TARGET - 2 * b) * PT_PER_MM, (TARGET - 2 * b) * PT_PER_MM, stroke=0, fill=1)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.setFont("Helvetica", 9)
    lines = ["CALIBRATION SHEET - print at 100 % (actual size) on plain paper.",
             "Cut calibration_cut.dxf at the X / Y given below. Every cut must run inside the black rings",
             "(each ring is the 2.5 mm bleed band). If a cut leaves a ring, alignment is off."]
    bx0, by0, bx1, by1 = bbox([p for path in paths for p in path])
    lines.append(f"Cut file position: X {bx0:.2f} mm   Y {by0:.2f} mm   (W {bx1 - bx0:.2f}  H {by1 - by0:.2f})")
    for i, t in enumerate(lines):
        c.drawString(40 * PT_PER_MM, (prod.page_h - 95 - i * 5) * PT_PER_MM, t)
    draw_marks_pdf(c, prod)
    c.showPage()
    c.save()
    (out_dir / "calibration_cut.dxf").write_text(cutfiles.dxf_r12(paths, prod.page_h, prod.page_w), encoding="ascii")
    (out_dir / "calibration_cut.svg").write_text(cutfiles.svg(paths, prod.page_w, prod.page_h), encoding="utf-8")
    x0, y0, x1, y1 = bbox([p for path in paths for p in path])
    info = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
    (out_dir / "calibration_info.txt").write_text(
        "Calibration cut file placement (Silhouette Studio, Transformer -> Position):\n"
        f"  X {x0:.2f} mm   Y {y0:.2f} mm   W {x1 - x0:.2f} mm   H {y1 - y0:.2f} mm\n"
        f"Registration marks: Type 1, inset {prod.mark_inset:g} mm, length {prod.mark_length:g} mm, "
        f"thickness {prod.mark_thickness:g} mm.\n", encoding="utf-8")
    return info
