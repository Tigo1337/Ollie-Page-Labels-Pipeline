"""Customer proof, holographic preview, design review sheet and font chart (screen images only)."""
from __future__ import annotations

import colorsys
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import Catalog, Preset, Size
from .geometry import shape_mask
from .orders import Order, spec_key
from .render import LabelSpec, RenderedLabel, Renderer, RenderError
from .text import FontError, GlyphError
from .uifont import UIFonts

if TYPE_CHECKING:
    from .production import Producer

INK = (34, 34, 48)
MUTED = (110, 110, 125)
RED = (205, 30, 30)
BG = (250, 248, 244)


# ---------------------------------------------------------------- effects
def holographic(img: Image.Image, strength: float = 0.55) -> Image.Image:
    """Simulated holographic sheen: rainbow soft-light blend + a diagonal sheen. Never printed."""
    a = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    diag = (xx + yy * 0.6) / (w + h * 0.6)
    hue = (diag * 1.6 + 0.05) % 1.0
    rgb = np.stack(np.vectorize(lambda t: colorsys.hsv_to_rgb(t, 0.5, 1.0), otypes=[float, float, float])(
        np.linspace(0, 1, 256)), axis=-1).astype(np.float32)
    rainbow = rgb[(hue * 255).astype(np.int32)]
    soft = (1 - 2 * rainbow) * a * a + 2 * rainbow * a          # soft-light (pegtop)
    out = a * (1 - strength) + soft * strength
    band = np.exp(-(((xx - yy * 0.8) / (w + h) - 0.15) / 0.07) ** 2)[..., None] * 0.35
    out = 1 - (1 - out) * (1 - band)                          # screen white sheen
    return Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8), "RGB")


