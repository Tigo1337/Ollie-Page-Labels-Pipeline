"""Artwork handling: white-band trimming, crop presets and the automatic layout."""
from __future__ import annotations

import numpy as np
from PIL import Image

from dataclasses import replace

from .config import Design, Preset, Size

TRIM_THRESHOLD = 245.0
# Fixed name position: on a strip size with `name_start` (sizes.json), the name box starts at that
# fraction of the label width on every design; the art slides left so the character ends
# NAME_GAP_MM before it (a wide character's left side may be cut).
NAME_GAP_MM = 0.8
TRIM_SHAVE_PX = 4


class ArtError(ValueError):
    pass


def trim_white_bands(img: Image.Image, threshold: float = TRIM_THRESHOLD,
                     shave: int = TRIM_SHAVE_PX) -> Image.Image:
    """Trim the plain white letterbox above and below a wide strip.

    Keeps the rows whose mean greyscale is under `threshold` (from the first such
    row to the last, so a pale row of sky inside the strip is never dropped), then
    shaves `shave` px off the top and bottom to remove the soft edge.
    """
    grey = np.asarray(img.convert("L"), dtype=np.float32)
    rows = np.where(grey.mean(axis=1) < threshold)[0]
    if rows.size == 0:
        raise ArtError("The wide image looks completely white; no illustrated strip found.")
    top, bottom = int(rows[0]) + shave, int(rows[-1]) + 1 - shave
    if bottom - top < 8:
        raise ArtError("The illustrated strip in the wide image is too thin after trimming.")
    return img.crop((0, top, img.width, bottom))


def bleed_aspect(size: Size, bleed: float) -> float:
    """Width / height of what the crop fills: the label (a pair: the whole pair cell) plus bleed."""
    return (size.w + 2 * bleed) / (size.h + 2 * bleed)


def crop_window(preset: Preset, src_w: int, src_h: int, aspect: float) -> tuple[float, float, float, float]:
    """Crop window (x0, y0, x1, y1) in source pixels for a preset.

    crop height = h × source height; width follows the label aspect (with bleed).
    If the width is larger than the source it is clamped and the height recomputed;
    then the window is clamped inside the image.
    """
    ch = max(1e-6, preset.height) * src_h
    cw = ch * aspect
    if cw > src_w:
        cw = float(src_w)
        ch = cw / aspect
    if ch > src_h:
        ch = float(src_h)
        cw = ch * aspect
    cx, cy = preset.center[0] * src_w, preset.center[1] * src_h
    x0 = min(max(cx - cw / 2, 0.0), src_w - cw)
    y0 = min(max(cy - ch / 2, 0.0), src_h - ch)
    return x0, y0, x0 + cw, y0 + ch


def crop_to_label(img: Image.Image, preset: Preset, size: Size, bleed: float,
                  out_px: tuple[int, int]) -> Image.Image:
    win = crop_window(preset, img.width, img.height, bleed_aspect(size, bleed))
    return img.convert("RGB").resize(out_px, Image.Resampling.LANCZOS, box=win)


def auto_preset(design: Design, size: Size, bleed: float, src_w: int, src_h: int) -> Preset:
    """The automatic layout, expressed as a preset so everything downstream is the same.

    * round, shoe pair and tall sizes: the square art covering the label (a pair: the whole
      pair cell, later split into its two labels), name box = the design's `square_text`
      (for a pair: fractions of each label);
    * sizes without the character (`no_character_sizes`, by default the clothing tag): the strip
      from `mini_start` onwards, and the name fills the label;
    * strips with a fixed name position (`size.name_start`: pencil, small, medium, large): the name
      box is the same on every design (`fixed_name_box`) and the strip slides so the character ends
      just before it, never past either end of the strip;
    * other strips: the strip at label height + bleed, anchored left so the character shows,
      name box from the character's end (`char_end`) to the right edge.
    """
    b = bleed
    if not size.is_rect:
        return Preset(source="square", center=(0.5, 0.5), height=1.0, text=tuple(design.square_text))  # type: ignore[arg-type]

    aspect = bleed_aspect(size, b)
    # Scale the strip to label height + bleed.
    ch = float(src_h)
    cw = ch * aspect
    if cw > src_w:  # strip narrower than the label: fill the width instead
        cw = float(src_w)
        ch = cw / aspect
    height = ch / src_h
    if size.id in design.no_character_sizes:
        x0 = min(design.mini_start * src_w, src_w - cw)
        pad = max(1.0, 0.4 * size.r)
        return Preset(source="wide", center=((x0 + cw / 2) / src_w, 0.5), height=height,
                      text=(pad / size.w, 0.6 * pad / size.h, 1 - pad / size.w, 1 - 0.6 * pad / size.h))
    mm_per_px = (size.h + 2 * b) / ch
    pad = max(1.0, 0.45 * size.r)
    vpad = pad * 0.7
    x1 = size.w - pad
    t0 = size.name_start
    if t0 is not None:
        # slide the strip so the character's end (char_end) lands NAME_GAP_MM before the name box
        name_x = t0 * size.w                                   # mm from the label's left cut edge
        x0_src = design.char_end * src_w - (name_x - NAME_GAP_MM + b) / mm_per_px
        x0_src = min(max(x0_src, 0.0), src_w - cw)             # never past the strip's ends
        center = ((x0_src + cw / 2) / src_w, 0.5)
        return Preset(source="wide", center=center, height=height, text=fixed_name_box(size))  # type: ignore[arg-type]
    center = ((cw / 2) / src_w, 0.5)
    strip_w_mm = src_w * mm_per_px
    x0 = design.char_end * strip_w_mm - b + 1.0
    x0 = min(max(x0, pad), x1 - 0.25 * size.w)  # keep a usable box on narrow strips
    return Preset(source="wide", center=center, height=height,
                  text=(x0 / size.w, vpad / size.h, x1 / size.w, 1 - vpad / size.h))


