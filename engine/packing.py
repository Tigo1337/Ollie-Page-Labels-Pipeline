"""Piece batching: orders fill whole pieces of fixed layouts; a sheet is `pieces` pieces (3 = thirds).

* A pack is a whole number of single-size pieces (pencil51 = 3 pencil pieces, starter = one piece
  each of pencil, medium and round + two small pieces). Every piece carries its order, line,
  size, design, name, font and finish; all its cells hold that one label.
* A sheet is three pieces with the same layout (size) and the same finish. Sheets are filled
  oldest piece first, and the pieces may come from different orders (three `starter` orders =
  one pencil sheet, two small sheets, one medium sheet and one round sheet).
* A sheet left with only 1 or 2 pieces either waits for more orders, or is printed: its empty
  pieces get free bonus copies of the last real piece, or are left blank.

Strategies sit behind `PackingStrategy` so the batching can change later.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Literal, Protocol, Sequence

from .config import Catalog, Pack, Production

Unpaired = Literal["wait", "bonus", "blank"]


class PackError(ValueError):
    pass


@dataclass(frozen=True)
class Piece:
    """One piece of a sheet (French: tiers): one size, one label repeated in every cell of the piece."""
    order_id: str
    line: int                # order line index (0-based)
    size: str
    key: str                 # render key (same label = same key)
    finish: str
    layout_id: str
    name: str = ""
    design: str = ""
    font: int = 1
    index: int = 1           # this piece's number within its order (1-based) ...
    of: int = 1              # ... out of the order's pieces
    seq: int = 0             # age: lower = older (filling order)
    bonus: bool = False      # a free copy filling an empty piece of a sheet printed without enough pieces

    @property
    def tag(self) -> str:
        return f"#{self.order_id} · {self.name} · tiers {self.index}/{self.of}"


@dataclass
class SheetPlan:
    n: int                        # sheet number in the run (1-based)
    layout_id: str
    size: str
    finish: str
    pieces: list[Piece | None]    # printed order (top, middle, bottom); None = printed blank

    @property
    def filled(self) -> list[Piece]:
        return [p for p in self.pieces if p is not None]


@dataclass
class BatchPlan:
    sheets: list[SheetPlan] = field(default_factory=list)
    waiting: list[Piece] = field(default_factory=list)


class PackingStrategy(Protocol):
    name: str

    def plan(self, pieces: Sequence[Piece], unpaired: Unpaired, size_order: Sequence[str],
             finish_order: Sequence[str], per_sheet: int = 3) -> BatchPlan:
        ...


class PieceBatcher:
    """Fill sheets with pieces of the same layout and finish, oldest first."""
    name = "pieces"

    def plan(self, pieces: Sequence[Piece], unpaired: Unpaired = "bonus", size_order: Sequence[str] = (),
             finish_order: Sequence[str] = (), per_sheet: int = 3) -> BatchPlan:
        groups: dict[tuple[str, str], list[Piece]] = {}
        for p in sorted(pieces, key=lambda p: p.seq):
            groups.setdefault((p.finish, p.layout_id), []).append(p)
        f_rank = {f: i for i, f in enumerate(finish_order)}
        s_rank = {s: i for i, s in enumerate(size_order)}
        out = BatchPlan()
        for (finish, layout_id) in sorted(groups, key=lambda k: (f_rank.get(k[0], 99),
                                                               s_rank.get(groups[k][0].size, 99), k)):
            todo = groups[(finish, layout_id)]
            size = todo[0].size
            for i in range(0, len(todo), per_sheet):
                chunk: list[Piece | None] = list(todo[i:i + per_sheet])
                if len(chunk) < per_sheet:
                    if unpaired == "wait":
                        out.waiting += [p for p in chunk if p is not None]
                        continue
                    last = chunk[-1]
                    fill = replace(last, bonus=True) if unpaired == "bonus" else None
                    chunk += [fill] * (per_sheet - len(chunk))
                out.sheets.append(SheetPlan(0, layout_id, size, finish, chunk))
        for n, sh in enumerate(out.sheets, 1):
            sh.n = n
        return out


STRATEGIES: dict[str, PackingStrategy] = {s.name: s for s in (PieceBatcher(),)}
DEFAULT_STRATEGY = PieceBatcher.name


def get_strategy(name: str | None = None) -> PackingStrategy:
    return STRATEGIES[name or DEFAULT_STRATEGY]


# ---------------------------------------------------------------------------
# Packs in pieces
# ---------------------------------------------------------------------------
def per_piece(cat: Catalog, size_id: str, layouts_dir) -> int:
    from .layout import current_layout
    return current_layout(cat.sheet, cat.sizes[size_id], layouts_dir).per_piece


def pack_pieces(pack: Pack, cat: Catalog, layouts_dir) -> dict[str, int]:
    """{size: number of pieces}. Every quantity must fill whole pieces of its layout."""
    return pack_pieces_from(pack, cat, {sid: per_piece(cat, sid, layouts_dir) for sid in pack.contents
                                        if sid in cat.sizes})


def pack_pieces_from(pack: Pack, cat: Catalog, per_piece_of: dict[str, int]) -> dict[str, int]:
    out = {}
    for sid, q in pack.contents.items():
        if sid not in cat.sizes or sid not in per_piece_of:
            raise PackError(f"Pack '{pack.id}' uses unknown size '{sid}'.")
        n = per_piece_of[sid]
        if q % n:
            raise PackError(f"Pack '{pack.id}': {q} {sid} labels is not a whole number of pieces "
                            f"({n} per piece).")
        out[sid] = q // n
    return out


# Canada Post Lettermail. A #10 envelope (241 × 105 mm) fits the standard size (245 × 156 mm).
STANDARD_MAX_G, STANDARD_MAX_MM = 50.0, 5.0         # standard letter: postage up to 30 g, then up to 50 g
OVERSIZED_MAX_G, OVERSIZED_MAX_MM = 500.0, 20.0     # oversized letter: postage in 100 g steps up to 500 g
STANDARD_TIERS = (30.0, 50.0)
OVERSIZED_TIERS = (100.0, 200.0, 300.0, 400.0, 500.0)


def envelope(pieces: int, production: Production) -> dict:
    """The #10 envelope holding `pieces` pieces: its estimated weight (pieces × piece_weight_g +
    envelope_weight_g) and thickness, and its Canada Post Lettermail postage tier, decided by the
    weight **and** the thickness (standard up to 50 g and 5 mm, oversized up to 500 g and 20 mm).
    `tier` names the postage step (same tier = same postage); `warning` says why it is not a standard
    letter, if it is not."""
    weight = round(pieces * production.piece_weight_g + production.envelope_weight_g, 1)
    thickness = round(pieces * production.piece_thickness_mm, 2)
    if weight <= STANDARD_MAX_G and thickness <= STANDARD_MAX_MM:
        limit = next(t for t in STANDARD_TIERS if weight <= t)
        kind, tier = "standard", f"standard-{limit:g}"
        label = f"Lettermail, up to {limit:g} g" if limit == STANDARD_TIERS[0] else \
            f"Lettermail, {STANDARD_TIERS[0]:g}–{limit:g} g"
    elif weight <= OVERSIZED_MAX_G and thickness <= OVERSIZED_MAX_MM:
        limit = next(t for t in OVERSIZED_TIERS if weight <= t)
        kind, tier = "oversized", f"oversized-{limit:g}"
        label = f"Oversized letter, up to {limit:g} g"
    else:
        kind, tier, label = "parcel", "parcel", "Parcel (over 500 g or 20 mm)"
    reasons = []
    if weight > STANDARD_MAX_G:
        reasons.append(f"over {STANDARD_MAX_G:g} g")
    if thickness > STANDARD_MAX_MM:
        reasons.append(f"about {thickness:g} mm thick (standard letters: {STANDARD_MAX_MM:g} mm)")
    ships_as = "a parcel" if kind == "parcel" else f"an {label[0].lower()}{label[1:]}"
    warning = f"{pieces} pieces, {' and '.join(reasons)}: ships as {ships_as}." if reasons else ""
    return {"weight_g": weight, "thickness_mm": thickness, "kind": kind, "tier": tier, "lettermail": label,
            "warning": warning}


def order_envelope(real: int, bonus: int, production: Production) -> dict:
    """An order's envelope: its real pieces, plus its bonus copies only when they keep the same postage
    tier (free copies must never raise the postage); otherwise the bonus copies are kept aside as spares."""
    alone = envelope(real, production)
    with_bonus = envelope(real + bonus, production)
    add = bonus > 0 and with_bonus["tier"] == alone["tier"]
    env = dict(with_bonus if add else alone)
    env.update(real=real, bonus=bonus, bonus_in_envelope=add, pieces=real + (bonus if add else 0))
    if bonus and not add:
        ships_as = "a parcel" if with_bonus["kind"] == "parcel" else \
            f"an {with_bonus['lettermail'][0].lower()}{with_bonus['lettermail'][1:]}"
        env["bonus_note"] = (f"keep the {bonus} bonus piece{'s' if bonus > 1 else ''} aside as spares: in the "
                             f"envelope they would make it {ships_as}")
    return env


def pack_sheets(pack: Pack, cat: Catalog, layouts_dir) -> dict[str, float]:
    """Material per pack, in sheets: pieces / pieces-per-sheet when batched with other orders, and
    the sheets used when the order is printed on its own (Σ ceil(pieces of a size / pieces-per-sheet))."""
    pieces = pack_pieces(pack, cat, layouts_dir)
    n = cat.sheet.pieces
    total = sum(pieces.values())
    return {"pieces": total, "batched": round(total / n, 3), "alone": sum(math.ceil(k / n) for k in pieces.values()),
            "envelope": envelope(total, cat.production)}
