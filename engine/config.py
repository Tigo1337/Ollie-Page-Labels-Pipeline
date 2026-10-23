"""Catalogue data: production numbers, sizes, packs, finishes, fonts and designs.

Everything is plain dataclasses so the web app can build them from its database
and the CLI can build them from the JSON files in ``config/``.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

Source = Literal["wide", "square"]


@dataclass(frozen=True)
class Production:
    """Production numbers that are not sheet geometry (that lives in config/sheet.json)."""
    safe: float = 1.0             # text at least this far inside the cut line (mm)
    proof_dpi: int = 150
    min_cap_mm: float = 1.7       # readability warning below this capital-letter height
    piece_weight_g: float = 6.0   # one laminated third with its backing (envelope estimate; weigh a real one)
    envelope_weight_g: float = 5.0  # an empty #10 envelope
    piece_thickness_mm: float = 0.35  # one piece, for the Lettermail 5 mm thickness limit

    @staticmethod
    def from_dict(d: dict) -> "Production":
        """Ignores keys from older versions (page size, margins, marks: now in sheet.json)."""
        known = {f for f in Production.__dataclass_fields__}
        return Production(**{k: v for k, v in d.items() if k in known})


@dataclass(frozen=True)
class Sheet:
    """Sheet geometry from config/sheet.json, in the Studio frame (landscape, mm, y down).

    `raw` is the file's content without its "_" keys; it feeds the layouts' geometry hash.
    """
    paper_w: float
    paper_h: float
    pdf_rotate: int
    marks: int
    mark_inset: float
    mark_length: float
    mark_thickness: float
    mark_padding: float
    ink_keepout: float
    cut_keepout: float
    notch: float
    edge_margin: float
    pieces: int                   # the sheet is trimmed into this many equal pieces (3 = thirds)
    trim_margin: float
    trim_ticks: float
    trim_guide: bool
    gap: float
    bleed: float
    dpi: int
    raw: dict = field(default_factory=dict, compare=False, repr=False)

    @staticmethod
    def from_dict(d: dict) -> "Sheet":
        d = {k: v for k, v in d.items() if not k.startswith("_")}
        reg, trim = d["registration"], d["trim"]
        if reg.get("style") != "type1" or reg.get("marks") not in (3, 4):
            raise ValueError("sheet.json: registration must be Type 1 with 3 or 4 marks.")
        if int(trim.get("pieces", 0)) < 2:
            raise ValueError("sheet.json: trim.pieces must be 2 or more.")
        return Sheet(paper_w=float(d["paper"]["w"]), paper_h=float(d["paper"]["h"]),
                     pdf_rotate=int(d["paper"]["pdf_rotate"]), marks=int(reg["marks"]),
                     mark_inset=float(reg["inset"]), mark_length=float(reg["length"]),
                     mark_thickness=float(reg["thickness"]), mark_padding=float(reg["padding"]),
                     ink_keepout=float(d["corner_ink_keepout"]), cut_keepout=float(d["corner_cut_keepout"]),
                     notch=float(d["laminate_notch"]), edge_margin=float(d["edge_margin"]),
                     pieces=int(trim["pieces"]), trim_margin=float(trim["margin_each_side"]),
                     trim_ticks=float(trim["ticks_mm"]), trim_guide=bool(trim["dashed_guide"]),
                     gap=float(d["gap"]), bleed=float(d["bleed"]), dpi=int(d["dpi"]), raw=d)

    @property
    def piece_w(self) -> float:
        """The width of one piece in the Studio frame (its height on the printed sheet)."""
        return self.paper_w / self.pieces

    @property
    def trims(self) -> list[float]:
        """The trim lines' Studio X, computed (never typed in): paper_w × i / pieces, i = 1 … pieces − 1.
        Ascending Studio X, so the last one is the printed top piece's lower edge."""
        return [round(self.paper_w * i / self.pieces, 3) for i in range(1, self.pieces)]

    def piece_span(self, i: int) -> tuple[float, float]:
        """Studio X range (x0, x1) of piece i, in printed order (0 = printed top = Studio right)."""
        edges = [0.0] + self.trims + [self.paper_w]
        return edges[self.pieces - 1 - i], edges[self.pieces - i]

    def corner_squares(self, k: float) -> list[tuple[float, float, float, float]]:
        """The four k × k corner squares (x0, y0, x1, y1). Keep-outs apply to all four corners,
        marked or not, because the bottom piece mirrors the top piece."""
        W, H = self.paper_w, self.paper_h
        return [(0.0, 0.0, k, k), (W - k, 0.0, W, k), (0.0, H - k, k, H), (W - k, H - k, W, H)]


@dataclass(frozen=True)
class Size:
    id: str
    label: str
    shape: Literal["rrect", "circle", "pair"]
    w: float                  # cut size; for "pair" the whole cell (two labels + the gap between them)
    h: float
    r: float = 0.0
    gap: float | None = None  # gap between neighbouring cut lines; None = the sheet's gap
    pair: dict | None = None  # shape "pair": {"each_w": label width, "gap": gap between the two labels}

    def __post_init__(self) -> None:
        if self.shape == "pair":
            if not self.pair or abs(2 * self.pair["each_w"] + self.pair["gap"] - self.w) > 1e-6:
                raise ValueError(f"Size '{self.id}': a pair needs pair.each_w × 2 + pair.gap = w.")

    @property
    def is_rect(self) -> bool:
        """Rectangular (strip) sizes use the wide art; square, round and pair sizes use the square art."""
        return self.shape == "rrect" and abs(self.w - self.h) > 1e-6

    def gap_on(self, sheet: "Sheet") -> float:
        return self.gap if self.gap is not None else sheet.gap

    def label_rects(self) -> list[tuple[float, float, float, float]]:
        """Cut labels inside the cell as (x, y, w, h), cell top-left = (0, 0): two for a pair."""
        if self.shape == "pair":
            ew, g = float(self.pair["each_w"]), float(self.pair["gap"])  # type: ignore[index]
            return [(0.0, 0.0, ew, self.h), (ew + g, 0.0, ew, self.h)]
        return [(0.0, 0.0, self.w, self.h)]

    def geometry(self) -> dict:
        """The fields that change cut lines (feeds the layout geometry hash; labels don't)."""
        out = {"shape": self.shape, "w": self.w, "h": self.h, "r": self.r}
        if self.gap is not None:
            out["gap"] = self.gap
        if self.pair is not None:
            out["pair"] = dict(self.pair)
        return out

    @property
    def default_source(self) -> Source:
        return "wide" if self.is_rect else "square"

    @property
    def dims_label(self) -> str:
        if self.shape == "circle":
            return f"{_n(self.w)} mm Ø"
        if self.shape == "pair":
            return f"2 × ({_n(self.pair['each_w'])} × {_n(self.h)}) mm"  # type: ignore[index]
        return f"{_n(self.w)} × {_n(self.h)} mm"


def _n(v: float) -> str:
    return f"{v:g}"


@dataclass(frozen=True)
class Pack:
    id: str
    label: str
    contents: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.contents.values())


@dataclass(frozen=True)
class Finish:
    id: str
    label: str
    media: str
    laminate: str
    notch: bool
    cost_per_sheet: float | None = None


@dataclass(frozen=True)
class FontSpec:
    id: int
    name: str
    repo_dir: str
    file: str
    weight: int | None = None
    mini_ok: bool = True


@dataclass(frozen=True)
class Preset:
    """Crop preset for one design at one size. All values are fractions."""
    source: Source
    center: tuple[float, float]
    height: float
    text: tuple[float, float, float, float]

    def to_dict(self) -> dict:
        return {"source": self.source, "center": list(self.center),
                "height": self.height, "text": list(self.text)}

    @staticmethod
    def from_dict(d: dict) -> "Preset":
        return Preset(source=d["source"], center=tuple(d["center"]),  # type: ignore[arg-type]
                      height=float(d["height"]), text=tuple(d["text"]))  # type: ignore[arg-type]


