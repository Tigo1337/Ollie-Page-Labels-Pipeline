"""Calibration sheet per layout: the marks plus every cut outline as a 0.2 mm grey hairline, no art.

Print it at 100 % on plain paper and cut it with the layout's Studio template. If every cut
lands on its hairline, the template (and the machine's mark reading) is right.
"""
from __future__ import annotations

from pathlib import Path

from .config import Catalog
from .layout import LayoutError, current_layout, published
from .templates import calibration_pdf, file_name


def find_layout(cat: Catalog, layout_id: str, layouts_dir: Path):
    for versions in published(layouts_dir).values():
        for lay in versions:
            if lay.layout_id == layout_id:
                return lay
    known = ", ".join(current_layout(cat.sheet, s, layouts_dir).layout_id for s in cat.sizes.values())
    raise LayoutError(f"No layout '{layout_id}'. Current layouts: {known}.")


def write_calibration(cat: Catalog, layout_id: str, out_dir: Path, layouts_dir: Path) -> Path:
    lay = find_layout(cat, layout_id, layouts_dir)
    if lay.size not in cat.sizes:
        raise LayoutError(f"Layout '{layout_id}' is for size '{lay.size}', which is no longer in sizes.json.")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / file_name(layout_id, "calibration.pdf")
    calibration_pdf(lay, cat.sizes[lay.size], cat.sheet, path)
    return path