def fixed_name_box(size: Size) -> tuple[float, float, float, float] | None:
    """The name box (fractions of the label) every design uses on a size with a fixed name position,
    or None for sizes without one (tag, round, shoe)."""
    if size.name_start is None:
        return None
    pad = max(1.0, 0.45 * size.r)
    vpad = pad * 0.7
    return (size.name_start, vpad / size.h, (size.w - pad) / size.w, 1 - vpad / size.h)


def has_fixed_name(design: Design, size: Size) -> bool:
    """True when this design's name box on this size is the fixed one (the size has `name_start` and
    the design shows its character there)."""
    return size.is_rect and size.name_start is not None and size.id not in design.no_character_sizes


def effective_preset(preset: Preset, size: Size, design: Design) -> Preset:
    """A preset as it prints: with a fixed name position the fixed box always wins over the preset's
    own `text` (only the art's centre and height are the preset's)."""
    box = fixed_name_box(size)
    if box is None or not has_fixed_name(design, size) or tuple(preset.text) == box:
        return preset
    return replace(preset, text=box)


def resolve_preset(design: Design, size: Size, bleed: float,
                   src_dims: dict[str, tuple[int, int]]) -> tuple[Preset, bool]:
    """Saved preset if there is one (with the fixed name box on strip sizes), else the automatic one.
    Returns (preset, is_auto)."""
    p = design.presets.get(size.id)
    if p is not None:
        return effective_preset(p, size, design), False
    src = size.default_source
    if src not in src_dims:
        raise ArtError(f"Design '{design.id}' has no {src} artwork yet. Upload it in the design library.")
    w, h = src_dims[src]
    return auto_preset(design, size, bleed, w, h), True


def _window_size(height: float, src_w: int, src_h: int, aspect: float) -> tuple[float, float]:
    """(width, height) in source px of the crop window for a preset height (as `crop_window` sizes it)."""
    ch = max(1e-6, height) * src_h
    cw = ch * aspect
    if cw > src_w:
        cw = float(src_w)
        ch = cw / aspect
    if ch > src_h:
        ch = float(src_h)
        cw = ch * aspect
    return cw, ch


def _auto_x0(design: Design, size: Size, bleed: float, src_w: int, ch: float, cw: float) -> float:
    """Left edge (source px) of the automatic crop of a fixed-name size for a window ch px high:
    the character ends NAME_GAP_MM before the name box, never past either end of the strip."""
    name_x = size.name_start * size.w                                        # type: ignore[operator]
    x0 = design.char_end * src_w - (name_x - NAME_GAP_MM + bleed) * ch / (size.h + 2 * bleed)
    return min(max(x0, 0.0), src_w - cw)


def transfer_preset(design: Design, preset: Preset, src: Size, dst: Size, bleed: float,
                    src_w: int, src_h: int) -> Preset:
    """A saved crop of one strip size carried over to another strip size with a fixed name position.

    The sizes have different shapes and name positions, so the crop's fractions cannot be copied as
    they are. What is carried over is the change from the automatic crop: the zoom, and how many mm
    the art was slid. Each size starts from its own automatic crop (character just before the name),
    so copying an automatic crop gives the other size its own automatic crop. Never past either end
    of the strip."""
    box = fixed_name_box(dst)
    if box is None or src.name_start is None:
        raise ArtError("The art position can only be copied between the skinny, small, medium and large labels.")
    if preset.source != "wide":                     # square art on a strip: keep the plain fractions
        return Preset(preset.source, preset.center, preset.height, box)
    b = bleed
    a_src, a_dst = bleed_aspect(src, b), bleed_aspect(dst, b)
    x0, y0, x1, y1 = crop_window(preset, src_w, src_h, a_src)
    cw_src, ch_src = x1 - x0, y1 - y0
    zoom = ch_src / (auto_preset(design, src, b, src_w, src_h).height * src_h)
    slid_mm = (x0 - _auto_x0(design, src, b, src_w, ch_src, cw_src)) * (src.h + 2 * b) / ch_src
    height = min(1.0, max(0.02, auto_preset(design, dst, b, src_w, src_h).height * zoom))
    cw, ch = _window_size(height, src_w, src_h, a_dst)
    x0d = _auto_x0(design, dst, b, src_w, ch, cw) + slid_mm * ch / (dst.h + 2 * b)
    x0d = min(max(x0d, 0.0), src_w - cw)
    cy = (y0 + ch_src / 2) / src_h
    return Preset("wide", ((x0d + cw / 2) / src_w, cy), ch / src_h, box)


def validate_preset(p: Preset, src_dims: dict[str, tuple[int, int]]) -> Preset:
    """Plain-language checks for a preset coming from the crop editor."""
    if p.source not in ("wide", "square"):
        raise ArtError("A crop must use the 'wide' or the 'square' image.")
    if p.source not in src_dims:
        raise ArtError(f"This design has no {p.source} artwork yet.")
    cx, cy = p.center
    if not (0 <= cx <= 1 and 0 <= cy <= 1):
        raise ArtError("The crop centre must be inside the image.")
    if not 0.02 <= p.height <= 1.0 + 1e-6:
        raise ArtError("The crop is too small or too large.")
    x0, y0, x1, y1 = p.text
    if not (-1e-6 <= x0 < x1 <= 1 + 1e-6 and -1e-6 <= y0 < y1 <= 1 + 1e-6):
        raise ArtError("The name box must sit inside the label.")
    if (x1 - x0) < 0.05 or (y1 - y0) < 0.05:
        raise ArtError("The name box is too small.")
    return p
