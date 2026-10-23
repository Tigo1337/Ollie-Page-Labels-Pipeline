"""Etsy listing images (2400 × 2400 PNG) in the Mazie Page Creations brand, made from the real label renders.

Every image is laid out on a 1200 × 1200 grid (the Claude Design templates) and drawn at 2× (K = S / 1200).
Only things Pillow draws exactly are used: flat fills, rounded rectangles with a Plum outline and a Plum
"ledge" under them (a sticker look), circles, text in the two brand fonts, and pasted PNGs (the logo, the
icons, the label renders and the sheet close-ups). No gradients, blurs or blend modes.

Per listing (a group of designs), in gallery order:
  Hero        close-up of a sheet of the group's labels + a card with the group name, 4 chips, the logo mark
              and an "up to N labels" badge (key content inside the 4:3 band Etsy thumbnails keep)
  Designs     "Choose your design": numbered tiles, label render + design name
  Bundles     "Choose your bundle": the combo bundles as cards (the largest marked "Most complete") and the
              single-size bundles as pills
  Sizes       the 7 sizes at the same scale, with mm, inches and what each is for
  Durable     "Made to last": a close-up photo and 4 feature cards with the brand icons
  HowToOrder  the 3 ordering steps
Shared by every listing:
  Fonts       "Choose your font": the numbered fonts
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import Catalog, Size
from .listings import IMAGE_VARIANTS, Group, asset_name
from .proofs import cut_out
from .render import LabelSpec, Renderer
from .uifont import UIFonts

REPO = Path(__file__).resolve().parent.parent
BRAND_DIR = REPO / "brand"          # the contents of mazie-page-brand.zip (logo files, icons/)

# -- brand ------------------------------------------------------------------------------------------
PLUM = (0x3E, 0x23, 0x52)
LILAC = (0xC9, 0xB5, 0xF0)
BLUSH = (0xF5, 0xBF, 0xD0)
PEARL = (0xFB, 0xF7, 0xFB)
DISPLAY_FONT_ID = 1          # Fredoka (titles, numbers): weight 600, or 500 for small kickers
TEXT_FONT_ID = 3             # Nunito (text): weight 700, or 800 for bold
GRID = 1200                  # the templates' grid; everything below is in grid px
LEDGE = 8                    # the Plum ledge under every card
BORDER = 4                   # card outline
RENDER_DPI = 400
HERO_FONTS = [1, 7, 12, 2, 9, 4, 11, 3]

SIZE_ORDER = ["large", "medium", "small", "pencil", "tag", "round", "shoe"]
SIZE_COPY = {   # name on the images, the inch line (the sizes are inch-based), what it is for
    "large": ("Large", "2.5 × 1 in", "Books, bins, lunch bags"),
    "medium": ("Medium", "2.5 × 0.75 in", "Bottles, lunch boxes, folders"),
    "small": ("Small", "1.75 × 0.5 in", "Supplies, containers"),
    "pencil": ("Skinny", "2.25 × 0.375 in", "Pencils, markers, crayons"),
    "tag": ("Clothing tag", "1 × 0.5 in", "Care tags inside clothes"),
    "round": ("Round", "1.25 in", "Lids, caps, toys"),
    "shoe": ("Shoe pair", "2 × (1.2 × 1.5 in)", "Left and right, one picture"),
}
COUNT_WORD = {"pencil": "Skinny", "small": "Small", "medium": "Medium", "large": "Large",
              "tag": "Clothing tags", "round": "Round", "shoe": "Shoe pairs"}
PILL_WORD = dict(COUNT_WORD, tag="Tags")
FEATURES = [  # (title, text, icon file)
    ("Waterproof laminate", "A clear layer over the ink keeps out water, juice and scratches.", "icons/icon-waterproof_256.png"),
    ("Peel and stick", "Precisely cut, easy to peel. Sticks to plastic, glass, metal and wood.", "icons/icon-peel_256.png"),
    ("Big, bold names", "Names little ones can spot on their own things, before they can read.", "icons/icon-heart_256.png"),
    ("Made in Québec", "Printed, laminated and cut to order, then mailed flat in an envelope.", "icons/icon-quebec_256.png"),
]


class ListingImages:
    def __init__(self, renderer: Renderer, ui: UIFonts, cfg: dict, texts: dict | None = None,
                 layouts_dir: Path | None = None, brand_dir: Path = BRAND_DIR):
        self.r = renderer
        self.cat: Catalog = renderer.cat
        self.ui = ui
        self.cfg = cfg
        self.S = int(cfg.get("image_size", 2400))
        self.K = self.S / GRID
        self.names = cfg.get("sample_names") or ["Liam", "Emma"]
        self.texts = texts or {}
        self.layouts_dir = layouts_dir
        self.brand_dir = Path(brand_dir)
        self._fonts: dict[tuple, ImageFont.FreeTypeFont] = {}
        self._pngs: dict[str, Image.Image] = {}

    # -- primitives (grid px in, output px out) -------------------------------------------------------
    def px(self, v: float) -> int:
        return int(round(v * self.K))

    def font(self, kind: str, size: float, weight: int) -> ImageFont.FreeTypeFont:
        """kind "display" (Fredoka) or "text" (Nunito), at `size` grid px and a `weight` (variable axis)."""
        key = (kind, size, weight)
        if key not in self._fonts:
            lf = self.r.fonts.get(DISPLAY_FONT_ID if kind == "display" else TEXT_FONT_ID)
            f = ImageFont.truetype(str(lf.path), self.px(size))
            if lf.axes:
                f.set_variation_by_axes([float(weight) if tag == "wght" else default
                                         for tag, lo, default, hi in lf.axes])
            self._fonts[key] = f
        return self._fonts[key]

    def png(self, name: str) -> Image.Image:
        if name not in self._pngs:
            self._pngs[name] = Image.open(self.brand_dir / name).convert("RGBA")
        return self._pngs[name]

    def paste(self, img: Image.Image, im: Image.Image, x: float, y: float, w: float, h: float,
              align: str = "center") -> None:
        """Paste `im` scaled to fit inside the grid box (x, y, w, h), keeping its aspect."""
        W, H = self.px(w), self.px(h)
        k = min(W / im.width, H / im.height)
        sm = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.Resampling.LANCZOS)
        ox = self.px(x) + (0 if align == "left" else (W - sm.width) // 2)
        oy = self.px(y) + (H - sm.height) // 2
        img.paste(sm, (ox, oy), sm if sm.mode == "RGBA" else None)

    def card(self, d: ImageDraw.ImageDraw, x: float, y: float, w: float, h: float, r: float,
             fill=PEARL, border: float = BORDER, ledge: float = LEDGE) -> None:
        """A sticker card: a Plum ledge, then the card with a Plum outline."""
        if ledge:
            d.rounded_rectangle(self.box(x, y + ledge, w, h), radius=self.px(r), fill=PLUM)
        d.rounded_rectangle(self.box(x, y, w, h), radius=self.px(r), fill=fill,
                            outline=PLUM if border else None, width=self.px(border) if border else 0)

    def box(self, x: float, y: float, w: float, h: float) -> list[int]:
        return [self.px(x), self.px(y), self.px(x + w) - 1, self.px(y + h) - 1]

    def text(self, d: ImageDraw.ImageDraw, x: float, y: float, s: str, font, fill=PLUM, align: str = "left",
             width: float | None = None, spacing: float = 0.0) -> None:
        """Text whose 1-line box (line height = font size) has its top-left at grid (x, y). align "center"
        centres it in `width`. `spacing` = extra letter spacing in em (spaced capitals)."""
        size = font.size / self.K
        cy = self.px(y + size / 2)
        if spacing:
            tw = sum(d.textlength(c, font=font) for c in s) + spacing * font.size * (len(s) - 1)
        else:
            tw = d.textlength(s, font=font)
        x0 = self.px(x) + ((self.px(width) - tw) / 2 if align == "center" and width else 0)
        if not spacing:
            d.text((x0, cy), s, font=font, fill=fill, anchor="lm")
            return
        for c in s:
            d.text((x0, cy), c, font=font, fill=fill, anchor="lm")
            x0 += d.textlength(c, font=font) + spacing * font.size

    def wrap(self, d, s: str, font, width: float) -> list[str]:
        words, lines, cur = s.split(), [], ""
        for w in words:
            t = f"{cur} {w}".strip()
            if cur and d.textlength(t, font=font) > self.px(width):
                lines.append(cur)
                cur = w
            else:
                cur = t
        return lines + ([cur] if cur else [])

    def paragraph(self, d, x: float, y: float, s: str, font, width: float, line: float = 1.35, fill=PLUM) -> float:
        """Wrapped text from grid (x, y); returns the y below it."""
        size = font.size / self.K
        for i, ln in enumerate(self.wrap(d, s, font, width)):
            self.text(d, x, y + i * size * line + size * (line - 1) / 2, ln, font, fill)
        return y + len(self.wrap(d, s, font, width)) * size * line

    def fit_font(self, d, s: str, kind: str, size: float, weight: int, width: float, min_size: float = 14):
        f = self.font(kind, size, weight)
        while d.textlength(s, font=f) > self.px(width) and size > min_size:
            size -= 1
            f = self.font(kind, size, weight)
        return f

    def number(self, d, x: float, y: float, dia: float, n, size: float, ring: float = 0) -> None:
        d.ellipse(self.box(x, y, dia, dia), fill=PLUM, outline=PEARL if ring else None,
                  width=self.px(ring) if ring else 0)
        f = self.font("display", size, 600)
        d.text((self.px(x + dia / 2), self.px(y + dia / 2)), str(n), font=f, fill=PEARL, anchor="mm")

    def canvas(self, bg) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("RGB", (self.S, self.S), bg)
        return img, ImageDraw.Draw(img)

    def heading(self, d, title: str, subtitle: str | None) -> None:
        self.text(d, 0, 60, title, self.fit_font(d, title, "display", 72, 600, 1080), align="center", width=GRID)
        if subtitle:
            self.text(d, 0, 150, subtitle, self.fit_font(d, subtitle, "text", 24, 800, 1080), align="center",
                      width=GRID)

    def footer(self, img: Image.Image) -> None:
        self.paste(img, self.png("mazie-page-logo-horizontal_2400.png"), 490, 1104, 220, 56)

    # -- label renders ----------------------------------------------------------------------------------
    def label(self, design: str, size_id: str, name: str, font: int = 1) -> Image.Image:
        """The label cut to shape (RGBA, soft shadow, ~4.2 mm of padding each side) at RENDER_DPI."""
        lab = self.r.render(LabelSpec(design, size_id, name, "", font, "matte"), dpi=RENDER_DPI)
        return cut_out(lab, self.cat.sizes[size_id], self.cat.sheet.bleed, RENDER_DPI / 25.4, shadow=True)

    def at_scale(self, im: Image.Image, ppm_grid: float) -> Image.Image:
        """A label render at `ppm_grid` grid px per mm (so every size shares one scale)."""
        k = ppm_grid * self.K / (RENDER_DPI / 25.4)
        return im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.Resampling.LANCZOS)

    def _sheet(self, rows: list[list[tuple[str, str, str, int]]], ppm: float, angle: float,
               gap_mm: float = 2.5) -> Image.Image:
        """A close-up of a label sheet: rows of labels (design, size, name, font) on white vinyl, turned by
        `angle` degrees, cropped to the square and lit softly from the top left. (`ppm` in output px.)"""
        S = self.S
        W = H = int(S * 1.55)
        sheet = Image.new("RGB", (W, H), (251, 251, 249))
        cache: dict[tuple, Image.Image] = {}
        y = int(-0.4 * ppm * 10)
        r = 0
        while y < H:
            row = rows[r % len(rows)]
            size = self.cat.sizes[row[0][1]]
            x = int(-ppm * (size.w * 0.35 if r % 2 else size.w * 0.1))
            i = 0
            while x < W:
                key = row[i % len(row)]
                if key not in cache:
                    k = ppm / (RENDER_DPI / 25.4)
                    im = self.label(*key)
                    cache[key] = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))),
                                           Image.Resampling.LANCZOS)
                im = cache[key]
                pad = round(3 * ppm)
                sheet.paste(im, (x - pad, y - pad), im)
                x += round((size.w + gap_mm) * ppm)
                i += 1
            y += round((size.h + gap_mm) * ppm)
            r += 1
        turned = sheet.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=(251, 251, 249))
        off = (W - S) // 2
        return _light(turned.crop((off, off, off + S, off + S)))

    # -- data -----------------------------------------------------------------------------------------
    def pack_labels(self, p) -> int:
        """Labels in a pack, a shoe pair counting as 2."""
        return sum(q * (2 if self.cat.sizes[s].shape == "pair" else 1) for s, q in p.contents.items())

    def pack_title(self, p) -> str:
        t = self.cfg.get("pack_short", {}).get(p.id, p.label)
        return re.sub(r"\s*\(.*?\)\s*", "", t).replace(" pack", "").strip()

    # -- the images ---------------------------------------------------------------------------------------
    def hero(self, g: Group) -> Image.Image:
        rows = [[(dd, "medium", self.names[i % len(self.names)], HERO_FONTS[i % len(HERO_FONTS)])]
                for i, dd in enumerate(g.designs[:8])]
        img = self._sheet(rows, ppm=self.S / 175, angle=-14)
        d = ImageDraw.Draw(img)
        # badge, top right (inside the 4:3 thumbnail band: y 150-1050)
        most = max((self.pack_labels(p) for p in self.cat.packs.values()), default=0)
        d.ellipse(self.box(930, 170, 210, 210), fill=BLUSH, outline=PLUM, width=self.px(BORDER))
        self.text(d, 930, 210, "up to", self.font("display", 26, 500), align="center", width=210)
        self.text(d, 930, 238, str(most), self.font("display", 80, 600), align="center", width=210)
        self.text(d, 930, 318, "labels", self.font("display", 26, 500), align="center", width=210)
        # the card
        self.card(d, 60, 780, 1080, 262, 32)
        self.text(d, 96, 810, "PERSONALIZED NAME LABELS", self.font("text", 22, 800), spacing=0.16)
        self.text(d, 94, 844, g.name, self.fit_font(d, g.name, "display", 76, 600, 800))
        chips = ["Waterproof", f"{len(self.cat.sizes)} sizes", f"{len(self.cat.fonts)} fonts", "Made in Québec"]
        x = 96
        f = self.font("text", 22, 800)
        for i, c in enumerate(chips):
            w = d.textlength(c, font=f) / self.K + 44
            d.rounded_rectangle(self.box(x, 948, w, 52), radius=self.px(26),
                                fill=BLUSH if i == len(chips) - 1 else LILAC, outline=PLUM, width=self.px(3))
            self.text(d, x, 948 + 15, c, f, align="center", width=w)
            x += w + 14
        self.paste(img, self.png("mazie-page-mark_1024.png"), 966, 818, 140, 175)
        return img

    def designs(self, g: Group) -> Image.Image:
        img, d = self.canvas(LILAC)
        n = len(g.designs)
        self.heading(d, "Choose your design", f"{g.name} · the number matches the Design option")
        rows = max(1, math.ceil(n / 2))
        pitch = min(176.0, (1072 - 210) / rows)
        th = pitch - LEDGE - 18                       # tile height (150 for up to 10 designs)
        top = 210 + (1072 - 210 - rows * pitch) / 2   # centre a shorter grid
        name = self.names[1 % len(self.names)]
        for i, did in enumerate(g.designs):
            x = 60 + (i % 2) * 550
            y = top + (i // 2) * pitch
            self.card(d, x, y, 530, th, 24)
            k = th / 150
            self.paste(img, self.label(did, "medium", name), x + 12, y + 11 * k, 316 * k, 120 * k, align="left")
            self.number(d, x + 6, y + 6 * k, 50 * k, i + 1, 24 * k, ring=3)
            # the design name in the column on the right: up to 2 lines, shrinking to fit
            title = self.cat.designs[did].name
            size = 28 * k
            while True:
                f = self.font("display", size, 600)
                lines = self.wrap(d, title, f, 176)
                if (len(lines) <= 2 and all(d.textlength(ln, font=f) <= self.px(176) for ln in lines)) or size < 14:
                    break
                size -= 1
            lh = size * 1.1
            y0 = y + (th - len(lines) * lh) / 2 + (lh - size) / 2
            for j, ln in enumerate(lines):
                self.text(d, x + 340, y0 + j * lh, ln, f)
        self.footer(img)
        return img

    def bundles(self, g: Group) -> Image.Image:
        img, d = self.canvas(BLUSH)
        self.heading(d, "Choose your bundle", "Every label has the same name, design and font")
        combos = [p for p in self.cat.packs.values() if len(p.contents) > 1]
        singles = [p for p in self.cat.packs.values() if len(p.contents) == 1]
        best = max(combos, key=self.pack_labels) if combos else None
        n = max(1, len(combos))
        cw = (1080 - (n - 1) * 24) / n
        for i, p in enumerate(combos):
            x = 60 + i * (cw + 24)
            self.card(d, x, 230, cw, 590, 28, fill=LILAC if p is best else PEARL)
            self.text(d, x + 26, 260, self.pack_title(p), self.fit_font(d, self.pack_title(p), "display", 36, 600,
                                                                         cw - 52))
            total = str(self.pack_labels(p))
            fnum = self.font("display", 88, 600)
            self.text(d, x + 24, 310, total, fnum)
            self.text(d, x + 32 + d.textlength(total, font=fnum) / self.K, 358, "labels", self.font("text", 24, 800))
            rect_sizes = [s for s in p.contents if self.cat.sizes[s].shape == "rrect"]
            big = max(rect_sizes, key=lambda s: self.cat.sizes[s].w * self.cat.sizes[s].h) if rect_sizes \
                else next(iter(p.contents))
            small = next((s for s in ("pencil", "tag") if s in p.contents and s != big), None) or \
                min(p.contents, key=lambda s: self.cat.sizes[s].w * self.cat.sizes[s].h)
            nm = self.names[(i + 2) % len(self.names)]
            self.paste(img, self.label(g.designs[i % len(g.designs)], big, nm), x + 14, 412, cw - 44, 92,
                       align="left")
            self.paste(img, self.label(g.designs[(i + 1) % len(g.designs)], small, nm), x + 70, 498, cw - 104,
                       74, align="left")
            d.line([self.px(x + 26), self.px(587), self.px(x + cw - 26), self.px(587)], fill=PLUM,
                   width=self.px(3))
            f = self.font("text", 22, 700)
            fb = self.font("text", 22, 800)
            items = sorted(p.contents.items(), key=lambda kv: -kv[1])
            for j, (sid, q) in enumerate(items):
                yy = 608 + j * 30
                self.text(d, x + 26, yy, COUNT_WORD.get(sid, sid), f)
                qs = str(q)
                d.text((self.px(x + cw - 26), self.px(yy + 11)), qs, font=fb, fill=PLUM, anchor="rm")
            if p is best:
                bw = 220
                d.rounded_rectangle(self.box(x + (cw - bw) / 2, 210, bw, 40), radius=self.px(20), fill=PLUM)
                self.text(d, x + (cw - bw) / 2, 210 + 11, "MOST COMPLETE", self.font("text", 18, 800), fill=PEARL,
                          align="center", width=bw, spacing=0.08)
        if singles:
            self.text(d, 0, 862, "Or one size, a full sheet", self.font("display", 32, 600), align="center",
                      width=GRID)
            m = len(singles)
            pw = (1080 - (m - 1) * 12) / m
            for i, p in enumerate(singles):
                x = 60 + i * (pw + 12)
                sid, q = next(iter(p.contents.items()))
                self.card(d, x, 922, pw, 112, 22, ledge=0)
                self.text(d, x, 938, str(q), self.font("display", 42, 600), align="center", width=pw)
                self.text(d, x, 988, PILL_WORD.get(sid, sid), self.fit_font(d, PILL_WORD.get(sid, sid), "text", 18,
                                                                              800, pw - 16), align="center", width=pw)
        self.footer(img)
        return img

    def sizes(self, g: Group) -> Image.Image:
        img, d = self.canvas(LILAC)
        self.heading(d, f"{len(self.cat.sizes)} sizes, shown to scale", "All at the same scale, so you can compare them")
        self.card(d, 60, 210, 1080, 852, 32)
        ppm = 3.4
        order = [s for s in SIZE_ORDER if s in self.cat.sizes] + [s for s in self.cat.sizes if s not in SIZE_ORDER]
        for i, sid in enumerate(order[:7]):
            s = self.cat.sizes[sid]
            cx, cy = 90 + (i % 2) * 510, 236 + (i // 2) * 200
            im = self.at_scale(self.label(g.designs[i % len(g.designs)], sid, self.names[(i + 1) % len(self.names)]),
                               ppm)
            img.paste(im, (self.px(cx + 125) - im.width // 2, self.px(cy + 100) - im.height // 2), im)
            mm, inch = _dims(s)
            title, inch, use = SIZE_COPY.get(sid, (s.label, inch, ""))
            self.text(d, cx + 268, cy + 36, title, self.font("display", 30, 600))
            fb = self.font("text", 19, 800)
            self.text(d, cx + 268, cy + 76, mm, fb)
            self.text(d, cx + 268, cy + 101, inch, fb)
            self.paragraph(d, cx + 268, cy + 130, use, self.font("text", 19, 700), 230, line=1.3)
        # the 8th cell: a pointer to the bundle with every size
        combos = [p for p in self.cat.packs.values() if len(p.contents) > 1]
        allp = next((p for p in combos if len(p.contents) >= len(self.cat.sizes)), None)
        d.rounded_rectangle(self.box(620, 852, 480, 168), radius=self.px(24), fill=LILAC, outline=PLUM,
                            width=self.px(3))
        self.text(d, 646, 880, "Not sure which size?", self.font("display", 30, 600))
        msg = (f"The {self.pack_title(allp)} bundle has all {len(self.cat.sizes)}, with extra clothing tags."
               if allp else "Start with a bundle: it mixes the most useful sizes.")
        self.paragraph(d, 646, 926, msg, self.font("text", 21, 700), 420)
        self.footer(img)
        return img

    def fonts(self) -> Image.Image:
        img, d = self.canvas(BLUSH)
        self.heading(d, "Choose your font", "Write the font number in the personalization box")
        self.card(d, 60, 210, 1080, 852, 32)
        sample = self.texts.get("en", {}).get("fontchart_sample", "Émilie-Rose")
        specs = list(self.r.fonts.specs.values())
        per_col = math.ceil(len(specs) / 2)
        rh = min(88.0, 800 / per_col)
        for i, spec in enumerate(specs):
            col, row = divmod(i, per_col)
            x, y = (100, 640)[col], 240 + row * rh
            self.number(d, x, y + (rh - 46) / 2, 46, spec.id, 22)
            lf = self.r.fonts.get(spec.id)
            size = 44.0
            f = lf.at(self.px(size))
            while d.textlength(sample, font=f) > self.px(420) and size > 16:
                size -= 1
                f = lf.at(self.px(size))
            d.text((self.px(x + 66), self.px(y + rh / 2)), sample, font=f, fill=PLUM, anchor="lm")
        if len(specs) % 2:
            self.paragraph(d, 640, 240 + per_col * rh - rh + 18, "Accents, hyphens and a second line are all welcome",
                           self.font("text", 20, 800), 460, line=1.3)
        self.footer(img)
        return img

    def durable(self, g: Group) -> Image.Image:
        img, d = self.canvas(PEARL)
        rows = []
        for i, dd in enumerate(g.designs[:6]):
            sid = ("small", "pencil", "tag")[i % 3]
            rows.append([(dd, sid, self.names[(i + 3) % len(self.names)], HERO_FONTS[(i + 2) % len(HERO_FONTS)])])
        photo = self._sheet(rows, ppm=self.S / 120, angle=12)
        crop_h = round(self.S * 540 / GRID)
        top = (self.S - crop_h) // 2
        img.paste(photo.crop((0, top, self.S, top + crop_h)), (0, 0))
        d.rectangle(self.box(0, 540, GRID, 4), fill=PLUM)
        self.card(d, 60, 462, 420, 118, 28, fill=BLUSH)
        self.text(d, 60, 488, "Made to last", self.font("display", 60, 600), align="center", width=420)
        for i, (title, body, icon) in enumerate(FEATURES):
            x, y = 60 + (i % 2) * 552, 616 + (i // 2) * 240
            self.card(d, x, y, 528, 216, 28)
            d.rounded_rectangle(self.box(x + 24, y + 26, 104, 104), radius=self.px(26), fill=LILAC)
            self.paste(img, self.png(icon), x + 30, y + 32, 92, 92)
            self.text(d, x + 152, y + 30, title, self.fit_font(d, title, "display", 34, 600, 356))
            self.paragraph(d, x + 152, y + 80, body, self.font("text", 22, 700), 344)
        self.footer(img)
        return img

    def how_to_order(self, g: Group) -> Image.Image:
        img, d = self.canvas(BLUSH)
        self.heading(d, "How to order", "Three steps, about a minute")
        combos = [p for p in self.cat.packs.values() if len(p.contents) > 1]
        best = max(combos, key=self.pack_labels) if combos else next(iter(self.cat.packs.values()))
        steps = ["Pick a design and a bundle", "Type the name and the font number", "We print, laminate and cut"]
        for i, t in enumerate(steps):
            y = 210 + i * 280
            self.card(d, 60, y, 1080, 262, 28)
            self.number(d, 92, y + 79, 96, i + 1, 54)
            self.text(d, 220, y + 40, t, self.font("display", 40, 600))
        f = self.font("text", 23, 800)
        for x, label in ((220, f"Design: 1. {self.cat.designs[g.designs[0]].name}"),
                         (660, f"Bundle: {self.pack_title(best)}")):
            d.rounded_rectangle(self.box(x, 330, 420, 66), radius=self.px(18), fill=LILAC, outline=PLUM,
                                width=self.px(3))
            self.text(d, x + 20, 352, label, self.fit_font(d, label, "text", 23, 800, 340))
            cx, cy = x + 388, 363                    # the drop-down chevron
            d.line([(self.px(cx - 6), self.px(cy - 3)), (self.px(cx), self.px(cy + 3)), (self.px(cx + 6), self.px(cy - 3))],
                   fill=PLUM, width=self.px(3), joint="curve")
        d.rounded_rectangle(self.box(220, 604, 860, 96), radius=self.px(18), fill=LILAC, outline=PLUM,
                            width=self.px(3))
        self.text(d, 240, 620, "ADD YOUR PERSONALIZATION", self.font("text", 16, 800), spacing=0.1)
        self.text(d, 240, 648, f"{self.names[1 % len(self.names)]} Tremblay - font 3", self.font("text", 32, 700))
        ship = self.cfg.get("ship_time", "[X] business days")
        self.paragraph(d, 220, 878, f"Your labels ship flat in an envelope within {ship}.",
                       self.font("text", 25, 700), 520)
        self.paste(img, self.label(g.designs[0], "medium", self.names[1 % len(self.names)]), 770, 832, 340, 130)
        self.footer(img)
        return img

    # -- all of a listing --------------------------------------------------------------------------------
    def image(self, variant: str, g: Group | None) -> Image.Image:
        """One listing image by its IMAGE_VARIANTS name ("Fonts" is shared: `g` may be None)."""
        if variant == "Fonts":
            return self.fonts()
        makers = {"Hero": self.hero, "Designs": self.designs, "Bundles": self.bundles, "Sizes": self.sizes,
                  "Durable": self.durable, "HowToOrder": self.how_to_order}
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


def _dims(s: Size) -> tuple[str, str]:
    """(mm line, inch line) for the Sizes image; SIZE_COPY's inch labels take precedence."""
    def inch(mm: float) -> str:
        return f"{mm / 25.4:.2f}".rstrip("0").rstrip(".")
    if s.shape == "circle":
        return f"{s.w:g} mm", f"{inch(s.w)} in"
    if s.shape == "pair":
        ew = s.pair["each_w"]  # type: ignore[index]
        return f"2 × ({ew:g} × {s.h:g} mm)", f"2 × ({inch(ew)} × {inch(s.h)} in)"
    return f"{s.w:g} × {s.h:g} mm", f"{inch(s.w)} × {inch(s.h)} in"
