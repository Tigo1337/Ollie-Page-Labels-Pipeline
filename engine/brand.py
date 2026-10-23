"""The Mazie Page Creations brand for anything a buyer sees (customer proofs; the listing images keep
their own copy in listing_images.py): the four colours, the logo files in brand/ and the two fonts.

Plum #3E2352, Lilac #C9B5F0, Blush #F5BFD0, Pearl #FBF7FB. Text is always Plum, or Pearl on Plum.
Fredoka SemiBold (font 1) for titles, Nunito (font 3) for text.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFont

from .text import FontLibrary

BRAND_DIR = Path(__file__).resolve().parent.parent / "brand"
PLUM = (0x3E, 0x23, 0x52)
LILAC = (0xC9, 0xB5, 0xF0)
BLUSH = (0xF5, 0xBF, 0xD0)
PEARL = (0xFB, 0xF7, 0xFB)
DISPLAY_FONT_ID = 1          # Fredoka
TEXT_FONT_ID = 3             # Nunito
LOGO = "mazie-page-logo-horizontal_2400.png"


def brand_font(fonts: FontLibrary, kind: str, size_px: int, weight: int) -> ImageFont.FreeTypeFont:
    """kind "display" (Fredoka) or "text" (Nunito) at `size_px` and a `weight` on the variable axis."""
    lf = fonts.get(DISPLAY_FONT_ID if kind == "display" else TEXT_FONT_ID)
    f = ImageFont.truetype(str(lf.path), size_px)
    if lf.axes:
        f.set_variation_by_axes([float(weight) if tag == "wght" else default for tag, lo, default, hi in lf.axes])
    return f


def logo(width_px: int, brand_dir: Path = BRAND_DIR) -> Image.Image:
    """The horizontal logo (RGBA) scaled to `width_px`."""
    im = Image.open(brand_dir / LOGO).convert("RGBA")
    return im.resize((width_px, round(im.height * width_px / im.width)), Image.Resampling.LANCZOS)
