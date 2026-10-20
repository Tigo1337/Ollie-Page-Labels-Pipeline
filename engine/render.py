"""Rendering one label: crop the art, mask it to the bleed shape and fit the name."""
from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field, replace

from PIL import Image, ImageDraw

from .art import crop_to_label, resolve_preset
from .assets import Assets
from .config import Catalog, Design, Preset, Size, hex_to_rgb
from .geometry import mm_to_px, px, rect_in_shape, shape_mask
from .text import FittedLine, FontLibrary, draw_line, fit_line, normalise_name

ENGINE_VERSION = "2"
MINI_SIZES = ("pencil", "tag")  # fonts with mini_ok: false get a warning on these


class RenderError(ValueError):
    pass


@dataclass
class LabelSpec:
    """What makes a label unique (the render cache key, minus the artwork hash)."""
    design: str
    size: str
    name: str
    line2: str = ""
    font: int = 1
    finish: str = "matte"

    def normalised(self) -> "LabelSpec":
        return LabelSpec(self.design, self.size, normalise_name(self.name), normalise_name(self.line2),
                         int(self.font), self.finish)


@dataclass
class RenderedLabel:
    spec: LabelSpec
    image: Image.Image        # RGB, bleed box at `dpi`, white outside the bleed shape
    dpi: int
    bleed_mm: tuple[float, float]
    preset: Preset
    preset_is_auto: bool
    lines: list[FittedLine]
    cap_mm: list[float]
    warnings: list[str] = field(default_factory=list)
    text_box_px: tuple[float, float, float, float] = (0, 0, 0, 0)

    @property
    def min_cap_mm(self) -> float:
        return min(self.cap_mm) if self.cap_mm else 0.0


def split_box(box: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
    """Two-line split: 60 / 40 with a 4 % gap."""
    x0, y0, x1, y1 = box
    h = y1 - y0
    gap = 0.04 * h
    h1 = 0.6 * (h - gap)
    return [(x0, y0, x1, y0 + h1), (x0, y0 + h1 + gap, x1, y1)]


class Renderer:
    def __init__(self, catalog: Catalog, assets: Assets, fonts: FontLibrary, cache_size: int = 256):
        self.cat = catalog
        self.assets = assets
        self.fonts = fonts
        self._cache: OrderedDict[str, RenderedLabel] = OrderedDict()
        self._cache_size = cache_size

    # -- helpers -----------------------------------------------------------
    def design(self, design_id: str) -> Design:
        d = self.cat.designs.get(design_id)
        if d is None:
            raise RenderError(f"Unknown design '{design_id}'.")
        return d

    def size(self, size_id: str) -> Size:
        s = self.cat.sizes.get(size_id)
        if s is None:
            raise RenderError(f"Unknown size '{size_id}'.")
        return s

    def preset_for(self, design: Design, size: Size) -> tuple[Preset, bool]:
        return resolve_preset(design, size, self.cat.sheet.bleed, self.assets.art_sources(design.id))

    def cache_key(self, spec: LabelSpec, preset: Preset, design: Design, dpi: int) -> str:
        size = self.size(spec.size)
        payload = {
            "v": ENGINE_VERSION, "spec": spec.__dict__, "preset": preset.to_dict(),
            "art": self.assets.art_version(design.id, preset.source),
            "style": [design.fill, design.stroke, design.effective_stroke_ratio, design.cap_frac],
            "size": size.__dict__, "prod": self.cat.production.__dict__, "bleed": self.cat.sheet.bleed, "dpi": dpi,
            "design": [design.mini_start, list(design.square_text), list(design.no_character_sizes)],
            "font": self.fonts.specs[spec.font].__dict__ if spec.font in self.fonts.specs else spec.font,
        }
        return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    # -- main entry ---------------------------------------------------------
    def render(self, spec: LabelSpec, preset: Preset | None = None, dpi: int | None = None,
               check_glyphs: bool = True) -> RenderedLabel:
        spec = spec.normalised()
        if not spec.name:
            raise RenderError("The name is empty.")
        dpi = dpi or self.cat.sheet.dpi
        design = self.design(spec.design)
        size = self.size(spec.size)
        is_auto = False
        if preset is None:
            preset, is_auto = self.preset_for(design, size)
        key = self.cache_key(spec, preset, design, dpi)
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return hit
        if check_glyphs:
            self.fonts.check_glyphs(spec.name + spec.line2, spec.font)
        out = self._render(spec, design, size, preset, is_auto, dpi)
        self._cache[key] = out
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return out

    def _render(self, spec: LabelSpec, design: Design, size: Size, preset: Preset, is_auto: bool,
                dpi: int) -> RenderedLabel:
        """The label (a pair: the whole pair cell) at cut size + bleed, white outside the bleed shape.

        A shoe pair is one crop over the whole cell, so the picture runs on across both labels;
        the name goes on each label (the preset's name box is a fraction of one label), and a
        small G / D (gauche / droite) sits in each label's safe area."""
        prod = self.cat.production
        b = self.cat.sheet.bleed
        bw_mm, bh_mm = size.w + 2 * b, size.h + 2 * b
        W, H = px(bw_mm, dpi), px(bh_mm, dpi)
        src = self.assets.art(design.id, preset.source)
        art = crop_to_label(src, preset, size, b, (W, H))

        # White outside the bleed shape (the cut shape grown by the bleed).
        mask = shape_mask(size, b, (bw_mm, bh_mm), (b, b), dpi)
        canvas = Image.new("RGB", (W, H), (255, 255, 255))
        canvas.paste(art, (0, 0), mask)

        k = mm_to_px(1, dpi)
        labels = size.label_rects()                     # one, or two for a pair
        lx0, ly0, lw, lh = labels[0]
        one = single_label(size)
        tx0, ty0, tx1, ty1 = preset.text
        box = ((b + lx0 + tx0 * lw) * k, (b + ly0 + ty0 * lh) * k, (b + lx0 + tx1 * lw) * k, (b + ly0 + ty1 * lh) * k)

        def ink_ok(r: tuple[float, float, float, float]) -> bool:
            rect_mm = (r[0] / k - b - lx0, r[1] / k - b - ly0, r[2] / k - b - lx0, r[3] / k - b - ly0)
            return rect_in_shape(one, rect_mm, prod.safe)

        font = self.fonts.get(spec.font)
        texts = [spec.name] + ([spec.line2] if spec.line2 else [])
        boxes = [box] if len(texts) == 1 else split_box(box)
        lines: list[FittedLine] = []
        for t, bx in zip(texts, boxes):
            fl = fit_line(font, t, bx, design.cap_frac, design.effective_stroke_ratio, ink_ok)
            if fl is None:
                raise RenderError(f"\"{t}\" does not fit the name box of {design.name} / {size.label}. "
                                  "Make the name box bigger in the crop editor.")
            lines.append(fl)

        draw = ImageDraw.Draw(canvas)
        fill, stroke = hex_to_rgb(design.fill), hex_to_rgb(design.stroke)
        for lx, ly, _, _ in labels:
            dx, dy = (lx - lx0) * k, (ly - ly0) * k
            for fl in lines:
                draw_line(draw, font, shifted(fl, dx, dy), fill, stroke)
        if size.shape == "pair":
            self._pair_markers(draw, font, design, size, b, k)

        cap_mm = [fl.cap_px / k for fl in lines]
        warnings = []
        if min(cap_mm) < prod.min_cap_mm:
            warnings.append(f"Small text: cap height {min(cap_mm):.2f} mm on {size.label} "
                            f"for \"{' / '.join(texts)}\" (minimum {prod.min_cap_mm} mm).")
        if size.id in MINI_SIZES and not font.spec.mini_ok:
            warnings.append(f"Font {font.spec.id} ({font.spec.name}) is hard to read on {size.label} labels.")
        return RenderedLabel(spec=spec, image=canvas, dpi=dpi, bleed_mm=(bw_mm, bh_mm), preset=preset,
                             preset_is_auto=is_auto, lines=lines, cap_mm=cap_mm, warnings=warnings,
                             text_box_px=box)

    @staticmethod
    def _pair_markers(draw: ImageDraw.ImageDraw, font, design: Design, size: Size, b: float, k: float) -> None:
        """A small G (left) / D (right) at each label's bottom outer corner, inside the safe area."""
        cap = PAIR_MARK_CAP
        f = font.at(max(4, int(round(cap * k / font.cap_ratio))))
        fill, stroke = hex_to_rgb(design.fill), hex_to_rgb(design.stroke)
        sw = max(1, int(round(design.effective_stroke_ratio * cap * k)))
        inset = size.r * 0.6 + 1.0                       # clear of the rounded corner and the safe line
        (lx, ly, lw, lh), (rx, _, rw, _) = size.label_rects()
        base_y = (b + ly + lh - inset) * k
        draw.text(((b + lx + inset) * k, base_y), "G", font=f, fill=fill, anchor="ls",
                  stroke_width=sw, stroke_fill=stroke)
        draw.text(((b + rx + rw - inset) * k, base_y), "D", font=f, fill=fill, anchor="rs",
                  stroke_width=sw, stroke_fill=stroke)


PAIR_MARK_CAP = 1.8  # mm, cap height of the G / D markers on shoe labels


def single_label(size: Size) -> Size:
    """The shape of one cut label of the size (a pair's left label; otherwise the size itself)."""
    if size.shape != "pair":
        return size
    _, _, lw, lh = size.label_rects()[0]
    return Size(id=size.id, label=size.label, shape="rrect", w=lw, h=lh, r=size.r)


def shifted(fl: FittedLine, dx: float, dy: float) -> FittedLine:
    if not dx and not dy:
        return fl
    x0, y0, x1, y1 = fl.ink
    return replace(fl, origin=(fl.origin[0] + dx, fl.origin[1] + dy), ink=(x0 + dx, y0 + dy, x1 + dx, y1 + dy))
