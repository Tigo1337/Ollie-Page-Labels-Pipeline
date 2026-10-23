"""Mazie Page Creations: logo mark, word mark, lockups and icon as SVG (text as outlines) + PNG.

usage: python3 build_logo.py <fredoka.ttf> <out_dir>
"""
import io
import math
import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

# The palette: Plum, Lilac, Blush, Pearl. BLUSH_DEEP is a deeper tone of Blush, used only for the
# heart on the i and the cheeks, so they still show on Pearl and on the Lilac page.
PLUM, LILAC, BLUSH, BLUSH_DEEP, PEARL = "#3E2352", "#C9B5F0", "#F5BFD0", "#EFA3BF", "#FBF7FB"
WHITE = "#FFFFFF"

FONT_PATH, OUT = sys.argv[1], Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)


def instance(wght):
    f = TTFont(FONT_PATH)
    return instantiateVariableFont(f, {"wght": wght, "wdth": 100})


FONTS = {600: instance(600), 500: instance(500)}


def text_paths(text, size, wght=600, tracking=0.0):
    """SVG path data for `text` with its baseline at y=0, starting at x=0. Returns (d, width, glyph_x)."""
    f = FONTS[wght]
    upm = f["head"].unitsPerEm
    k = size / upm
    cmap = f.getBestCmap()
    gs = f.getGlyphSet()
    hmtx = f["hmtx"]
    x = 0.0
    ds, xs = [], []
    for ch in text:
        g = cmap[ord(ch)]
        pen = SVGPathPen(gs)
        gs[g].draw(TransformPen(pen, (k, 0, 0, -k, x, 0)))
        ds.append(pen.getCommands())
        xs.append((x, hmtx[g][0] * k))
        x += hmtx[g][0] * k + tracking * size
    width = x - tracking * size
    return " ".join(d for d in ds if d), width, xs


def heart(cx, cy, s, fill):
    """A plump heart of width s centred at (cx, cy)."""
    w, h = s, s * 0.9
    x0, y0 = cx - w / 2, cy - h / 2
    d = (f"M{cx:.2f} {y0 + h:.2f} "
         f"C{x0 + w * 0.12:.2f} {y0 + h * 0.66:.2f} {x0 - w * 0.02:.2f} {y0 + h * 0.38:.2f} {x0 + w * 0.06:.2f} {y0 + h * 0.18:.2f} "
         f"C{x0 + w * 0.16:.2f} {y0 - h * 0.04:.2f} {x0 + w * 0.42:.2f} {y0 - h * 0.02:.2f} {cx:.2f} {y0 + h * 0.22:.2f} "
         f"C{x0 + w * 0.58:.2f} {y0 - h * 0.02:.2f} {x0 + w * 0.84:.2f} {y0 - h * 0.04:.2f} {x0 + w * 0.94:.2f} {y0 + h * 0.18:.2f} "
         f"C{x0 + w * 1.02:.2f} {y0 + h * 0.38:.2f} {x0 + w * 0.88:.2f} {y0 + h * 0.66:.2f} {cx:.2f} {y0 + h:.2f} Z")
    return f'<path d="{d}" fill="{fill}"/>'


def sparkle(cx, cy, r, fill, stroke=None, sw=0):
    d = (f"M{cx} {cy - r} C{cx + r * 0.12} {cy - r * 0.12} {cx + r * 0.12} {cy - r * 0.12} {cx + r} {cy} "
         f"C{cx + r * 0.12} {cy + r * 0.12} {cx + r * 0.12} {cy + r * 0.12} {cx} {cy + r} "
         f"C{cx - r * 0.12} {cy + r * 0.12} {cx - r * 0.12} {cy + r * 0.12} {cx - r} {cy} "
         f"C{cx - r * 0.12} {cy - r * 0.12} {cx - r * 0.12} {cy - r * 0.12} {cx} {cy - r} Z")
    s = f' stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round"' if stroke else ""
    return f'<path d="{d}" fill="{fill}"{s}/>'