@dataclass(frozen=True)
class Design:
    id: str
    name: str
    fill: str
    stroke: str
    char_end: float
    stroke_ratio: float | None = None  # None = 0.20 for a light stroke, 0.14 for a dark one
    cap_frac: float = 0.52
    presets: dict[str, Preset] = field(default_factory=dict)
    mini_start: float = 0.24           # where sizes without the character start along the wide strip
    square_text: tuple[float, float, float, float] = (0.14, 0.14, 0.86, 0.40)  # name box on square art
    no_character_sizes: tuple[str, ...] = ("tag",)

    @property
    def effective_stroke_ratio(self) -> float:
        if self.stroke_ratio is not None:
            return self.stroke_ratio
        return 0.20 if _luminance(self.stroke) > 0.5 else 0.14


def _luminance(hex_colour: str) -> float:
    r, g, b = hex_to_rgb(hex_colour)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def hex_to_rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def load_sheet(config_dir: str | Path) -> Sheet:
    return Sheet.from_dict(json.loads((Path(config_dir) / "sheet.json").read_text(encoding="utf-8")))


def geometry_hash(sheet: Sheet, size: Size) -> str:
    """sha256 of sheet.json + the size's geometry, canonical JSON. A published layout keeps the
    hash it was built with; a different hash means the layout (and its Studio template) is stale."""
    blob = json.dumps({"sheet": sheet.raw, "size": size.geometry()}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config"


@dataclass
class Catalog:
    production: Production
    sizes: dict[str, Size]
    packs: dict[str, Pack]
    finishes: dict[str, Finish]
    fonts: dict[int, FontSpec]
    designs: dict[str, Design]
    # Not editable in the app: changing it invalidates every Studio template.
    sheet: Sheet = field(default_factory=lambda: load_sheet(DEFAULT_CONFIG))

    def size_order(self) -> list[str]:
        return list(self.sizes.keys())


def load_catalog(config_dir: str | Path) -> Catalog:
    d = Path(config_dir)

    def rd(name: str):
        return json.loads((d / name).read_text(encoding="utf-8"))

    prod_raw = {k: v for k, v in rd("production.json").items() if not k.startswith("_")}
    designs = {x["id"]: design_from_dict(x) for x in rd("designs.json")}
    return Catalog(
        production=Production.from_dict(prod_raw),
        sizes={x["id"]: Size(**x) for x in rd("sizes.json")},
        packs={x["id"]: Pack(**x) for x in rd("packs.json")},
        finishes={x["id"]: Finish(**x) for x in rd("finishes.json")},
        fonts={int(x["id"]): FontSpec(**x) for x in rd("fonts.json")},
        designs=designs,
        sheet=load_sheet(d),
    )


def design_from_dict(x: dict) -> Design:
    presets = {k: Preset.from_dict(v) for k, v in (x.get("presets") or {}).items()}
    extra = {}
    if x.get("mini_start") is not None:
        extra["mini_start"] = float(x["mini_start"])
    if x.get("square_text") is not None:
        extra["square_text"] = tuple(float(v) for v in x["square_text"])
    if x.get("no_character_sizes") is not None:
        extra["no_character_sizes"] = tuple(x["no_character_sizes"])
    return Design(id=x["id"], name=x["name"], fill=x["fill"], stroke=x["stroke"], char_end=float(x["char_end"]),
                  stroke_ratio=x.get("stroke_ratio"), cap_frac=float(x.get("cap_frac", 0.52)), presets=presets,
                  **extra)


def design_to_dict(d: Design) -> dict:
    out = asdict(d)
    out["presets"] = {k: v.to_dict() for k, v in d.presets.items()}
    out["square_text"] = list(d.square_text)
    out["no_character_sizes"] = list(d.no_character_sizes)
    return out
