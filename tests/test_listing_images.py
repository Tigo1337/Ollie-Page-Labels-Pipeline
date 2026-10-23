"""The 7 Etsy listing images (engine/listing_images.py): sizes, every group, text inside its box,
brand colours, alt texts and asset names."""
import contextlib

import numpy as np
import pytest
from PIL import ImageDraw

from engine.listing_images import GRID, LILAC, PEARL, PLUM, BLUSH, ListingImages
from engine.listings import IMAGE_VARIANTS, Group, alts, asset_name, groups_of, image_files, load_listings
from engine.workspace import REPO

GROUP_VARIANTS = [v for v, shared, _ in IMAGE_VARIANTS if not shared]


@pytest.fixture(scope="module")
def cfg():
    return load_listings(REPO / "config")


def test_variants_in_gallery_order():
    assert [v for v, _, _ in IMAGE_VARIANTS] == ["Hero", "Designs", "Bundles", "Sizes", "Fonts", "Durable",
                                                 "HowToOrder"]
    assert [v for v, shared, _ in IMAGE_VARIANTS if shared] == ["Fonts"]
    assert not any("Closeup" in v for v, _, _ in IMAGE_VARIANTS)


def test_alt_texts_and_asset_names_follow_the_variants(cfg, ws):
    g = groups_of(cfg)[0]
    files = image_files(cfg, g)
    assert [v for _, v in files] == [v for v, _, _ in IMAGE_VARIANTS]
    assert files[0][0] == "Labels_Dinosaurs_Fantasy_Hero.png" and files[4][0] == "Labels_Fonts.png"
    assert all(name == asset_name(cfg, None if v == "Fonts" else g, v) for name, v in files)
    a = alts(cfg, ws.catalog, g)
    assert len(a) == 7
    assert a[0] == ("Dinosaur & Fantasy kids name labels on a sheet — personalized waterproof name stickers by "
                    "Mazie Page Creations")
    assert a[3].startswith("Dinosaur & Fantasy name label sizes at the same scale")
    assert a[6] == "How to order the Dinosaur & Fantasy name labels in three steps"
    assert all("|" not in x and "{" not in x for x in a)


SMALL = 600   # every group at this size: the drawing code is the same at every size, 16 times fewer pixels


@pytest.fixture(scope="module")
def every_group_images(ws, cfg, tmp_path_factory):
    out = tmp_path_factory.mktemp("listing-images")
    li = ListingImages(ws.renderer, ws.ui, {**cfg, "image_size": SMALL}, ws.texts)
    paths = {}
    for g in groups_of(cfg):
        paths[g.id] = li.write_group(g, out / g.id, shared=False)
    paths["_fonts"] = [li.write_shared(out)]
    return paths


def test_every_group_makes_its_7_images(every_group_images, cfg):
    from PIL import Image
    groups = groups_of(cfg)
    assert len(every_group_images) == len(groups) + 1
    for g in groups:
        files = every_group_images[g.id]
        assert [p.name for p in files] == [asset_name(cfg, g, v) for v in GROUP_VARIANTS]
        for p in files:
            with Image.open(p) as im:
                assert im.size == (SMALL, SMALL) and im.mode == "RGB", p.name
    with Image.open(every_group_images["_fonts"][0]) as im:
        assert im.size == (SMALL, SMALL)


def test_listing_images_are_2400_square(ws, cfg, tmp_path):
    """The real size, on one group and the shared Fonts image."""
    from PIL import Image
    assert cfg["image_size"] == 2400
    li = ListingImages(ws.renderer, ws.ui, cfg, ws.texts)
    g = groups_of(cfg)[0]
    files = li.write_group(g, tmp_path / g.id, shared=False) + [li.write_shared(tmp_path)]
    assert len(files) == 7
    for p in files:
        with Image.open(p) as im:
            assert im.size == (2400, 2400) and im.mode == "RGB", p.name


# ---------------------------------------------------------------- text inside its box
@contextlib.contextmanager
def record_draws(size: int):
    """Record every text bounding box and every box drawn (cards, pills, circles) on the size × size
    listing canvas while images are made (the label renders draw on their own canvases)."""
    boxes, texts = [], []

    def on_canvas(draw) -> bool:
        return tuple(draw.im.size) == (size, size)
    orig_text, orig_rr, orig_el = ImageDraw.ImageDraw.text, ImageDraw.ImageDraw.rounded_rectangle, \
        ImageDraw.ImageDraw.ellipse

    def text(self, xy, s, *a, **kw):
        if s.strip() and on_canvas(self):
            texts.append((s, self.textbbox(xy, s, font=kw.get("font"), anchor=kw.get("anchor"))))
        return orig_text(self, xy, s, *a, **kw)

    def rounded_rectangle(self, xy, *a, **kw):
        if on_canvas(self):
            boxes.append(tuple(xy))
        return orig_rr(self, xy, *a, **kw)

    def ellipse(self, xy, *a, **kw):
        if on_canvas(self):
            boxes.append(tuple(xy))
        return orig_el(self, xy, *a, **kw)
    ImageDraw.ImageDraw.text, ImageDraw.ImageDraw.rounded_rectangle, ImageDraw.ImageDraw.ellipse = \
        text, rounded_rectangle, ellipse
    try:
        yield boxes, texts
    finally:
        ImageDraw.ImageDraw.text, ImageDraw.ImageDraw.rounded_rectangle, ImageDraw.ImageDraw.ellipse = \
            orig_text, orig_rr, orig_el


