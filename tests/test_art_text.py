import numpy as np
import pytest
from PIL import Image

from engine.art import ArtError, auto_preset, bleed_aspect, crop_window, trim_white_bands
from engine.config import Preset
from engine.geometry import rect_in_shape
from engine.render import LabelSpec, RenderError
from engine.text import GlyphError, normalise_name

# ---------------------------------------------------------------- trimming

def test_trim_white_bands():
    img = Image.new("RGB", (400, 300), "white")
    img.paste(Image.new("RGB", (400, 100), (90, 140, 200)), (0, 100))
    # a pale row of sky in the middle of the strip must not split the strip
    img.paste(Image.new("RGB", (400, 2), (252, 252, 252)), (0, 150))
    out = trim_white_bands(img)
    assert out.size == (400, 100 - 8)


def test_trim_real_shaped_art(ws):
    im = ws.assets.art("dino", "wide")
    assert im.width == 2752 and im.height == 688 - 8


def test_trim_all_white_raises():
    with pytest.raises(ArtError):
        trim_white_bands(Image.new("RGB", (100, 100), "white"))

# ---------------------------------------------------------------- crop math

def test_crop_window_basic():
    p = Preset("wide", (0.5, 0.5), 0.5, (0, 0, 1, 1))
    x0, y0, x1, y1 = crop_window(p, 1000, 400, 2.0)
    assert (y1 - y0) == pytest.approx(200) and (x1 - x0) == pytest.approx(400)
    assert (x0 + x1) / 2 == pytest.approx(500) and (y0 + y1) / 2 == pytest.approx(200)


def test_crop_window_clamps_width_and_recomputes_height():
    p = Preset("wide", (0.5, 0.5), 1.0, (0, 0, 1, 1))
    x0, y0, x1, y1 = crop_window(p, 1000, 400, 4.0)   # 400 * 4 = 1600 > 1000
    assert x1 - x0 == pytest.approx(1000) and y1 - y0 == pytest.approx(250)


def test_crop_window_clamped_inside_image():
    p = Preset("square", (0.02, 0.99), 0.5, (0, 0, 1, 1))
    x0, y0, x1, y1 = crop_window(p, 1000, 1000, 1.0)
    assert (x0, y0, x1, y1) == pytest.approx((0, 500, 500, 1000))
    p = Preset("square", (0.5, 0.5), 3.0, (0, 0, 1, 1))  # taller than the source
    assert crop_window(p, 1000, 800, 1.0) == pytest.approx((100, 0, 900, 800))


def test_auto_preset_rect_is_left_anchored(ws):
    cat = ws.catalog
    size, prod = cat.sizes["medium"], cat.production
    p = auto_preset(cat.designs["dino"], size, prod, 2752, 680)
    x0, y0, x1, y1 = crop_window(p, 2752, 680, bleed_aspect(size, prod))
    assert x0 == pytest.approx(0) and y0 == pytest.approx(0) and y1 == pytest.approx(680)
    strip_w_mm = 2752 * (size.h + 2 * prod.bleed) / 680
    assert p.text[0] * size.w == pytest.approx(0.20 * strip_w_mm - prod.bleed + 1)
    pad = max(1, 0.45 * size.r)
    assert p.text[2] * size.w == pytest.approx(size.w - pad)
    assert p.text[1] * size.h == pytest.approx(pad * 0.7)


def test_auto_preset_round_square(ws):
    cat = ws.catalog
    for sid in ("round", "square"):
        p = auto_preset(cat.designs["dino"], cat.sizes[sid], cat.production, 2048, 2048)
        assert p.source == "square" and p.text == (0.14, 0.14, 0.86, 0.40)


def test_saved_preset_is_used_and_survives_same_shape_art(ws):
    preset = Preset("wide", (0.6, 0.5), 0.8, (0.3, 0.1, 0.95, 0.9))
    lab = ws.renderer.render(LabelSpec("fox", "small", "Léo", "", 1), preset=preset)
    assert lab.preset == preset
    k = lab.dpi / 25.4
    assert lab.text_box_px[0] == pytest.approx((ws.catalog.production.bleed + 0.3 * 45) * k)

# ---------------------------------------------------------------- text

def test_normalise():
    assert normalise_name("  Zoë   Marie ") == "Zoë Marie"


@pytest.mark.parametrize("size", ["mini", "small", "medium", "large", "round", "square"])
@pytest.mark.parametrize("name,line2", [("Maximilien-Alexandre", ""), ("Léo", ""),
                                        ("Alexandre", "Tremblay-Gagnon")])
def test_text_fits_inside_box_and_safe_zone(ws, size, name, line2):
    cat = ws.catalog
    lab = ws.renderer.render(LabelSpec("dino", size, name, line2, 1))
    k = lab.dpi / 25.4
    b = cat.production.bleed
    x0, y0, x1, y1 = lab.text_box_px
    for ln in lab.lines:
        ix0, iy0, ix1, iy1 = ln.ink
        assert ix0 >= x0 - 0.5 and ix1 <= x1 + 0.5 and iy0 >= y0 - 0.5 and iy1 <= y1 + 0.5
        rect_mm = (ix0 / k - b, iy0 / k - b, ix1 / k - b, iy1 / k - b)
        assert rect_in_shape(cat.sizes[size], rect_mm, cat.production.safe)
        assert ln.cap_px <= cat.designs["dino"].cap_frac * (y1 - y0) + 1e-6 or line2


def test_text_pixels_inside_box(ws):
    """Check the actual drawn pixels, not just the metrics: render on a blank design."""
    lab = ws.renderer.render(LabelSpec("solid", "medium", "Maximilien-Alexandre", "", 1))
    a = np.asarray(lab.image).astype(int)
    art = np.array([40, 90, 200])
    differs = np.abs(a - art).sum(axis=2) > 60
    white_outside = a.min(axis=2) > 250
    text_px = differs & ~white_outside
    ys, xs = np.nonzero(text_px[5:-5, 5:-5])  # ignore the anti-aliased bleed edge
    x0, y0, x1, y1 = lab.text_box_px
    assert xs.min() + 5 >= x0 - 2 and xs.max() + 5 <= x1 + 2
    assert ys.min() + 5 >= y0 - 2 and ys.max() + 5 <= y1 + 2


def test_readability_and_mini_warnings(ws):
    lab = ws.renderer.render(LabelSpec("dino", "mini", "Maximilien-Alexandre", "", 17))
    assert any("Pacifico" in w and "Mini" in w for w in lab.warnings)
    assert any("cap height" in w for w in lab.warnings) == (lab.min_cap_mm < 1.7)
    lab = ws.renderer.render(LabelSpec("dino", "mini", "Christopher-Alexandre", "Tremblay-Gagnon", 1))
    assert lab.min_cap_mm < 1.7 and any("cap height" in w for w in lab.warnings)


def test_glyph_check_catches_missing_characters(ws):
    with pytest.raises(GlyphError) as e:
        ws.renderer.render(LabelSpec("dino", "mini", "Nguyễn", "", 1))
    assert "ễ" in e.value.missing
    alt_ids = {f.id for f in e.value.alternatives}
    assert 2 in alt_ids and 1 not in alt_ids
    for name in ("Zoë", "Łukasz", "Søren", "Müller"):
        ws.fonts.check_glyphs(name, 1)


def test_glyph_check_line2(ws):
    with pytest.raises(GlyphError):
        ws.renderer.render(LabelSpec("dino", "large", "Anna", "Nguyễn", 8))


def test_empty_name(ws):
    with pytest.raises(RenderError):
        ws.renderer.render(LabelSpec("dino", "mini", "   ", "", 1))
