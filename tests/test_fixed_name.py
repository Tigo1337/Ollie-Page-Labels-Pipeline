"""Fixed name position on the strip sizes: the name box is the same on every design, the art slides
behind it, and the crop never runs past either end of the strip."""
import dataclasses

import pytest

from engine.art import (NAME_GAP_MM, auto_preset, bleed_aspect, crop_window, effective_preset, fixed_name_box,
                        has_fixed_name, resolve_preset)
from engine.config import Preset, geometry_hash, load_catalog
from engine.render import LabelSpec
from engine.workspace import REPO

CAT = load_catalog(REPO / "config")
FIXED = {"pencil": 0.24, "small": 0.36, "medium": 0.36, "large": 0.42}


def test_name_start_lives_in_sizes_json_and_not_in_the_geometry_hash():
    assert {sid: s.name_start for sid, s in CAT.sizes.items() if s.name_start is not None} == FIXED
    assert all(CAT.sizes[s].name_start is None for s in ("tag", "round", "shoe"))
    assert NAME_GAP_MM == 0.8
    for sid in FIXED:
        size = CAT.sizes[sid]
        assert "name_start" not in size.geometry()
        moved = dataclasses.replace(size, name_start=0.5)
        assert geometry_hash(CAT.sheet, moved) == geometry_hash(CAT.sheet, size)
    with pytest.raises(ValueError):
        dataclasses.replace(CAT.sizes["round"], name_start=0.3)


@pytest.mark.parametrize("sid", list(FIXED))
def test_every_design_has_the_same_name_box(ws, sid):
    """For every design, the name box of the size has the same x0 and x1 (±0.01), auto or saved."""
    size = ws.catalog.sizes[sid]
    boxes = {}
    for did, design in ws.catalog.designs.items():
        if did == "solid":
            continue
        preset, _ = ws.renderer.preset_for(design, size)
        boxes[did] = preset.text
    x0s = [b[0] for b in boxes.values()]
    x1s = [b[2] for b in boxes.values()]
    assert max(x0s) - min(x0s) <= 0.01 and max(x1s) - min(x1s) <= 0.01
    assert x0s[0] == pytest.approx(FIXED[sid], abs=1e-9)
    assert tuple(boxes["dino"]) == fixed_name_box(size)


@pytest.mark.parametrize("sid", list(FIXED))
def test_the_art_slides_so_the_character_ends_before_the_name(ws, sid):
    size, b = ws.catalog.sizes[sid], ws.catalog.sheet.bleed
    w, h = ws.assets.art_sources("dino")["wide"]
    design = ws.catalog.designs["dino"]
    p = auto_preset(design, size, b, w, h)
    x0, y0, x1, y1 = crop_window(p, w, h, bleed_aspect(size, b))
    mm_per_px = (size.h + 2 * b) / (y1 - y0)
    # the character's end (char_end of the strip) lands NAME_GAP_MM before the name box (cut-edge mm)
    char_end_mm = (design.char_end * w - x0) * mm_per_px - b
    if 0 < x0 < w - (x1 - x0):                         # not clamped at either end
        assert char_end_mm == pytest.approx(size.name_start * size.w - NAME_GAP_MM, abs=0.05)
    else:
        assert char_end_mm <= size.name_start * size.w - NAME_GAP_MM + 0.05


@pytest.mark.parametrize("sid", list(FIXED))
@pytest.mark.parametrize("char_end", [0.0, 0.02, 0.2, 0.5, 0.8, 0.95])
@pytest.mark.parametrize("dims", [(2752, 680), (1200, 680), (600, 400)])
def test_the_crop_never_runs_past_either_end_of_the_strip(sid, char_end, dims):
    size, b = CAT.sizes[sid], CAT.sheet.bleed
    design = dataclasses.replace(CAT.designs["dino"], char_end=char_end)
    w, h = dims
    p = auto_preset(design, size, b, w, h)
    aspect = bleed_aspect(size, b)
    ch = p.height * h
    cw = min(ch * aspect, w)
    left = p.center[0] * w - cw / 2                     # the window the preset asks for, before clamping
    assert -1e-6 <= left and left + cw <= w + 1e-6
    x0, y0, x1, y1 = crop_window(p, w, h, aspect)
    assert 0 <= x0 and x1 <= w + 1e-6 and 0 <= y0 and y1 <= h + 1e-6
    assert tuple(p.text) == fixed_name_box(size)


