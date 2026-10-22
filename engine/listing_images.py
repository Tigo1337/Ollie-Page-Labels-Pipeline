"""Etsy listing images (2400 × 2400 PNG, like the binder pipeline's), made from the real label renders.

Per listing (a group of designs):
  Hero           a close-up of a sheet of the group's labels, turned at an angle (different names / fonts)
  Designs        "Choose your design": every design of the group, numbered like the Design drop-down
  Bundles        "Choose your bundle": each bundle's labels, with diagrams of its sheets
  Sizes          every label size, to scale, with its size in mm and inches
  Closeup_Small  a close-up of small, skinny pencil and clothing tag labels
  Closeup_Round  a close-up of round labels and shoe pairs
Shared by every listing:
  Fonts          "Choose your font": the numbered fonts with a sample name and the alphabet
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .config import Catalog, Size, hex_to_rgb
from .frames import to_printed
from .layout import current_layout
from .listings import IMAGE_VARIANTS, Group, asset_name
from .proofs import cut_out
from .render import LabelSpec, Renderer
from .uifont import UIFonts

BG = (250, 248, 244)
INK = (34, 34, 48)
MUTED = (110, 108, 125)
VINYL = (251, 251, 249)
NUMBER_COLOURS = [(214, 92, 120), (205, 64, 120), (98, 128, 214), (40, 150, 160), (122, 140, 40), (110, 70, 160),
                  (60, 140, 70), (40, 70, 150), (90, 90, 30), (214, 110, 60)]
RENDER_DPI = 400
HERO_FONTS = [1, 7, 12, 2, 9, 4, 11, 3]


class ListingImages:
    def __init__(self, renderer: Renderer, ui: UIFonts, cfg: dict, texts: dict | None = None,
                 layouts_dir: Path | None = None):
        self.r = renderer
        self.cat: Catalog = renderer.cat
        self.ui = ui
        self.cfg = cfg
        self.S = int(cfg.get("image_size", 2400))
        self.names = cfg.get("sample_names") or ["Emma", "Liam"]
        self.texts = texts or {}
        self.layouts_dir = layouts_dir

    # -- helpers ---------------------------------------------------------------
    def label(self, design: str, size_id: str, name: str, font: int = 1) -> Image.Image:
        """The label cut to shape (RGBA, with a soft shadow) at RENDER_DPI."""
        lab = self.r.render(LabelSpec(design, size_id, name, "", font, "matte"), dpi=RENDER_DPI)
        return cut_out(lab, self.cat.sizes[size_id], self.cat.sheet.bleed, RENDER_DPI / 25.4, shadow=True)

    def _scaled(self, im: Image.Image, size: Size, ppm: float) -> tuple[Image.Image, int]:
        """A cut_out image scaled to `ppm` px/mm; returns it and its shadow padding (px)."""
        k = ppm / (RENDER_DPI / 25.4)
        out = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.Resampling.LANCZOS)
        return out, round(3 * ppm)

    def _canvas(self, title: str | None = None, subtitle: str | None = None) -> tuple[Image.Image, int]:
        img = Image.new("RGB", (self.S, self.S), BG)
        y = 0
        if title:
            d = ImageDraw.Draw(img)
            f = self.ui.pil(int(self.S * 0.05), "bold")
            tw = d.textlength(title, font=f)
            d.text(((self.S - tw) / 2, self.S * 0.04), title, font=f, fill=INK)
            y = int(self.S * 0.04 + self.S * 0.065)
            if subtitle:
                f2 = self.ui.pil(int(self.S * 0.022))
                sw = d.textlength(subtitle, font=f2)
                d.text(((self.S - sw) / 2, y), subtitle, font=f2, fill=MUTED)
                y += int(self.S * 0.04)
            y += int(self.S * 0.02)
        return img, y

    def _sheet(self, rows: list[list[tuple[str, str, str, int]]], ppm: float, angle: float,
               gap_mm: float = 2.5) -> Image.Image:
        """A close-up of a label sheet: rows of labels (design, size, name, font) on white vinyl,
        turned by `angle` degrees, cropped to the square and lit softly from the top left."""
        S = self.S
        W = H = int(S * 1.55)
        sheet = Image.new("RGB", (W, H), VINYL)
        cache: dict[tuple, tuple[Image.Image, int]] = {}
        y = int(-0.4 * ppm * 10)
        r = 0
        while y < H:
            row = rows[r % len(rows)]
            size = self.cat.sizes[row[0][1]]
            x = int(-ppm * (size.w * 0.35 if r % 2 else size.w * 0.1))
            i = 0
            while x < W:
                design, sid, name, font = row[i % len(row)]
                key = (design, sid, name, font)
                if key not in cache:
                    cache[key] = self._scaled(self.label(design, sid, name, font), size, ppm)
                im, pad = cache[key]
                sheet.paste(im, (x - pad, y - pad), im)
                x += round((size.w + gap_mm) * ppm)
                i += 1
            y += round((size.h + gap_mm) * ppm)
            r += 1
        turned = sheet.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=VINYL)
        off = (W - S) // 2
        out = turned.crop((off, off, off + S, off + S))
        return _light(out)

    # -- the images ------------------------------------------------------------
    def hero(self, g: Group) -> Image.Image:
        rows = []
        for i, d in enumerate(g.designs[:8]):
            name = self.names[i % len(self.names)]
            rows.append([(d, "medium", name, HERO_FONTS[i % len(HERO_FONTS)])])
        return self._sheet(rows, ppm=self.S / 175, angle=-14)

    def closeup_small(self, g: Group) -> Image.Image:
        rows = []
        for i, d in enumerate(g.designs[:6]):
            name = self.names[(i + 3) % len(self.names)]
            sid = ("small", "pencil", "tag")[i % 3]
            rows.append([(d, sid, name, HERO_FONTS[(i + 2) % len(HERO_FONTS)])])
        return self._sheet(rows, ppm=self.S / 120, angle=12)

    def closeup_round(self, g: Group) -> Image.Image:
        rows = []
        for i, d in enumerate(g.designs[:6]):
            name = self.names[(i + 5) % len(self.names)]
            rows.append([(d, "round" if i % 2 == 0 else "shoe", name, HERO_FONTS[(i + 4) % len(HERO_FONTS)])])
        return self._sheet(rows, ppm=self.S / 150, angle=-10, gap_mm=3.0)

    def designs(self, g: Group) -> Image.Image:
        n = len(g.designs)
        img, top = self._canvas("Choose your design", f"{g.name} · {n} designs · the number matches the Design option")
        d = ImageDraw.Draw(img)
        margin = int(self.S * 0.05)
        size = self.cat.sizes["medium"]
        cap_h = self.S * 0.045                       # caption under each label
        lw, lh = size.w + 2 * self.cat.sheet.bleed + 6, size.h + 2 * self.cat.sheet.bleed + 6

        def fit(cols: int) -> float:                 # px per mm that fits `cols` columns
            rows = math.ceil(n / cols)
            cw, chh = (self.S - 2 * margin) / cols, (self.S - top - margin) / rows
            return min(cw * 0.92 / lw, (chh - cap_h) * 0.9 / lh)
        cols = max(range(1, 5), key=fit)
        rows = math.ceil(n / cols)
        ppm = fit(cols)
        cell_w = (self.S - 2 * margin) / cols
        cell_h = (self.S - top - margin) / rows
        name = self.names[1 % len(self.names)]
        cap = self.ui.pil(int(min(cap_h * 0.62, self.S * 0.026)), "bold")
        for i, did in enumerate(g.designs):
            c, rr = i % cols, i // cols
            cx = margin + c * cell_w + cell_w / 2
            cy = top + rr * cell_h + (cell_h - cap_h) / 2
            im, pad = self._scaled(self.label(did, "medium", name, 1), size, ppm)
            img.paste(im, (int(cx - im.width / 2), int(cy - im.height / 2)), im)
            caption = f"{i + 1}. {self.cat.designs[did].name}"
            tw = d.textlength(caption, font=cap)
            d.text((cx - tw / 2, cy + im.height / 2 - pad + cap_h * 0.15), caption, font=cap, fill=INK)
        return img

    def fonts(self) -> Image.Image:
        T = self.texts.get("en", {})
        sample = T.get("fontchart_sample", "Émilie-Rose")
        fonts = list(self.r.fonts.specs.values())
        img, top = self._canvas("Choose your font", "Write the font number in the personalization box")
        d = ImageDraw.Draw(img)
        margin = int(self.S * 0.045)
        cols = 2
        rows = math.ceil(len(fonts) / cols)
        col_w = (self.S - 2 * margin) / cols
        row_h = (self.S - top - margin) / rows
        num_f = self.ui.pil(int(row_h * 0.30), "bold")
        for i, spec in enumerate(fonts):
            c, rr = divmod(i, rows)
            x = margin + c * col_w
            y = top + rr * row_h
            colour = NUMBER_COLOURS[i % len(NUMBER_COLOURS)]
            num = f"{spec.id}."
            d.text((x, y + row_h * 0.42), num, font=num_f, fill=colour, anchor="ls")
            tx = x + d.textlength("17.", font=num_f) + row_h * 0.12
            avail = col_w - (tx - x) - row_h * 0.15
            lf = self.r.fonts.get(spec.id)
            # sample name, coloured
            size = int(row_h * 0.30 / lf.cap_ratio)
            f = lf.at(size)
            while d.textlength(sample, font=f) > avail and size > 8:
                size -= 2
                f = lf.at(size)
            d.text((tx, y + row_h * 0.42), sample, font=f, fill=colour, anchor="ls")
            # alphabet, lower then upper case
            for line, frac in (("abcdefghijklmnopqrstuvwxyz", 0.66), ("ABCDEFGHIJKLMNOPQRSTUVWXYZ", 0.88)):
                size = int(row_h * 0.13 / lf.cap_ratio)
                f = lf.at(size)
                while d.textlength(line, font=f) > avail and size > 8:
                    size -= 1
                    f = lf.at(size)
                d.text((tx, y + row_h * frac), line, font=f, fill=INK, anchor="ls")
        return img

    def bundles(self, g: Group) -> Image.Image:
        img, top = self._canvas("Choose your bundle")
        d = ImageDraw.Draw(img)
        packs = list(self.cat.packs.values())
        margin = int(self.S * 0.04)
        cols = 2
        rows = math.ceil(len(packs) / cols)
        gap = int(self.S * 0.015)
        cw = (self.S - 2 * margin - gap) / cols
        ch = (self.S - top - margin - (rows - 1) * gap) / rows
        title_f = self.ui.pil(int(ch * 0.17), "bold")
        body_f = self.ui.pil(int(ch * 0.12))
        colours = [_ink_colour(self.cat.designs[x]) for x in g.designs] or [INK]
        for i, p in enumerate(packs):
            c, rr = i % cols, i // cols
            x0 = margin + c * (cw + gap)
            y0 = top + rr * (ch + gap)
            d.rounded_rectangle([x0, y0, x0 + cw, y0 + ch], radius=int(ch * 0.08), fill=(255, 255, 255),
                                outline=(226, 222, 232), width=3)
            text_w = cw * 0.44 - ch * 0.12
            title = self.cfg["pack_short"].get(p.id, p.label)
            tf, ts = title_f, int(ch * 0.17)
            while d.textlength(title, font=tf) > text_w and ts > 12:
                ts -= 2
                tf = self.ui.pil(ts, "bold")
            d.text((x0 + ch * 0.12, y0 + ch * 0.12), title, font=tf, fill=INK)
            lines = []
            for sid, q in p.contents.items():
                s_ = self.cat.sizes[sid]
                word = "shoe pairs" if s_.shape == "pair" else s_.label.split(" (")[0].lower()
                lines.append(f"{q} {word}")
            if len(p.contents) == 1:                     # the title says it all: give the size instead
                lines = [_dims(self.cat.sizes[next(iter(p.contents))]).replace(" · ", "\n")]
                lines = lines[0].split("\n")
            bf, bs = body_f, int(ch * 0.12)
            while max(d.textlength(ln, font=bf) for ln in lines) > text_w and bs > 10:
                bs -= 1
                bf = self.ui.pil(bs)
            step = min(ch * 0.15, (ch * 0.84 - ch * 0.38) / max(1, len(lines)))
            if step < bs * 1.15:                     # too many lines: shrink to fit the card
                bs = max(10, int(step / 1.2))
                bf = self.ui.pil(bs)
            yy = y0 + ch * 0.38
            for ln in lines:
                d.text((x0 + ch * 0.12, yy), ln, font=bf, fill=MUTED)
                yy += step
            # the bundle's half sheets, as small diagrams
            halves = [sid for sid, q in p.contents.items() for _ in range(self._halves(sid, q))]
            per_row = min(3, max(1, len(halves)))
            n_rows = math.ceil(len(halves[:6]) / per_row)
            area_w, area_h = cw * 0.5, ch * 0.82
            hw = area_w / per_row
            scale = min(hw * 0.94 / 215.9, area_h / n_rows * 0.94 / 139.7)
            for j, sid in enumerate(halves[:6]):
                jj, jr = j % per_row, j // per_row
                hx = x0 + cw * 0.47 + jj * hw
                hy = y0 + ch * 0.09 + jr * (area_h / n_rows)
                self._half_diagram(d, sid, hx, hy, scale, colours[(i + j) % len(colours)])
        return img

    def sizes(self, g: Group) -> Image.Image:
        img, top = self._canvas("Label sizes", "Shown to scale")
        d = ImageDraw.Draw(img)
        margin = int(self.S * 0.06)
        order = [["large", "medium"], ["small", "pencil"], ["tag", "round"], ["shoe"]]
        caption_h = self.S * 0.075                      # name + dims under each row
        heights = sum(max(self.cat.sizes[x].h + 2 * self.cat.sheet.bleed for x in row) for row in order)
        ppm = min((self.S - 2 * margin) / (2 * 63.5 + 40),
                  (self.S - top - margin - len(order) * caption_h) / heights)
        cap = self.ui.pil(int(self.S * 0.02), "bold")
        sub = self.ui.pil(int(self.S * 0.017))
        y = top + self.S * 0.01
        k = 0
        for row in order:
            row_h = max(self.cat.sizes[s].h for s in row if s in self.cat.sizes) * ppm
            col_w = (self.S - 2 * margin) / len(row)
            for j, sid in enumerate(row):
                if sid not in self.cat.sizes:
                    continue
                s = self.cat.sizes[sid]
                did = g.designs[k % len(g.designs)]
                k += 1
                im, pad = self._scaled(self.label(did, sid, self.names[k % len(self.names)], 1), s, ppm)
                cx = margin + col_w * j + col_w / 2
                img.paste(im, (int(cx - im.width / 2), int(y + row_h / 2 - im.height / 2)), im)
                name = s.label.split(" (")[0]
                dims = _dims(s)
                for txt, f, col, dy in ((name, cap, INK, 0), (dims, sub, MUTED, self.S * 0.026)):
                    tw = d.textlength(txt, font=f)
                    d.text((cx - tw / 2, y + row_h + self.S * 0.012 + dy), txt, font=f, fill=col)
            y += row_h + caption_h
        return img

    # -- small parts -------------------------------------------------------------
    def _halves(self, sid: str, q: int) -> int:
        try:
            return max(1, q // current_layout(self.cat.sheet, self.cat.sizes[sid], self.layouts_dir).per_piece) \
                if self.layouts_dir else 1
        except ValueError:
            return 1

    def _half_diagram(self, d: ImageDraw.ImageDraw, sid: str, x0: float, y0: float, k: float,
                      colour: tuple[int, int, int]) -> None:
        """A half sheet (printed view, 215.9 × 139.7 mm) with its label cells."""
        W, H = 215.9, self.cat.sheet.paper_w / 2
        d.rounded_rectangle([x0, y0, x0 + W * k, y0 + H * k], radius=max(2, int(4 * k)), fill=(247, 246, 250),
                            outline=(200, 196, 210), width=2)
        if not self.layouts_dir:
            return
        size = self.cat.sizes[sid]
        lay = current_layout(self.cat.sheet, size, self.layouts_dir)
        light = tuple(int(c + (255 - c) * 0.45) for c in colour)
        from .layout import cell_labels
        for cell in lay.pieces[0]:
            for lab in cell_labels(cell, size, self.cat.sheet):
                px_, py, pw, ph = to_printed(*lab, studio_w=self.cat.sheet.paper_w)  # type: ignore[misc]
                box = [x0 + px_ * k, y0 + py * k, x0 + (px_ + pw) * k, y0 + (py + ph) * k]
                if size.shape == "circle":
                    d.ellipse(box, fill=light, outline=colour)
                else:
                    d.rounded_rectangle(box, radius=max(1, int(size.r * k)), fill=light, outline=colour)

    # -- all of a listing ------------------------------------------------------------
    def image(self, variant: str, g: Group | None) -> Image.Image:
        """One listing image by its IMAGE_VARIANTS name ("Fonts" is shared: `g` may be None)."""
        if variant == "Fonts":
            return self.fonts()
        makers = {"Hero": self.hero, "Designs": self.designs, "Bundles": self.bundles, "Sizes": self.sizes,
                  "Closeup_Small": self.closeup_small, "Closeup_Round": self.closeup_round}
        if variant not in makers or g is None:
            raise ValueError(f"Unknown listing image '{variant}'.")
        return makers[variant](g)

    def write_group(self, g: Group, out_dir: Path, shared: bool = True) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for variant, is_shared, _ in IMAGE_VARIANTS:
            if is_shared:
                continue
            p = out_dir / asset_name(self.cfg, g, variant)
            self.image(variant, g).save(p, optimize=False, compress_level=6)
            paths.append(p)
        if shared:
            paths.append(self.write_shared(out_dir))
        return paths

    def write_shared(self, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / asset_name(self.cfg, None, "Fonts")
        self.fonts().save(p, optimize=False, compress_level=6)
        return p


def _light(img: Image.Image) -> Image.Image:
    """Soft light from the top left and a slight vignette, so a flat render reads like a photo."""
    S = img.width
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32) / S
    light = 1.04 - 0.10 * (xx * 0.6 + yy * 0.4)
    vign = 1 - 0.10 * (((xx - 0.5) ** 2 + (yy - 0.5) ** 2) * 2.2)
    a = np.asarray(img, dtype=np.float32) * (light * vign)[..., None]
    out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")
    return out.filter(ImageFilter.UnsharpMask(radius=2, percent=40, threshold=2))


def _ink_colour(design) -> tuple[int, int, int]:
    """The design's name colour, or its outline colour when the name is printed in white."""
    fill = hex_to_rgb(design.fill)
    return fill if (0.2126 * fill[0] + 0.7152 * fill[1] + 0.0722 * fill[2]) < 215 else hex_to_rgb(design.stroke)


def _dims(s: Size) -> str:
    def inch(mm: float) -> str:
        return f"{round(mm / 25.4 * 16) / 16:.3f}".rstrip("0").rstrip(".")
    if s.shape == "circle":
        return f"{s.w:g} mm Ø · {inch(s.w)} in"
    if s.shape == "pair":
        ew = s.pair["each_w"]  # type: ignore[index]
        return f"2 × {ew:g} × {s.h:g} mm · {inch(ew)} × {inch(s.h)} in"
    return f"{s.w:g} × {s.h:g} mm · {inch(s.w)} × {inch(s.h)} in"


def _wrap_items(d: ImageDraw.ImageDraw, items: list[str], font, width: float) -> list[str]:
    lines, cur = [], ""
    for it in items:
        t = f"{cur}, {it}" if cur else it
        if cur and d.textlength(t, font=font) > width:
            lines.append(cur + ",")
            cur = it
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines
