"""Placeholder artwork shaped like the real Google Flow images (for tests and demos).

wide:   2752 × 1536, a 4:1 strip on a plain white letterbox, character at the left.
square: 2048 × 2048, same character, name area in the upper middle.
"""
from __future__ import annotations

import colorsys
import hashlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .config import Design, hex_to_rgb


def _palette(design: Design) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    base = hex_to_rgb(design.fill if design.fill.upper() != "#FFFFFF" else design.stroke)
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in base))
    sky_top = tuple(int(c * 255) for c in colorsys.hls_to_rgb(h, 0.88, min(1, s * 0.6)))
    sky_bot = tuple(int(c * 255) for c in colorsys.hls_to_rgb((h + 0.08) % 1, 0.95, min(1, s * 0.4)))
    char = tuple(int(c * 255) for c in colorsys.hls_to_rgb(h, 0.55, min(1, s + 0.2)))
    return sky_top, sky_bot, char  # type: ignore[return-value]


def _scene(w: int, h: int, design: Design, char_box: tuple[int, int, int, int], seed: int) -> Image.Image:
    sky_top, sky_bot, char = _palette(design)
    t = np.linspace(0, 1, h)[:, None, None]
    grad = (np.array(sky_top) * (1 - t) + np.array(sky_bot) * t)
    img = Image.fromarray(np.repeat(grad, w, axis=1).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(seed)
    # rolling hills along the bottom
    ground = tuple(max(0, c - 60) for c in char)
    pts = [(0, h)]
    for x in range(0, w + 40, 40):
        pts.append((x, int(h * 0.82 + h * 0.06 * np.sin(x / w * 9 + seed))))
    pts.append((w, h))
    d.polygon(pts, fill=ground)
    for _ in range(max(3, w // 400)):  # little scenery dots
        x = int(rng.uniform(w * 0.35, w * 0.98))
        r = int(h * rng.uniform(0.03, 0.07))
        d.ellipse([x - r, int(h * 0.8) - r, x + r, int(h * 0.8) + r], fill=tuple(min(255, c + 40) for c in ground))
    # the "character"
    x0, y0, x1, y1 = char_box
    d.ellipse([x0, y0, x1, y1], fill=char, outline=(40, 40, 40), width=max(2, (x1 - x0) // 40))
    ew = (x1 - x0) // 9
    for ex in (x0 + (x1 - x0) * 0.35, x0 + (x1 - x0) * 0.62):
        d.ellipse([ex - ew, y0 + (y1 - y0) * 0.3, ex + ew, y0 + (y1 - y0) * 0.3 + 2 * ew], fill="white")
        d.ellipse([ex - ew / 2, y0 + (y1 - y0) * 0.33, ex + ew / 2, y0 + (y1 - y0) * 0.33 + ew], fill="black")
    return img


def make_wide(design: Design, w: int = 2752, h: int = 1536) -> Image.Image:
    seed = int(hashlib.md5(design.id.encode()).hexdigest()[:6], 16)
    sh = w // 4
    top = (h - sh) // 2
    strip_w = w
    cw = int(strip_w * design.char_end)
    char_box = (int(cw * 0.1), int(sh * 0.12), int(cw * 0.95), int(sh * 0.95))
    strip = _scene(strip_w, sh, design, char_box, seed)
    img = Image.new("RGB", (w, h), (255, 255, 255))
    img.paste(strip, (0, top))
    return img


def make_square(design: Design, s: int = 2048) -> Image.Image:
    seed = int(hashlib.md5(design.id.encode()).hexdigest()[:6], 16)
    char_box = (int(s * 0.3), int(s * 0.45), int(s * 0.7), int(s * 0.88))
    return _scene(s, s, design, char_box, seed)


def write_design_art(design: Design, root: Path) -> None:
    d = root / "designs" / design.id
    d.mkdir(parents=True, exist_ok=True)
    make_wide(design).save(d / f"{design.id}_wide.jpg", quality=92)
    make_square(design).save(d / f"{design.id}_square.jpg", quality=92)


def write_solid_art(design_id: str, root: Path, colour: tuple[int, int, int] = (40, 90, 200)) -> None:
    """Uniform-colour art (used by the alignment test: every bleed pixel is ink)."""
    d = root / "designs" / design_id
    d.mkdir(parents=True, exist_ok=True)
    wide = Image.new("RGB", (2752, 1536), (255, 255, 255))
    wide.paste(Image.new("RGB", (2752, 688), colour), (0, 424))
    wide.save(d / f"{design_id}_wide.png")
    Image.new("RGB", (2048, 2048), colour).save(d / f"{design_id}_square.png")
