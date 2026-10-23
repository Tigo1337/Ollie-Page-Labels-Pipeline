"""Static UI fonts (for proof captions, info sheets) made from Nunito by instancing its weight axis.

ReportLab cannot use variable fonts, so we instance them once and cache the result.
"""
from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from PIL import ImageFont

UI_FONT_ID = 3  # Nunito
WEIGHTS = {"regular": 500, "bold": 800}


def ui_font_paths(nunito_path: Path, cache_dir: Path) -> dict[str, Path]:
    """Static Nunito instances, each with its own font name: PDF viewers tell embedded fonts apart by
    name, so two instances both called after the variable font's default would print the same weight."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, wght in WEIGHTS.items():
        p = cache_dir / f"NunitoUI-{name}.ttf"
        if not p.exists():
            if not nunito_path.exists():
                raise FileNotFoundError(f"UI font source missing: {nunito_path}. Run the font downloader.")
            vf = TTFont(nunito_path)
            inst = instancer.instantiateVariableFont(vf, {"wght": wght})
            style = name.title()
            for rec in inst["name"].names:
                if rec.nameID in (1, 16):
                    rec.string = "Nunito UI"
                elif rec.nameID in (2, 17):
                    rec.string = style
                elif rec.nameID in (3, 4, 6):
                    rec.string = f"NunitoUI-{style}"
            inst.save(p)
        out[name] = p
    return out


class UIFonts:
    def __init__(self, paths: dict[str, Path]):
        self.paths = paths
        self._pil: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

    def pil(self, size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
        k = (weight, size)
        if k not in self._pil:
            self._pil[k] = ImageFont.truetype(str(self.paths[weight]), size)
        return self._pil[k]

    _registered = False

    def reportlab(self) -> tuple[str, str]:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont as RLTTFont
        if not UIFonts._registered:
            pdfmetrics.registerFont(RLTTFont("UI", str(self.paths["regular"])))
            pdfmetrics.registerFont(RLTTFont("UI-Bold", str(self.paths["bold"])))
            UIFonts._registered = True
        return "UI", "UI-Bold"