# ---------------------------------------------------------------------------
# The mark: a little page with a folded corner and a kawaii face (viewBox 0 0 200 200)
# ---------------------------------------------------------------------------
def mark(colors=None, sparkle_on=False):
    c = {"line": PLUM, "page": LILAC, "fold": BLUSH, "cheek": BLUSH_DEEP, "spark": BLUSH, "face": PLUM}
    c.update(colors or {})
    sw = 9
    x0, y0, x1, y1, r, f = 46, 30, 162, 178, 24, 38
    page = (f"M{x0 + r} {y0} L{x1 - f} {y0} L{x1} {y0 + f} L{x1} {y1 - r} "
            f"Q{x1} {y1} {x1 - r} {y1} L{x0 + r} {y1} Q{x0} {y1} {x0} {y1 - r} "
            f"L{x0} {y0 + r} Q{x0} {y0} {x0 + r} {y0} Z")
    fold = f"M{x1 - f} {y0} L{x1 - f} {y0 + f - 8} Q{x1 - f} {y0 + f} {x1 - f + 8} {y0 + f} L{x1} {y0 + f} Z"
    cx = (x0 + x1) / 2 + 2
    ey = 112
    parts = [
        f'<path d="{page}" fill="{c["page"]}" stroke="{c["line"]}" stroke-width="{sw}" stroke-linejoin="round"/>',
        f'<path d="{fold}" fill="{c["fold"]}" stroke="{c["line"]}" stroke-width="{sw}" stroke-linejoin="round"/>',
        f'<ellipse cx="{cx - 22}" cy="{ey + 20}" rx="11" ry="7" fill="{c["cheek"]}"/>' if c["cheek"] else "",
        f'<ellipse cx="{cx + 22}" cy="{ey + 20}" rx="11" ry="7" fill="{c["cheek"]}"/>' if c["cheek"] else "",
        f'<ellipse cx="{cx - 17}" cy="{ey}" rx="7" ry="9.5" fill="{c["face"]}"/>',
        f'<ellipse cx="{cx + 17}" cy="{ey}" rx="7" ry="9.5" fill="{c["face"]}"/>',
        f'<path d="M{cx - 7} {ey + 14} Q{cx} {ey + 22} {cx + 7} {ey + 14}" fill="none" stroke="{c["face"]}" '
        f'stroke-width="6" stroke-linecap="round"/>',
    ]
    if sparkle_on:
        parts.append(sparkle(28, 42, 20, c["spark"], c["line"], 5))
    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# The word mark: "mazie page" (heart dot on the i) over "CREATIONS"
# ---------------------------------------------------------------------------
def wordmark(color=PLUM, heart_color=BLUSH_DEEP, size=100, creations=True):
    """Returns (svg_body, width, height) with the top-left at (0, 0)."""
    text = "mazıe page"
    d, w, xs = text_paths(text, size, 600, tracking=0.0)
    asc = size * 0.98                       # baseline from the top, leaves room for the heart
    body = [f'<path transform="translate(0 {asc:.2f})" d="{d}" fill="{color}"/>']
    ix, iw = xs[3]                           # the dotless i
    body.append(heart(ix + iw / 2, asc - size * 0.615, size * 0.22, heart_color))
    h = asc + size * 0.27
    if creations:
        cs = size * 0.27
        d2, w2, _ = text_paths("CREATIONS", cs, 500, tracking=0.42)
        x2 = (w - w2) / 2
        y2 = asc + size * 0.22 + cs * 0.95
        body.append(f'<path transform="translate({x2:.2f} {y2:.2f})" d="{d2}" fill="{color}"/>')
        h = y2 + cs * 0.25
    return "\n".join(body), w, h


def svg(body, w, h, bg=None, pad=0):
    W, H = w + 2 * pad, h + 2 * pad
    rect = f'<rect width="{W:.2f}" height="{H:.2f}" fill="{bg}"/>' if bg else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.2f} {H:.2f}" width="{W:.0f}" height="{H:.0f}">'
            f'{rect}<g transform="translate({pad} {pad})">{body}</g></svg>')


MB = (40, 24, 128, 160)   # the mark's tight box (page + outline) inside its 200 x 200 drawing


def svg_mark(body):
    x, y, w, h = MB
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {w} {h}" width="{w}" height="{h}">'
            f'{body}</svg>')