def test_sizes_without_name_start_keep_todays_behaviour(ws):
    design = ws.catalog.designs["dino"]
    b = ws.catalog.sheet.bleed
    w, h = ws.assets.art_sources("dino")["wide"]
    sq = ws.assets.art_sources("dino")["square"]
    tag = auto_preset(design, ws.catalog.sizes["tag"], b, w, h)        # no character: the name fills the label
    assert tag.text[0] < 0.1 and not has_fixed_name(design, ws.catalog.sizes["tag"])
    for sid in ("round", "shoe"):
        p = auto_preset(design, ws.catalog.sizes[sid], b, *sq)
        assert p.source == "square" and tuple(p.text) == tuple(design.square_text)
    # a design without its character on a strip size keeps the full-width box there
    no_char = dataclasses.replace(design, no_character_sizes=("tag", "pencil"))
    assert not has_fixed_name(no_char, ws.catalog.sizes["pencil"])
    assert auto_preset(no_char, ws.catalog.sizes["pencil"], b, w, h).text[0] < 0.1


def test_a_saved_preset_keeps_its_art_but_the_fixed_box_wins(ws):
    size = ws.catalog.sizes["medium"]
    design = ws.catalog.designs["dino"]
    saved = Preset("wide", (0.4, 0.5), 0.8, (0.1, 0.1, 0.5, 0.9))
    with_preset = dataclasses.replace(design, presets={"medium": saved})
    p, is_auto = resolve_preset(with_preset, size, ws.catalog.sheet.bleed, ws.assets.art_sources("dino"))
    assert not is_auto and p.center == (0.4, 0.5) and p.height == 0.8 and tuple(p.text) == fixed_name_box(size)
    assert effective_preset(saved, ws.catalog.sizes["tag"], design) is saved      # tag: its own box
    lab = ws.renderer.render(LabelSpec("dino", "medium", "Léo", "", 1), preset=saved)
    assert tuple(lab.preset.text) == fixed_name_box(size)


@pytest.mark.parametrize("design", ["dino", "narwhal", "tractor", "camping"])
def test_review_names_are_big_enough_or_flagged(ws, design):
    """The review sheet's names on the strip sizes: at or above the minimum cap height, or flagged."""
    from engine.proofs import REVIEW_NAMES, review_sheet
    min_cap = ws.catalog.production.min_cap_mm
    for sid in FIXED:
        for name, l2 in REVIEW_NAMES:
            lab = ws.renderer.render(LabelSpec(design, sid, name, l2, 1))
            if lab.min_cap_mm < min_cap:
                assert any("cap height" in w for w in lab.warnings)
            else:
                assert not any("cap height" in w for w in lab.warnings)
    assert review_sheet(ws.renderer, ws.ui, design).width == 1700


@pytest.mark.parametrize("dims", [(2752, 680), (1200, 680), (600, 400)])
def test_copying_an_automatic_crop_gives_each_size_its_own_automatic_crop(dims):
    from engine.art import transfer_preset
    b = CAT.sheet.bleed
    for design in list(CAT.designs.values())[:30]:
        for s in FIXED:
            for t in FIXED:
                if s == t:
                    continue
                src, dst = CAT.sizes[s], CAT.sizes[t]
                got = transfer_preset(design, auto_preset(design, src, b, *dims), src, dst, b, *dims)
                want = auto_preset(design, dst, b, *dims)
                assert got.center == pytest.approx(want.center, abs=1e-6) and got.height == pytest.approx(want.height)
                assert tuple(got.text) == fixed_name_box(dst)


def test_copying_carries_the_zoom_and_the_slide_in_mm():
    from engine.art import transfer_preset
    b, (w, h) = CAT.sheet.bleed, (2752, 680)
    design = CAT.designs["dino"]
    large, medium = CAT.sizes["large"], CAT.sizes["medium"]

    def window(p, size):
        return crop_window(p, w, h, bleed_aspect(size, b))
    auto_l, auto_m = auto_preset(design, large, b, w, h), auto_preset(design, medium, b, w, h)
    zoomed = Preset("wide", auto_l.center, 0.8, auto_l.text)
    zx0, zy0, zx1, zy1 = window(zoomed, large)
    px_mm = (zy1 - zy0) / (large.h + 2 * b)
    slid = Preset("wide", ((zx0 + 3 * px_mm + (zx1 - zx0) / 2) / w, 0.5), 0.8, auto_l.text)   # art 3 mm further left
    got = transfer_preset(design, slid, large, medium, b, w, h)
    assert got.height == pytest.approx(0.8 * auto_m.height)
    gx0, gy0, _, gy1 = window(got, medium)
    ref = transfer_preset(design, Preset("wide", (((zx0 + zx1) / 2) / w, 0.5), 0.8, auto_l.text), large, medium, b, w, h)
    rx0, _, _, _ = window(ref, medium)
    assert (gx0 - rx0) / ((gy1 - gy0) / (medium.h + 2 * b)) == pytest.approx(3.0, abs=0.05)   # same 3 mm slide
    with pytest.raises(Exception):
        transfer_preset(design, auto_l, large, CAT.sizes["tag"], b, w, h)