def text_problems(boxes, texts, size, tol=2):
    """Each text must lie inside the smallest box (card, pill, circle) its centre is in; text in no box
    must stay on the image."""
    out = []
    for s, (x0, y0, x1, y1) in texts:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        inside = [b for b in boxes if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]]
        if inside:
            b = min(inside, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
            if x0 < b[0] - tol or x1 > b[2] + tol or y0 < b[1] - tol or y1 > b[3] + tol:
                out.append(f"'{s}' {(x0, y0, x1, y1)} runs out of its box {b}")
        elif x0 < 0 or y0 < 0 or x1 > size or y1 > size:
            out.append(f"'{s}' runs off the image")
    return out


@pytest.mark.parametrize("n", [1, 6, 10, 16])
def test_groups_of_1_6_10_16_designs_keep_their_text_inside(ws, cfg, n):
    designs = [d for d in ws.catalog.designs if d != "solid"][:n]
    # the longest design names first, so the tiles' name column is really tested
    designs.sort(key=lambda d: -len(ws.catalog.designs[d].name))
    g = Group(id=f"test-{n}", code="T", name="Under the Sea & Friends" if n > 1 else "Dinos", designs=designs,
              tags=[])
    small = {**cfg, "image_size": 1200}
    li = ListingImages(ws.renderer, ws.ui, small, ws.texts)
    for variant in GROUP_VARIANTS + ["Fonts"]:
        with record_draws(1200) as (boxes, texts):
            img = li.image(variant, g)
        assert img.size == (1200, 1200)
        assert texts, variant
        problems = text_problems(boxes, texts, 1200)
        assert problems == [], f"{variant}: " + "; ".join(problems[:4])


@pytest.mark.parametrize("n,cols,tile_w", [(10, 2, 530), (11, 3, 346.7), (13, 3, 346.7), (16, 3, 346.7),
                                            (22, 4, 255)])
def test_design_image_layout_by_group_size(ws, cfg, n, cols, tile_w):
    """Up to 10 designs: the 2 × 5 tiles of the reference images. More: upright tiles in 3 columns (4 above 18),
    every design numbered in order, names at least 20 px on the 1200 grid up to 18 designs."""
    designs = [d for d in ws.catalog.designs if d != "solid"][:n]
    g = Group(id=f"g{n}", code="G", name="Group", designs=designs, tags=[])
    li = ListingImages(ws.renderer, ws.ui, {**cfg, "image_size": 1200}, ws.texts)
    with record_draws(1200) as (boxes, texts):
        li.image("Designs", g)
    numbers = [s for s, _ in texts if s.isdigit()]
    assert numbers == [str(i) for i in range(1, n + 1)]
    tiles = [b for b in boxes if abs((b[2] - b[0] + 1) - tile_w) < 2 and (b[3] - b[1]) > 60]
    assert len(tiles) >= n
    assert len({round(b[0]) for b in tiles}) >= cols
    if 10 < n <= 18:
        names = {ws.catalog.designs[d].name for d in designs}
        sizes = [y1 - y0 for s, (x0, y0, x1, y1) in texts if s in names]
        assert len(sizes) == n and min(sizes) >= 14          # cap height of a >= 20 px font


def test_listing_images_use_only_brand_colours_outside_the_labels(ws, cfg):
    """Backgrounds, cards and text: Plum, Lilac, Blush, Pearl (the label renders and photos aside)."""
    g = groups_of(cfg)[0]
    li = ListingImages(ws.renderer, ws.ui, {**cfg, "image_size": 600}, ws.texts)
    palette = np.array([PLUM, LILAC, BLUSH, PEARL], dtype=int)
    for variant in ("Bundles", "HowToOrder", "Fonts"):
        img = li.image(variant, None if variant == "Fonts" else g)
        a = np.asarray(img, dtype=int)
        # the heading band and the footer band hold only brand colours (and their anti-aliasing blends)
        for band in (a[: 600 * 200 // GRID], a[600 * 1100 // GRID:]):
            px = band.reshape(-1, 3)
            d = np.abs(px[:, None, :] - palette[None, :, :]).sum(axis=2).min(axis=1)
            assert (d <= 6).mean() > 0.9, variant


def test_customer_proof_is_in_the_brand(ws):
    """Pearl background, the horizontal logo at the top, Plum text (the labels themselves aside)."""
    from engine.brand import PEARL, PLUM
    from engine.orders import Order, OrderLine
    from engine.proofs import customer_proof_image
    img = customer_proof_image(ws.renderer, ws.ui, ws.texts, Order("p1", [OrderLine("dino", "starter", "matte", "Léo")]))
    a = np.asarray(img, dtype=int)
    assert tuple(a[5, 5]) == PEARL and tuple(a[-5, -5]) == PEARL
    logo = a[40:40 + 110, 40:40 + 420].reshape(-1, 3)
    assert (np.abs(logo - np.array(PLUM)).sum(axis=1) < 10).mean() > 0.05      # the logo's Plum outline + word mark
    # "Please check the spelling": every pixel is Plum, Pearl or an anti-aliasing blend of the two
    title = a[190:250, 40:700].reshape(-1, 3).astype(float)
    pearl, plum = np.array(PEARL, float), np.array(PLUM, float)
    t = np.clip(((title - pearl) @ (plum - pearl)) / ((plum - pearl) @ (plum - pearl)), 0, 1)
    off_line = np.linalg.norm(title - (pearl + t[:, None] * (plum - pearl)), axis=1)
    assert off_line.max() < 8 and (t > 0.9).sum() > 500
