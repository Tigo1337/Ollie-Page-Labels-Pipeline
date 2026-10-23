"""Etsy listings: designs grouped into listings, and the import CSV for them.

One listing per group of designs (config/listings.json, editable in the app). Each listing asks for
  * the bundle  -> variation 1 (with its price and SKU per bundle),
  * the design  -> variation 2 (the group's design names),
  * the name and the font number -> Etsy's personalization box.

The CSV has the same 36 columns, order and encoding as the binder pipeline's physical export
(UTF-8 with a BOM, LF line ends, fields quoted only when needed, `|` between variation values and
between image alts), plus four personalization columns at the end (`personalization.columns`).
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .config import Catalog

CSV_HEADER = [
    "sku", "previous_sku", "title", "description", "price", "quantity", "who_made", "when_made", "taxonomy_id",
    "category", "shipping_profile_id", "return_policy_id", "readiness_state_id", "readiness_state",
    "shop_section_id", "item_weight", "item_weight_unit", "item_length", "item_width", "item_height",
    "item_dimensions_unit", "is_taxable", "should_auto_renew", "tags", "materials", "styles", "image_urls",
    "image_alts", "video_url", "variation_name", "variation_values", "variation_prices", "variation_quantities",
    "variation_skus", "variation2_name", "variation2_values",
]
PERSONALIZATION_HEADER = ["is_personalizable", "personalization_is_required", "personalization_char_count_max",
                          "personalization_instructions"]
ETSY_MAX_TAGS = 13
ETSY_MAX_TAG_LENGTH = 20
ETSY_MAX_TITLE = 140
ETSY_MAX_SKU = 32
ETSY_MAX_IMAGES = 10
ETSY_MAX_OPTION = 20          # characters in a variation value (Etsy property value)
SEP = "━━━━━━━━━━━━━━━"

# listing images, in gallery order: (variant, shared across listings?, alt template)
IMAGE_VARIANTS = [
    ("Hero", False, "{group_name} kids name labels on a sheet — personalized waterproof name stickers by {shop_name}"),
    ("Designs", False, "The {design_count} {group_name} label designs, numbered — choose your design"),
    ("Bundles", False, "Bundle options for the {group_name} name labels — label counts per bundle"),
    ("Sizes", False, "{group_name} name label sizes at the same scale — large, medium, small, skinny, clothing tag, "
                     "round and shoe pair"),
    ("Fonts", True, "The {font_count} numbered fonts for the kids name labels — choose your font"),
    ("Durable", False, "Close-up of laminated {group_name} name labels — waterproof, peel and stick, made in Québec"),
    ("HowToOrder", False, "How to order the {group_name} name labels in three steps"),
]


class ListingError(ValueError):
    pass


@dataclass
class Group:
    id: str
    code: str
    name: str
    designs: list[str]
    tags: list[str]


def load_listings(config_dir: Path) -> dict:
    return json.loads((Path(config_dir) / "listings.json").read_text(encoding="utf-8"))


def groups_of(cfg: dict) -> list[Group]:
    return [Group(id=g["id"], code=g["code"], name=g["name"], designs=list(g["designs"]), tags=list(g.get("tags", [])))
            for g in cfg["groups"]]


def asset_name(cfg: dict, group: Group | None, variant: str) -> str:
    """Flat, stable file name (like the binder's): Labels_Dinosaurs_Fantasy_Hero.png, Labels_Fonts.png."""
    if group is None:
        return f"{cfg['asset_prefix']}_{variant}.png"
    words = "_".join(w.capitalize() for w in re.split(r"[^A-Za-z0-9]+", group.id) if w)
    return f"{cfg['asset_prefix']}_{words}_{variant}.png"


def image_files(cfg: dict, group: Group) -> list[tuple[str, str]]:
    """(file name, variant) of a listing's images, gallery order."""
    return [(asset_name(cfg, None if shared else group, variant), variant) for variant, shared, _ in IMAGE_VARIANTS]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def problems(cfg: dict, cat: Catalog, asset_base: str | None = None) -> list[str]:
    """Everything that would make the import fail or the listings wrong (empty = ready).
    `asset_base` (where the images are hosted) is checked when given."""
    out = []
    uses_name = any("{shop_name}" in cfg.get(k, "") for k in ("title_template", "description_template"))
    if uses_name and not cfg.get("shop_name", "").strip():
        out.append("Set the shop name (it is used in the description).")
    if asset_base is not None and not asset_base.strip():
        out.append("Set where the listing images are hosted: add the R2 secrets, or fill in "
                   "'Where the images are hosted'.")
    seen: dict[str, str] = {}
    for g in groups_of(cfg):
        if not g.designs:
            out.append(f"Listing '{g.name}' has no designs.")
        for d in g.designs:
            if d not in cat.designs:
                out.append(f"Listing '{g.name}': unknown design '{d}'.")
            elif d in seen:
                out.append(f"Design '{d}' is in two listings ('{seen[d]}' and '{g.name}').")
            seen.setdefault(d, g.name)
        title = render_title(cfg, g)
        if len(title) > ETSY_MAX_TITLE:
            out.append(f"Listing '{g.name}': the title is {len(title)} characters (Etsy allows {ETSY_MAX_TITLE}).")
        for sku in [listing_sku(cfg, g)] + [variation_sku(cfg, g, p) for p in cat.packs]:
            if len(sku) > ETSY_MAX_SKU:
                out.append(f"SKU '{sku}' is longer than {ETSY_MAX_SKU} characters.")
        names = [cat.designs[d].name for d in g.designs if d in cat.designs]
        for n in names:
            if len(n) > ETSY_MAX_OPTION:
                out.append(f"Design name '{n}' is longer than {ETSY_MAX_OPTION} characters (Etsy option limit).")
        if len(set(names)) != len(names):
            out.append(f"Listing '{g.name}' has two designs with the same name.")
    missing = [d for d in cat.designs if d not in seen]
    if missing:
        out.append(f"{len(missing)} design(s) are in no listing: {', '.join(missing)}.")
    for pid in cat.packs:
        price = str(cfg["prices"].get(pid, "")).strip()
        if not price:
            out.append(f"Set the price of the '{cat.packs[pid].label}' bundle.")
        elif not re.fullmatch(r"\d+(\.\d{1,2})?", price):
            out.append(f"The price of '{cat.packs[pid].label}' must look like 12.50 (got '{price}').")
        short = cfg["pack_short"].get(pid, "")
        if not short or len(short) > ETSY_MAX_OPTION:
            out.append(f"The bundle option name for '{pid}' must be 1-{ETSY_MAX_OPTION} characters.")
    return out


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------
def listing_sku(cfg: dict, g: Group) -> str:
    return f"{cfg['sku_prefix']}-{g.code}"


def variation_sku(cfg: dict, g: Group, pack_id: str) -> str:
    return f"{listing_sku(cfg, g)}-{cfg['pack_code'].get(pack_id, pack_id.upper())}"


def render_title(cfg: dict, g: Group) -> str:
    return cfg["title_template"].format(group_name=g.name, group=g.id, shop_name=cfg.get("shop_name", ""))


def sanitize_tag(tag: str) -> str:
    """Like the binder's: NFC, letters / digits / spaces / ' and -, at most 20 characters (word boundary)."""
    t = unicodedata.normalize("NFC", tag)
    t = re.sub(r"[^\w\s'-]|_", "", t).strip().lstrip("'-").strip()
    t = re.sub(r"\s+", " ", t)
    if len(t) > ETSY_MAX_TAG_LENGTH:
        cut = t[:ETSY_MAX_TAG_LENGTH + 1]
        t = cut[:cut.rfind(" ")] if " " in cut else t[:ETSY_MAX_TAG_LENGTH]
    return t.strip()


def tags_for(cfg: dict, g: Group) -> list[str]:
    """Group tags first (they matter most), then the shop's base tags; no duplicates, at most 13."""
    out: list[str] = []
    for t in g.tags + cfg["tags_base"]:
        s = sanitize_tag(t)
        if s and s.lower() not in {x.lower() for x in out}:
            out.append(s)
    return out[:ETSY_MAX_TAGS]


def _in(mm: float) -> str:
    """Nominal inches, to the nearest 1/16 (57 mm -> 2.25)."""
    return f"{round(mm / 25.4 * 16) / 16:.3f}".rstrip("0").rstrip(".")


def size_lines(cat: Catalog) -> list[str]:
    out = []
    for s in cat.sizes.values():
        if s.shape == "circle":
            dims = f"{s.w:g} mm Ø ({_in(s.w)} in)"
        elif s.shape == "pair":
            ew = s.pair["each_w"]  # type: ignore[index]
            dims = f"2 labels of {ew:g} × {s.h:g} mm ({_in(ew)} × {_in(s.h)} in)"
        else:
            dims = f"{s.w:g} × {s.h:g} mm ({_in(s.w)} × {_in(s.h)} in)"
        out.append(f"• {s.label}: {dims}")
    return out


def bundle_lines(cfg: dict, cat: Catalog) -> list[str]:
    out = []
    for pid, p in cat.packs.items():
        parts = []
        for sid, q in p.contents.items():
            size = cat.sizes[sid]
            unit = "pairs of shoe labels" if size.shape == "pair" else f"{size.label.split(' (')[0].lower()} labels"
            parts.append(f"{q} {unit}")
        out.append(f"• {cfg['pack_short'].get(pid, p.label)} — {', '.join(parts)}")
    return out


def description(cfg: dict, cat: Catalog, g: Group) -> str:
    designs = "\n".join(f"{i}. {cat.designs[d].name}" for i, d in enumerate(g.designs, 1) if d in cat.designs)
    return cfg["description_template"].format(
        group=g.id, group_name=g.name, designs=designs, design_count=len(g.designs),
        bundles="\n".join(bundle_lines(cfg, cat)), sizes="\n".join(size_lines(cat)),
        fonts=", ".join(f"{f.id}. {f.name}" for f in cat.fonts.values()), font_count=len(cat.fonts),
        sku=listing_sku(cfg, g), shop_name=cfg.get("shop_name", ""))


def alts(cfg: dict, cat: Catalog, g: Group) -> list[str]:
    ctx = {"group_name": g.name, "design_count": len(g.designs), "font_count": len(cat.fonts),
           "shop_name": cfg.get("shop_name", "")}
    return [re.sub(r"\s+", " ", tpl.format(**ctx).replace("|", " ")).strip() for _, _, tpl in IMAGE_VARIANTS]


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
def escape_field(value: str) -> str:
    """RFC 4180, minimal (the binder's escapeField): quote only fields with a quote, comma or line break."""
    if re.search(r'[",\n\r]', value):
        return '"' + value.replace('"', '""') + '"'
    return value


def listing_row(cfg: dict, cat: Catalog, g: Group, asset_base: str) -> list[str]:
    c = cfg["csv"]
    packs = list(cat.packs)
    prices = [str(cfg["prices"][p]).strip() for p in packs]
    base = asset_base.rstrip("/")
    from urllib.parse import quote
    urls = [f"{base}/{quote(name)}" for name, _ in image_files(cfg, g)][:ETSY_MAX_IMAGES]
    values = {
        "sku": listing_sku(cfg, g), "previous_sku": "", "title": render_title(cfg, g),
        "description": description(cfg, cat, g), "price": min(prices, key=float), "quantity": c["quantity"],
        "tags": ",".join(tags_for(cfg, g)), "image_urls": ",".join(urls),
        "image_alts": "|".join(alts(cfg, cat, g)[:len(urls)]),
        "variation_name": cfg["variation_names"]["bundle"],
        "variation_values": "|".join(cfg["pack_short"][p] for p in packs),
        "variation_prices": "|".join(prices),
        "variation_quantities": "|".join(c["quantity"] for _ in packs),
        "variation_skus": "|".join(variation_sku(cfg, g, p) for p in packs),
        "variation2_name": cfg["variation_names"]["design"],
        "variation2_values": "|".join(cat.designs[d].name for d in g.designs),
    }
    row = [values[k] if k in values else str(c.get(k, "")) for k in CSV_HEADER]
    pz = cfg["personalization"]
    if pz.get("columns"):
        row += ["TRUE", "TRUE" if pz.get("required") else "FALSE", str(pz.get("char_count_max", 256)),
                pz.get("instructions", "")]
    return row


def build_csv(cfg: dict, cat: Catalog, asset_base: str, group_ids: list[str] | None = None) -> str:
    errs = problems(cfg, cat, asset_base)
    if errs:
        raise ListingError("The listings are not ready: " + " ".join(errs[:8]) + (" …" if len(errs) > 8 else ""))
    header = CSV_HEADER + (PERSONALIZATION_HEADER if cfg["personalization"].get("columns") else [])
    lines = [",".join(header)]
    for g in groups_of(cfg):
        if group_ids is None or g.id in group_ids:
            lines.append(",".join(escape_field(v) for v in listing_row(cfg, cat, g, asset_base)))
    return "﻿" + "\n".join(lines) + "\n"