def gm(body, x, y, h):
    """The mark placed with its tight box's top-left at (x, y) and height h."""
    s = h / MB[3]
    return g(body, x - MB[0] * s, y - MB[1] * s, s)


def g(body, x, y, s=1.0):
    return f'<g transform="translate({x:.2f} {y:.2f}) scale({s:.4f})">{body}</g>'


files = {}

# mark
files["mazie-page-mark"] = svg_mark(mark())
files["mazie-page-mark-plum"] = svg_mark(mark({"page": WHITE, "fold": WHITE, "cheek": None}))
files["mazie-page-mark-white"] = svg_mark(mark({"line": WHITE, "page": "none", "fold": "none", "cheek": None,
                                                "face": WHITE}))

# word mark
wm, ww, wh = wordmark()
files["mazie-page-wordmark"] = svg(wm, ww, wh)
wmw, _, _ = wordmark(color=WHITE, heart_color=BLUSH)
files["mazie-page-wordmark-white"] = svg(wmw, ww, wh)
wm1, ww1, wh1 = wordmark(creations=False)
files["mazie-page-wordmark-short"] = svg(wm1, ww1, wh1)

# horizontal lockup: mark height = word mark height × 1.25
mh = wh * 1.12
mw = mh * MB[2] / MB[3]
gap = mh * 0.16
hw = mw + gap + ww
files["mazie-page-logo-horizontal"] = svg(gm(mark(), 0, 0, mh) + g(wm, mw + gap, (mh - wh) / 2), hw, mh)
files["mazie-page-logo-horizontal-white"] = svg(
    gm(mark({"line": PEARL}), 0, 0, mh) + g(wmw, mw + gap, (mh - wh) / 2), hw, mh)

# stacked lockup
smh = ww * 0.46
smw = smh * MB[2] / MB[3]
sgap = smh * 0.12
stw, sth = ww, smh + sgap + wh
files["mazie-page-logo-stacked"] = svg(gm(mark(), (ww - smw) / 2, 0, smh) + g(wm, 0, smh + sgap), stw, sth)

# icon (shop icon / favicon / avatar): the mark on a blush square, inside the circle-safe area
icon_mark = mark(sparkle_on=False)
for name, bg in (("mazie-page-icon", BLUSH), ("mazie-page-icon-lilac", LILAC), ("mazie-page-icon-plum", PLUM)):
    m = icon_mark if bg != PLUM else mark({"line": PEARL, "face": PLUM}, sparkle_on=False)
    if bg == LILAC:
        m = mark({"page": PEARL}, sparkle_on=False)
    k = 512 * 0.80 / 200
    body = g(m, 256 - 104 * k, 256 - 104 * k, k)
    files[name] = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">'
                   f'<rect width="512" height="512" fill="{bg}"/>{body}</svg>')

for name, text in files.items():
    (OUT / f"{name}.svg").write_text(text, encoding="utf-8")
print("svg:", len(files))

# PNG exports through headless Chromium (transparent background)
from playwright.sync_api import sync_playwright

PNG = {"mazie-page-mark": [1024, 256], "mazie-page-mark-plum": [1024], "mazie-page-mark-white": [1024],
       "mazie-page-wordmark": [2000], "mazie-page-wordmark-white": [2000], "mazie-page-wordmark-short": [2000],
       "mazie-page-logo-horizontal": [2400], "mazie-page-logo-horizontal-white": [2400],
       "mazie-page-logo-stacked": [1600], "mazie-page-icon": [500, 1024, 32], "mazie-page-icon-lilac": [500],
       "mazie-page-icon-plum": [500]}
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    for name, widths in PNG.items():
        text = files[name]
        import re
        vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', text).group(1).split()]
        for W in widths:
            H = round(W * vb[3] / vb[2])
            html = (f"<html><body style='margin:0;background:transparent'>"
                    f"{re.sub(r'width=\"[^\"]+\" height=\"[^\"]+\"', f'width=\"{W}\" height=\"{H}\"', text, count=1)}"
                    f"</body></html>")
            pg.set_viewport_size({"width": W, "height": H})
            pg.set_content(html)
            pg.locator("svg").screenshot(path=str(OUT / f"{name}_{W}.png"), omit_background=True)
    b.close()
print("png done")
