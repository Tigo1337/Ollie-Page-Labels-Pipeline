"""Name text: normalisation, glyph check, fitting and drawing."""
from __future__ import annotations

import io
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fontTools.ttLib import TTFont
from PIL import ImageDraw, ImageFont

from .config import FontSpec


class FontError(ValueError):
    pass


class GlyphError(ValueError):
    def __init__(self, text: str, font: FontSpec, missing: list[str], alternatives: list[FontSpec]):
        self.text = text
        self.font = font
        self.missing = missing
        self.alternatives = alternatives
        alt = ", ".join(f"{f.id} {f.name}" for f in alternatives) or "none of the fonts"
        chars = " ".join(missing)
        super().__init__(f"Font {font.id} ({font.name}) has no glyph for: {chars} in \"{text}\". "
                         f"Fonts that have every character: {alt}.")


def normalise_name(s: str | None) -> str:
    if not s:
        return ""
    return " ".join(unicodedata.normalize("NFC", s).split())


class LoadedFont:
    """A font file with its variable-weight instance applied."""

    def __init__(self, spec: FontSpec, path: Path):
        if not path.exists():
            raise FontError(f"Font {spec.id} ({spec.name}) is not installed: {path.name} is missing. "
                            "Run the font downloader.")
        self.spec = spec
        self.path = path
        self.data = path.read_bytes()
        tt = TTFont(io.BytesIO(self.data), lazy=True)
        self.codepoints: frozenset[int] = frozenset(tt.getBestCmap() or {})
        self.axes: list[tuple[str, float, float, float]] = []
        if "fvar" in tt:
            self.axes = [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in tt["fvar"].axes]
        tt.close()
        self._cache: dict[int, ImageFont.FreeTypeFont] = {}
        self.cap_ratio = self._measure_cap_ratio()

    def at(self, size_px: int) -> ImageFont.FreeTypeFont:
        f = self._cache.get(size_px)
        if f is None:
            f = ImageFont.truetype(io.BytesIO(self.data), size_px)
            if self.axes:
                values = []
                for tag, lo, default, hi in self.axes:
                    v = default
                    if tag == "wght" and self.spec.weight is not None:
                        v = min(max(float(self.spec.weight), lo), hi)
                    values.append(v)
                f.set_variation_by_axes(values)
            if len(self._cache) > 256:
                self._cache.clear()
            self._cache[size_px] = f
        return f

    def _measure_cap_ratio(self) -> float:
        f = self.at(1000)
        _, t, _, b = f.getbbox("H", anchor="ls")
        return (b - t) / 1000.0

    def missing_chars(self, text: str) -> list[str]:
        seen: list[str] = []
        for ch in text:
            if ch.isspace():
                continue
            if ord(ch) not in self.codepoints and ch not in seen:
                seen.append(ch)
        return seen


class FontLibrary:
    def __init__(self, fonts: dict[int, FontSpec], resolve_path: Callable[[FontSpec], Path]):
        self.specs = fonts
        self._resolve = resolve_path
        self._loaded: dict[int, LoadedFont] = {}

    def get(self, font_id: int) -> LoadedFont:
        if font_id not in self.specs:
            raise FontError(f"Unknown font number {font_id}. Valid numbers are "
                            f"{min(self.specs)}–{max(self.specs)}.")
        lf = self._loaded.get(font_id)
        if lf is None:
            lf = LoadedFont(self.specs[font_id], self._resolve(self.specs[font_id]))
            self._loaded[font_id] = lf
        return lf

    def check_glyphs(self, text: str, font_id: int) -> None:
        """Raise GlyphError listing the fonts that do have every character."""
        lf = self.get(font_id)
        missing = lf.missing_chars(text)
        if not missing:
            return
        alts = []
        for fid, spec in self.specs.items():
            try:
                other = self.get(fid)
            except FontError:
                continue
            if not other.missing_chars(text):
                alts.append(spec)
        raise GlyphError(text, lf.spec, missing, alts)


@dataclass
class FittedLine:
    text: str
    size_px: int
    stroke_px: int
    origin: tuple[float, float]           # left-baseline anchor, px
    ink: tuple[float, float, float, float]  # ink box incl. stroke, px
    cap_px: float


Box = tuple[float, float, float, float]


def fit_line(font: LoadedFont, text: str, box: Box, cap_frac: float, stroke_ratio: float,
             ink_ok: Callable[[Box], bool] | None = None) -> FittedLine | None:
    """Largest size where the stroked text fits the box and cap height ≤ cap_frac × box height.

    The text is centred on its cap height, then clamped so ascenders and
    descenders stay inside the box. `ink_ok` adds the safe-zone check.
    """
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    if bw <= 0 or bh <= 0 or not text:
        return None

    def attempt(s: int) -> FittedLine | None:
        cap = font.cap_ratio * s
        if cap > cap_frac * bh:
            return None
        stroke = int(round(stroke_ratio * cap))
        l, t, r, b = font.at(s).getbbox(text, anchor="ls", stroke_width=stroke)
        w, h = r - l, b - t
        if w > bw or h > bh:
            return None
        ox = x0 + (bw - w) / 2 - l
        base = (y0 + y1) / 2 + cap / 2
        if base + t < y0:
            base = y0 - t
        if base + b > y1:
            base = y1 - b
        ink = (ox + l, base + t, ox + r, base + b)
        if ink_ok is not None and not ink_ok(ink):
            return None
        return FittedLine(text, s, stroke, (ox, base), ink, cap)

    lo, hi = 1, max(2, int(bh / max(font.cap_ratio, 0.3) * 1.2) + 2)
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        res = attempt(mid)
        if res is not None:
            best, lo = res, mid + 1
        else:
            hi = mid - 1
    return best


def draw_line(draw: ImageDraw.ImageDraw, font: LoadedFont, line: FittedLine,
              fill: tuple[int, int, int], stroke: tuple[int, int, int]) -> None:
    draw.text(line.origin, line.text, font=font.at(line.size_px), fill=fill, anchor="ls",
              stroke_width=line.stroke_px, stroke_fill=stroke)
