"""Catalogue data: production numbers, sizes, packs, finishes, fonts and designs.

Everything is plain dataclasses so the web app can build them from its database
and the CLI can build them from the JSON files in ``config/``.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

Source = Literal["wide", "square"]


@dataclass(frozen=True)
class Production:
    page_w: float = 215.9
    page_h: float = 279.4
    margin: float = 12.0
    keepout: float = 36.0
    mark_inset: float = 10.0
    mark_length: float = 20.0
    mark_thickness: float = 1.0
    mark_square: float = 5.0      # side of the filled Type 1 square (top-left)
    print_marks: bool = True      # draw the Type 1 marks into the print PDF
    bleed: float = 1.25
    gap: float = 3.0
    safe: float = 1.0
    dpi: int = 600
    proof_dpi: int = 150
    min_cap_mm: float = 1.7
    notch: float = 34.0
    rrect_segments: int = 12
    circle_segments: int = 96

    def keepout_rects(self) -> list[tuple[float, float, float, float]]:
        """Registration-mark keep-out squares (x0, y0, x1, y1), page mm, y down."""
        k, W, H = self.keepout, self.page_w, self.page_h
        return [(0.0, 0.0, k, k), (W - k, 0.0, W, k), (0.0, H - k, k, H)]

    def mark_rects(self) -> list[tuple[float, float, float, float]]:
        """Silhouette Type 1 registration marks as filled rectangles (page mm, y down).

        Top-left: a filled square. Top-right and bottom-left: L-shaped corners whose
        outer edges sit `mark_inset` from the page edges, arms `mark_length` long and
        `mark_thickness` thick, pointing into the page.
        """
        i, L, t, s, W, H = (self.mark_inset, self.mark_length, self.mark_thickness, self.mark_square,
                            self.page_w, self.page_h)
        return [
            (i, i, i + s, i + s),                      # top-left square
            (W - i - L, i, W - i, i + t),              # top-right, horizontal arm
            (W - i - t, i, W - i, i + L),              # top-right, vertical arm
            (i, H - i - t, i + L, H - i),              # bottom-left, horizontal arm
            (i, H - i - L, i + t, H - i),              # bottom-left, vertical arm
        ]

    def notch_rects(self) -> list[tuple[float, float, float, float]]:
        n, W, H = self.notch, self.page_w, self.page_h
        return [(0.0, 0.0, n, n), (W - n, 0.0, W, n), (0.0, H - n, n, H)]


@dataclass(frozen=True)
class Size:
    id: str
    label: str
    shape: Literal["rrect", "circle"]
    w: float
    h: float
    r: float = 0.0

    @property
    def is_rect(self) -> bool:
        """Rectangular (strip) sizes use the wide art; square and round use the square art."""
        return self.shape == "rrect" and abs(self.w - self.h) > 1e-6

    @property
    def default_source(self) -> Source:
        return "wide" if self.is_rect else "square"

    @property
    def dims_label(self) -> str:
        if self.shape == "circle":
            return f"{_n(self.w)} mm Ø"
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


@dataclass
class Catalog:
    production: Production
    sizes: dict[str, Size]
    packs: dict[str, Pack]
    finishes: dict[str, Finish]
    fonts: dict[int, FontSpec]
    designs: dict[str, Design]

    def size_order(self) -> list[str]:
        return list(self.sizes.keys())


def load_catalog(config_dir: str | Path) -> Catalog:
    d = Path(config_dir)

    def rd(name: str):
        return json.loads((d / name).read_text(encoding="utf-8"))

    prod_raw = {k: v for k, v in rd("production.json").items() if not k.startswith("_")}
    designs = {}
    for x in rd("designs.json"):
        presets = {k: Preset.from_dict(v) for k, v in (x.get("presets") or {}).items()}
        designs[x["id"]] = Design(id=x["id"], name=x["name"], fill=x["fill"], stroke=x["stroke"],
                                  char_end=float(x["char_end"]), stroke_ratio=x.get("stroke_ratio"),
                                  cap_frac=float(x.get("cap_frac", 0.52)), presets=presets)
    return Catalog(
        production=Production(**prod_raw),
        sizes={x["id"]: Size(**x) for x in rd("sizes.json")},
        packs={x["id"]: Pack(**x) for x in rd("packs.json")},
        finishes={x["id"]: Finish(**x) for x in rd("finishes.json")},
        fonts={int(x["id"]): FontSpec(**x) for x in rd("fonts.json")},
        designs=designs,
    )


def design_to_dict(d: Design) -> dict:
    out = asdict(d)
    out["presets"] = {k: v.to_dict() for k, v in d.presets.items()}
    return out
