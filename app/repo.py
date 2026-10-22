"""Storage interface for the app: designs, presets, settings and artwork.

Everything that touches the database or blob storage goes through `Repo`, so the
backing store (SQLite today, Postgres later) can change in one place.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import threading
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from engine.art import ArtError, trim_white_bands
from engine.config import (Catalog, Design, Finish, FontSpec, Pack, Preset, Production, Size, design_to_dict,
                           load_catalog)

from .db import DesignRow, PresetRow, Setting
from .storage import BlobStore

SETTING_KEYS = ("production", "sizes", "packs", "finishes", "fonts", "texts", "shop", "listings")
GEOMETRY_VERSION = 2   # 2 = fixed half-sheet layouts (sheet.json); see app/migrate.py
SHOP_DEFAULTS = {"default_finish": "matte"}
# the first listings seed carried another business's name and image host: (key, old text, new text)
LISTINGS_FIXUPS = (
    ("asset_base_url", "https://assets.olliepagecreations.com", ""),
    ("description_template", "At Ollie Page Creations, we prepay", "We prepay"),
    ("description_template", "Ollie Page Creations © ", "{shop_name} © "),
)
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
MAX_IMAGE_PIXELS = 40_000_000


class NotFound(LookupError):
    pass


class Repo:
    def __init__(self, session_factory, store: BlobStore):
        self.Session = session_factory
        self.store = store
        self._version = 0
        self._lock = threading.Lock()

    # -- change tracking (engine snapshots are rebuilt when this moves) -----
    @property
    def version(self) -> int:
        return self._version

    def _bump(self) -> None:
        with self._lock:
            self._version += 1

    # -- seeding -------------------------------------------------------------
    def seed(self, config_dir: Path) -> bool:
        """Fill an empty database from config/*.json. Returns True if it seeded."""
        with self.Session() as s:
            if s.get(Setting, "sizes") is not None:
                return False
            for key, fname in (("production", "production.json"), ("sizes", "sizes.json"),
                               ("packs", "packs.json"), ("finishes", "finishes.json"),
                               ("fonts", "fonts.json"), ("texts", "texts.json")):
                val = json.loads((config_dir / fname).read_text(encoding="utf-8"))
                if isinstance(val, dict):
                    val = {k: v for k, v in val.items() if not k.startswith("_")}
                s.add(Setting(key=key, value=val))
            s.add(Setting(key="geometry_version", value={"version": GEOMETRY_VERSION}))
            cat = load_catalog(config_dir)
            for i, d in enumerate(cat.designs.values()):
                s.add(design_row_from(d, i))
            s.flush()
            for d in cat.designs.values():
                for sid, pr in d.presets.items():
                    s.add(PresetRow(design_id=d.id, size_id=sid, data=pr.to_dict()))
            s.commit()
        self._bump()
        return True

    def ensure_defaults(self, config_dir: Path | None = None) -> None:
        """Add settings introduced after a database was first seeded."""
        with self.Session() as s:
            listings = s.get(Setting, "listings")
            if config_dir is not None and listings is None:
                val = json.loads((config_dir / "listings.json").read_text(encoding="utf-8"))
                s.add(Setting(key="listings", value={k: v for k, v in val.items() if not k.startswith("_")}))
            elif listings is not None:
                val = {"shop_name": "", **listings.value}
                for key, old, new in LISTINGS_FIXUPS:
                    if isinstance(val.get(key), str):
                        val[key] = new if key == "asset_base_url" and val[key] == old else val[key].replace(old, new)
                if val != listings.value:
                    listings.value = val
            row = s.get(Setting, "shop")
            if row is None:
                s.add(Setting(key="shop", value=dict(SHOP_DEFAULTS)))
            else:
                missing = {k: v for k, v in SHOP_DEFAULTS.items() if k not in row.value}
                if missing:
                    row.value = {**row.value, **missing}
            s.commit()

    # -- settings ------------------------------------------------------------
    def setting(self, key: str):
        with self.Session() as s:
            row = s.get(Setting, key)
            if row is None:
                raise NotFound(f"Setting '{key}' is missing.")
            return row.value

    def set_setting(self, key: str, value) -> None:
        if key not in SETTING_KEYS:
            raise ValueError(f"Unknown setting '{key}'.")
        with self.Session() as s:
            row = s.get(Setting, key)
            if row is None:
                s.add(Setting(key=key, value=value))
            else:
                row.value = value
            s.commit()
        self._bump()

    # -- catalogue -----------------------------------------------------------
    def catalog(self) -> Catalog:
        with self.Session() as s:
            vals = {r.key: r.value for r in s.scalars(select(Setting))}
            designs = list(s.scalars(select(DesignRow).order_by(DesignRow.position, DesignRow.id)))
            presets = list(s.scalars(select(PresetRow)))
        by_design: dict[str, dict[str, Preset]] = {}
        for p in presets:
            by_design.setdefault(p.design_id, {})[p.size_id] = Preset.from_dict(p.data)
        return Catalog(
            production=Production.from_dict(vals["production"]),
            sizes={x["id"]: Size(**x) for x in vals["sizes"]},
            packs={x["id"]: Pack(**x) for x in vals["packs"]},
            finishes={x["id"]: Finish(**x) for x in vals["finishes"]},
            fonts={int(x["id"]): FontSpec(**x) for x in vals["fonts"]},
            designs={d.id: self._design(d, by_design.get(d.id, {})) for d in designs},
        )

    @staticmethod
    def _design(row: DesignRow, presets: dict[str, Preset]) -> Design:
        extra: dict = {}
        if row.mini_start is not None:
            extra["mini_start"] = row.mini_start
        if row.square_text is not None:
            extra["square_text"] = tuple(row.square_text)
        if row.no_character_sizes is not None:
            extra["no_character_sizes"] = tuple(row.no_character_sizes)
        return Design(id=row.id, name=row.name, fill=row.fill, stroke=row.stroke, char_end=row.char_end,
                      stroke_ratio=row.stroke_ratio, cap_frac=row.cap_frac, presets=presets, **extra)

    def art_index(self) -> dict[str, dict[str, tuple[str, int, int]]]:
        """{design: {source: (version, w, h)}} for designs that have artwork."""
        out: dict[str, dict[str, tuple[str, int, int]]] = {}
        with self.Session() as s:
            for d in s.scalars(select(DesignRow)):
                if d.wide_version:
                    out.setdefault(d.id, {})["wide"] = (d.wide_version, d.wide_w or 0, d.wide_h or 0)
                if d.square_version:
                    out.setdefault(d.id, {})["square"] = (d.square_version, d.square_w or 0, d.square_h or 0)
        return out

    # -- designs -------------------------------------------------------------
    def design_rows(self) -> list[DesignRow]:
        with self.Session() as s:
            return list(s.scalars(select(DesignRow).order_by(DesignRow.position, DesignRow.id)))

    def design_row(self, design_id: str) -> DesignRow:
        with self.Session() as s:
            row = s.get(DesignRow, design_id)
            if row is None:
                raise NotFound(f"Design '{design_id}' not found.")
            return row

    def design_json(self, row: DesignRow) -> dict:
        cat_design = self._design(row, {})
        with self.Session() as s:
            rows = list(s.scalars(select(PresetRow).where(PresetRow.design_id == row.id)))
        presets = {p.size_id: p.data for p in rows}
        d = design_to_dict(cat_design)
        d.update(presets=presets, review={p.size_id: p.review for p in rows if p.review}, position=row.position,
                 effective_stroke_ratio=cat_design.effective_stroke_ratio,
                 art={"wide": row.wide_version is not None, "square": row.square_version is not None,
                      "wide_size": [row.wide_w, row.wide_h] if row.wide_version else None,
                      "square_size": [row.square_w, row.square_h] if row.square_version else None,
                      "wide_version": row.wide_version, "square_version": row.square_version},
                 updated_at=row.updated_at.isoformat() if row.updated_at else None)
        return d

    EDITABLE = {"name": str, "fill": str, "stroke": str, "char_end": float, "stroke_ratio": float,
                "cap_frac": float, "position": int, "mini_start": float,
                "square_text": lambda v: [float(x) for x in v], "no_character_sizes": lambda v: [str(x) for x in v]}

    def update_design(self, design_id: str, fields: dict) -> DesignRow:
        with self.Session() as s:
            row = s.get(DesignRow, design_id)
            if row is None:
                raise NotFound(f"Design '{design_id}' not found.")
            for k, v in fields.items():
                if k not in self.EDITABLE:
                    raise ValueError(f"'{k}' cannot be edited.")
                if v is None and k == "stroke_ratio":
                    row.stroke_ratio = None
                    continue
                v = self.EDITABLE[k](v)
                validate_field(k, v)
                setattr(row, k, v)
            s.commit()
            s.refresh(row)
        self._bump()
        return row

    def create_design(self, design_id: str, name: str, fill: str = "#1F3B63", stroke: str = "#FFFFFF",
                      char_end: float = 0.25) -> DesignRow:
        design_id = design_id.strip().lower()
        if not ID_RE.match(design_id):
            raise ValueError("Design id must be lowercase letters, digits and hyphens (e.g. 'sea-turtle').")
        for k, v in (("fill", fill), ("stroke", stroke), ("char_end", char_end)):
            validate_field(k, v)
        with self.Session() as s:
            if s.get(DesignRow, design_id) is not None:
                raise ValueError(f"A design with id '{design_id}' already exists.")
            pos = len(list(s.scalars(select(DesignRow.id))))
            row = DesignRow(id=design_id, name=name.strip() or design_id, fill=fill, stroke=stroke,
                            char_end=char_end, cap_frac=0.52, position=pos)
            s.add(row)
            s.commit()
        self._bump()
        return row

    def delete_design(self, design_id: str) -> None:
        with self.Session() as s:
            row = s.get(DesignRow, design_id)
            if row is None:
                raise NotFound(f"Design '{design_id}' not found.")
            s.query(PresetRow).filter(PresetRow.design_id == design_id).delete()
            s.delete(row)
            s.commit()
        for key in self.store.list(f"designs/{design_id}/"):
            self.store.delete(key)
        self._bump()

    # -- artwork -------------------------------------------------------------
    @staticmethod
    def art_key(design_id: str, source: str, variant: str, ext: str = "png") -> str:
        """variant: 'original' (as uploaded) or 'prepared' (what the engine crops: trimmed wide / square)."""
        return f"designs/{design_id}/{source}_{variant}.{ext}"

    def set_art(self, design_id: str, source: str, data: bytes, filename: str = "") -> DesignRow:
        if source not in ("wide", "square"):
            raise ValueError("Artwork must be 'wide' or 'square'.")
        self.design_row(design_id)  # 404 early
        img = open_image(data, filename)
        if source == "wide":
            prepared = trim_white_bands(img)
            if prepared.width / prepared.height < 2.0:
                raise ArtError(f"After trimming the white bands the wide strip is {prepared.width} × "
                               f"{prepared.height} px, which is not a wide strip. Is this the square image?")
        else:
            prepared = img
            if abs(img.width / img.height - 1) > 0.15:
                raise ArtError(f"The square image is {img.width} × {img.height} px; expected roughly square.")
        ext = image_ext(img, filename)
        buf = io.BytesIO()
        prepared.save(buf, format="PNG", optimize=False, compress_level=3)   # lossless; faster for bulk imports
        prepared_bytes = buf.getvalue()
        version = hashlib.sha1(prepared_bytes).hexdigest()[:16]
        self.store.put(self.art_key(design_id, source, "original", ext), data)
        self.store.put(self.art_key(design_id, source, "prepared"), prepared_bytes)
        with self.Session() as s:
            row = s.get(DesignRow, design_id)
            assert row is not None
            if source == "wide":
                old = row.wide_orig_ext
                row.wide_version, row.wide_w, row.wide_h, row.wide_orig_ext = (version, prepared.width,
                                                                                prepared.height, ext)
            else:
                old = row.square_ext
                row.square_version, row.square_w, row.square_h, row.square_ext = (version, prepared.width,
                                                                                    prepared.height, ext)
            s.commit()
            s.refresh(row)
        if old and old != ext:
            self.store.delete(self.art_key(design_id, source, "original", old))
        self._bump()
        return row

    def art_bytes(self, design_id: str, source: str, variant: str) -> bytes:
        row = self.design_row(design_id)
        if source == "wide":
            if not row.wide_version:
                raise NotFound(f"Design '{design_id}' has no wide artwork yet.")
            ext = row.wide_orig_ext or "png"
        elif source == "square":
            if not row.square_version:
                raise NotFound(f"Design '{design_id}' has no square artwork yet.")
            ext = row.square_ext or "png"
        else:
            raise ValueError("Artwork must be 'wide' or 'square'.")
        if variant == "original":
            return self.store.get(self.art_key(design_id, source, "original", ext))
        return self.store.get(self.art_key(design_id, source, "prepared"))

    # -- presets (crop editor, phase 3) ---------------------------------------
    def set_preset(self, design_id: str, size_id: str, preset: Preset | None) -> None:
        self.design_row(design_id)
        with self.Session() as s:
            row = s.get(PresetRow, (design_id, size_id))
            if preset is None:
                if row is not None:
                    s.delete(row)
            elif row is None:
                s.add(PresetRow(design_id=design_id, size_id=size_id, data=preset.to_dict()))
            else:
                row.data = preset.to_dict()
                row.review = None          # saved again in the crop editor: reviewed
            s.commit()
        self._bump()


def design_row_from(d: Design, position: int) -> DesignRow:
    return DesignRow(id=d.id, name=d.name, fill=d.fill, stroke=d.stroke, char_end=d.char_end,
                     stroke_ratio=d.stroke_ratio, cap_frac=d.cap_frac, position=position,
                     mini_start=d.mini_start, square_text=list(d.square_text),
                     no_character_sizes=list(d.no_character_sizes))


HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def validate_field(k: str, v) -> None:
    if k in ("fill", "stroke") and not HEX_RE.match(str(v)):
        raise ValueError(f"{k} must be a colour like #1F5C38.")
    if k == "char_end" and not 0 <= v < 0.9:
        raise ValueError("char_end must be between 0 and 0.9.")
    if k == "cap_frac" and not 0.1 <= v <= 1.0:
        raise ValueError("Max cap-height fraction must be between 0.1 and 1.0.")
    if k == "stroke_ratio" and not 0 <= v <= 0.5:
        raise ValueError("Stroke ratio must be between 0 and 0.5.")
    if k == "name" and not str(v).strip():
        raise ValueError("The design name cannot be empty.")
    if k == "mini_start" and not 0 <= v < 0.9:
        raise ValueError("mini_start must be between 0 and 0.9.")
    if k == "square_text" and not (len(v) == 4 and 0 <= v[0] < v[2] <= 1 and 0 <= v[1] < v[3] <= 1):
        raise ValueError("square_text must be [x0, y0, x1, y1] fractions with x0 < x1 and y0 < y1.")


def open_image(data: bytes, filename: str = "") -> Image.Image:
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise ArtError(f"'{filename or 'upload'}' is not an image I can read (JPG or PNG please).") from e
    return im.convert("RGB")


def image_ext(img: Image.Image, filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext in ("jpg", "jpeg", "png", "webp"):
        return "jpg" if ext == "jpeg" else ext
    return "png"