def cut_out(lab: RenderedLabel, size: Size, bleed: float, px_per_mm: float, holo: bool = False,
            shadow: bool = True) -> Image.Image:
    """The label as the buyer sees it: cut to shape, with a soft shadow (RGBA)."""
    bw, bh = size.w + 2 * bleed, size.h + 2 * bleed
    W, H = int(round(bw * px_per_mm)), int(round(bh * px_per_mm))
    im = lab.image.resize((W, H), Image.Resampling.LANCZOS)
    if holo:
        im = holographic(im)
    dpi = px_per_mm * 25.4
    mask = shape_mask(size, 0.0, (bw, bh), (bleed, bleed), dpi, supersample=4).resize((W, H))
    pad = int(3 * px_per_mm)
    out = Image.new("RGBA", (W + 2 * pad, H + 2 * pad), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
        alpha = Image.new("L", out.size, 0)
        alpha.paste(mask.point(lambda v: int(v * 0.35)), (pad + int(0.5 * px_per_mm), pad + int(0.8 * px_per_mm)))
        sh.putalpha(alpha.filter(ImageFilter.GaussianBlur(px_per_mm * 0.9)))
        out = Image.alpha_composite(out, sh)
    face = im.convert("RGBA")
    face.putalpha(mask)
    out.alpha_composite(face, (pad, pad))
    return out


# ---------------------------------------------------------------- text helpers
def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if draw.textlength(t, font=font) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def _t(texts: dict, lang: str) -> dict:
    return texts.get(lang) or texts["en"]


CAPTION = (105, 100, 125)
SHEET_BG = (245, 244, 249)


def _flow(items: list[tuple[Image.Image, int, list[tuple[str, tuple]]]], width: int, ui: UIFonts,
          cap_size: int, gap: int = 24) -> tuple[list[tuple[Image.Image, int, int, int, list]], int]:
    """Left-aligned flow layout of (cut-out image, its shadow padding, captions).

    Returns (image, x, y, pad, captions) placements and the total height. x/y are
    where the label itself starts; captions go right under it.
    """
    f = ui.pil(cap_size, "bold")
    line_h = int(cap_size * 1.4)
    x = y = row_h = 0
    out = []
    for im, pad, captions in items:
        lw, lh = im.width - 2 * pad, im.height - 2 * pad
        cw = max([lw] + [int(f.getlength(c)) for c, _ in captions])
        ch = lh + 8 + len(captions) * line_h
        if x and x + cw > width:
            x, y, row_h = 0, y + row_h + gap, 0
        out.append((im, x, y, pad, captions))
        x += cw + gap
        row_h = max(row_h, ch)
    return out, y + row_h


def _paste_flow(img: Image.Image, flow, ox: int, oy: int, ui: UIFonts, cap_size: int) -> None:
    d = ImageDraw.Draw(img)
    f = ui.pil(cap_size, "bold")
    for im, x, y, pad, caps in flow:
        img.paste(im, (ox + x - pad, oy + y - pad), im)
        cy = oy + y + im.height - 2 * pad + 8
        for c, col in caps:
            d.text((ox + x, cy), c, font=f, fill=col)
            cy += int(cap_size * 1.4)


def proof_size_order(cat: Catalog) -> list[str]:
    """Largest strips first, then round and square (as on the review sheets)."""
    rect = sorted((s for s in cat.sizes.values() if s.is_rect), key=lambda s: -s.w * s.h)
    other = [s for s in cat.sizes.values() if not s.is_rect]
    other.sort(key=lambda s: (s.shape != "circle", s.w))
    return [s.id for s in rect + other]


# ---------------------------------------------------------------- customer proof
def customer_proof(producer: "Producer", order: Order, lang: str = "en", width: int = 1700) -> Image.Image:
    return customer_proof_image(producer.r, producer.ui, producer.texts, order, lang, width)


def customer_proof_image(r: Renderer, ui: UIFonts, texts: dict, order: Order, lang: str = "en",
                         width: int = 1700) -> Image.Image:
    """One of each unique label, grouped by design, as the buyer will see it."""
    cat = r.cat
    T = _t(texts, lang)
    rank = {s: i for i, s in enumerate(proof_size_order(cat))}
    unique: dict[str, LabelSpec] = {}
    for line in order.lines:
        for sid in cat.packs[line.pack].contents:
            spec = line.label_spec(sid)
            unique.setdefault(spec_key(spec), spec)
    by_design: dict[str, list[LabelSpec]] = {}
    for spec in sorted(unique.values(), key=lambda sp: (rank[sp.size], sp.name, sp.line2)):
        by_design.setdefault(spec.design, []).append(spec)

    ppm, cap = 9.0, 21
    margin = 40
    inner = width - 2 * margin
    sections = []
    for did, specs in by_design.items():
        items = []
        for spec in specs:
            size = cat.sizes[spec.size]
            im = cut_out(r.render(spec), size, cat.production.bleed, ppm, holo=spec.finish == "holographic")
            label = T.get("size_labels", {}).get(size.id, size.label)
            caption = T["proof_caption"].format(size=label, dims=size.dims_label,
                                                finish=T["finishes"].get(spec.finish, spec.finish))
            items.append((im, int(3 * ppm), [(caption, CAPTION)]))
        flow, fh = _flow(items, inner, ui, cap, gap=28)
        sections.append((r.design(did).name, flow, fh))

    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    title_f, body_f, bold_f, small_f, sec_f = (ui.pil(54, "bold"), ui.pil(26), ui.pil(28, "bold"),
                                               ui.pil(21), ui.pil(40, "bold"))
    names = []
    for ln in order.lines:
        n = ln.name.strip() + (f" / {ln.line2.strip()}" if ln.line2 else "")
        if n not in names:
            names.append(n)
    names_l = wrap(tmp, T["proof_names"].format(names=", ".join(names)), bold_f, inner)
    intro = wrap(tmp, T["proof_intro"], body_f, inner)
    footer = wrap(tmp, T["proof_footer"], small_f, inner)
    head_h = 70 + 44 + len(names_l) * 38 + 10 + len(intro) * 34 + 30
    body_h = sum(64 + fh + 40 for _, _, fh in sections)
    H = margin + head_h + body_h + len(footer) * 28 + margin

    img = Image.new("RGB", (width, H), SHEET_BG)
    d = ImageDraw.Draw(img)
    y = margin
    d.text((margin, y), T["proof_title"], font=title_f, fill=INK)
    y += 70
    d.text((margin, y), T["proof_order"].format(order=order.order_id), font=body_f, fill=MUTED)
    y += 44
    for ln in names_l:
        d.text((margin, y), ln, font=bold_f, fill=INK)
        y += 38
    y += 10
    for ln in intro:
        d.text((margin, y), ln, font=body_f, fill=INK)
        y += 34
    y += 30
    for title, flow, fh in sections:
        d.text((margin, y), title, font=sec_f, fill=INK)
        y += 64
        _paste_flow(img, flow, margin, y, ui, cap)
        y += fh + 40
    for ln in footer:
        d.text((margin, y), ln, font=small_f, fill=MUTED)
        y += 28
    return img


# ---------------------------------------------------------------- design review sheet
REVIEW_NAMES = [("Léo", ""), ("Maximilien", ""), ("Alexandre", "Tremblay-Gagnon")]


def review_sheet(r: Renderer, ui: UIFonts, design_id: str, font_id: int = 1, finish: str = "matte",
                 presets: dict[str, Preset] | None = None, width: int = 1700) -> Image.Image:
    """Every size with a short, a long and a two-line name; caption gives the cap height."""
    cat = r.cat
    design = r.design(design_id)
    ppm, cap = 9.0, 21
    margin = 40
    items = []
    for sid in proof_size_order(cat):
        size = cat.sizes[sid]
        preset = (presets or {}).get(sid)
        source = "saved preset" if (preset or sid in design.presets) else "automatic"
        for name, l2 in REVIEW_NAMES:
            spec = LabelSpec(design_id, sid, name, l2, font_id, finish)
            try:
                lab = r.render(spec, preset=preset)
                im = cut_out(lab, size, cat.production.bleed, ppm, holo=finish == "holographic")
                small = lab.min_cap_mm < cat.production.min_cap_mm
                caps = [(f"{size.label} - caps {' / '.join(f'{c:.1f}' for c in lab.cap_mm)} mm",
                         RED if small else CAPTION)]
                caps += [(w[:70], RED) for w in lab.warnings if "cap height" not in w]
            except (RenderError, GlyphError, FontError) as e:
                im = Image.new("RGBA", (int(size.w * ppm) + 54, int(size.h * ppm) + 54), (0, 0, 0, 0))
                ImageDraw.Draw(im).rectangle([27, 27, im.width - 28, im.height - 28], fill=(255, 225, 225, 255))
                caps = [(f"{size.label}: {str(e)[:70]}", RED)]
            if name == REVIEW_NAMES[0][0]:
                caps.append((source, MUTED))
            items.append((im, int(3 * ppm), caps))
    flow, fh = _flow(items, width - 2 * margin, ui, cap, gap=28)
    head = 110
    img = Image.new("RGB", (width, margin + head + fh + margin), SHEET_BG)
    d = ImageDraw.Draw(img)
    d.text((margin, margin), design.name, font=ui.pil(54, "bold"), fill=INK)
    d.text((margin, margin + 66), f"Font {font_id} · {cat.finishes[finish].label if finish in cat.finishes else finish}",
           font=ui.pil(24), fill=MUTED)
    _paste_flow(img, flow, margin, margin + head, ui, cap)
    return img


# ---------------------------------------------------------------- font chart
def font_chart(r: Renderer, ui: UIFonts, texts: dict, lang: str = "en", width: int = 2000) -> Image.Image:
    T = _t(texts, lang)
    sample = T.get("fontchart_sample", "Émilie-Rose")
    fonts = list(r.fonts.specs.values())
    cols = 2
    rows = (len(fonts) + cols - 1) // cols
    margin, row_h = 80, 150
    head = 120
    H = margin * 2 + head + rows * row_h
    img = Image.new("RGB", (width, H), BG)
    d = ImageDraw.Draw(img)
    tf = ui.pil(72, "bold")
    tw = d.textlength(T.get("fontchart_title", "Choose your font"), font=tf)
    d.text(((width - tw) / 2, margin - 10), T.get("fontchart_title", "Choose your font"), font=tf, fill=INK)
    col_w = (width - 2 * margin) // cols
    cap_px = 62
    for i, spec in enumerate(fonts):
        c, rr = divmod(i, rows)
        x = margin + c * col_w
        y = margin + head + rr * row_h
        d.ellipse([x, y + 20, x + 70, y + 90], fill=INK)
        num = str(spec.id)
        nf = ui.pil(36, "bold")
        nw = d.textlength(num, font=nf)
        d.text((x + 35 - nw / 2, y + 55), num, font=nf, fill="white", anchor="lm")
        try:
            lf = r.fonts.get(spec.id)
            size = int(cap_px / lf.cap_ratio)
            f = lf.at(size)
            while d.textlength(sample, font=f) > col_w - 130 and size > 10:
                size -= 4
                f = lf.at(size)
            d.text((x + 100, y + 55 + cap_px / 2), sample, font=f, fill=INK, anchor="ls")
        except FontError as e:
            d.text((x + 100, y + 30), str(e)[:60], font=ui.pil(22), fill=RED)
        d.text((x + 100, y + 108), spec.name, font=ui.pil(22), fill=MUTED)
    return img


def pack_table(cat: Catalog) -> tuple[dict[str, int], dict[str, int]]:
    from .packing import labels_per_sheet, sheets_for
    per = {sid: labels_per_sheet(s, cat.production) for sid, s in cat.sizes.items()}
    sheets = {pid: sheets_for(p.contents, cat.sizes, cat.production) for pid, p in cat.packs.items()}
    return per, sheets
