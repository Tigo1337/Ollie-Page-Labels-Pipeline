"""Half-sheet batching: orders fill whole halves of fixed layouts; two halves make a sheet.

* A pack is a whole number of single-size halves (pencil60 = 2 pencil halves, school = one
  half each of pencil, small, medium, round and shoe). Every half carries its order, line,
  size, design, name, font and finish; all its cells hold that one label.
* A sheet is two halves with the same layout (size) and the same finish. Halves are paired
  oldest first and may come from different orders (two `starter` orders = one pencil sheet
  and one small sheet).
* A half without a partner either waits for one, or is printed alone: its other half is a
  free bonus copy of the same half, or left blank.

Strategies sit behind `PackingStrategy` so the batching can change later.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Literal, Protocol, Sequence

from .config import Catalog, Pack

Unpaired = Literal["wait", "bonus", "blank"]


class PackError(ValueError):
    pass


@dataclass(frozen=True)
class Half:
    """One half-sheet: one size, one label repeated in every cell of the half."""
    order_id: str
    line: int                # order line index (0-based)
    size: str
    key: str                 # render key (same label = same key)
    finish: str
    layout_id: str
    name: str = ""
    design: str = ""
    font: int = 1
    index: int = 1           # this half's number within its order (1-based) ...
    of: int = 1              # ... out of the order's halves
    seq: int = 0             # age: lower = older (pairing order)
    bonus: bool = False      # a free copy filling the other half of a sheet printed alone

    @property
    def tag(self) -> str:
        return f"#{self.order_id} · {self.name} · {self.finish} · half {self.index}/{self.of}"


@dataclass
class SheetPlan:
    n: int                   # sheet number in the run (1-based)
    layout_id: str
    size: str
    finish: str
    top: Half
    bottom: Half | None      # None = printed blank

    @property
    def halves(self) -> list[Half]:
        return [self.top] + ([self.bottom] if self.bottom is not None else [])


@dataclass
class BatchPlan:
    sheets: list[SheetPlan] = field(default_factory=list)
    waiting: list[Half] = field(default_factory=list)


class PackingStrategy(Protocol):
    name: str

    def plan(self, halves: Sequence[Half], unpaired: Unpaired, size_order: Sequence[str],
             finish_order: Sequence[str]) -> BatchPlan:
        ...


class HalfSheetBatcher:
    """Pair halves of the same layout and finish, oldest first."""
    name = "half-sheets"

    def plan(self, halves: Sequence[Half], unpaired: Unpaired = "bonus", size_order: Sequence[str] = (),
             finish_order: Sequence[str] = ()) -> BatchPlan:
        groups: dict[tuple[str, str], list[Half]] = {}
        for h in sorted(halves, key=lambda h: h.seq):
            groups.setdefault((h.finish, h.layout_id), []).append(h)
        f_rank = {f: i for i, f in enumerate(finish_order)}
        s_rank = {s: i for i, s in enumerate(size_order)}
        out = BatchPlan()
        for (finish, layout_id) in sorted(groups, key=lambda k: (f_rank.get(k[0], 99),
                                                               s_rank.get(groups[k][0].size, 99), k)):
            todo = groups[(finish, layout_id)]
            size = todo[0].size
            for i in range(0, len(todo) - 1, 2):
                out.sheets.append(SheetPlan(0, layout_id, size, finish, todo[i], todo[i + 1]))
            if len(todo) % 2:
                last = todo[-1]
                if unpaired == "wait":
                    out.waiting.append(last)
                else:
                    other = replace(last, bonus=True) if unpaired == "bonus" else None
                    out.sheets.append(SheetPlan(0, layout_id, size, finish, last, other))
        for n, sh in enumerate(out.sheets, 1):
            sh.n = n
        return out


STRATEGIES: dict[str, PackingStrategy] = {s.name: s for s in (HalfSheetBatcher(),)}
DEFAULT_STRATEGY = HalfSheetBatcher.name


def get_strategy(name: str | None = None) -> PackingStrategy:
    return STRATEGIES[name or DEFAULT_STRATEGY]


# ---------------------------------------------------------------------------
# Packs in halves
# ---------------------------------------------------------------------------
def per_half(cat: Catalog, size_id: str, layouts_dir) -> int:
    from .layout import current_layout
    return current_layout(cat.sheet, cat.sizes[size_id], layouts_dir).per_half


def pack_halves(pack: Pack, cat: Catalog, layouts_dir) -> dict[str, int]:
    """{size: number of halves}. Every quantity must fill whole halves of its layout."""
    return pack_halves_from(pack, cat, {sid: per_half(cat, sid, layouts_dir) for sid in pack.contents
                                        if sid in cat.sizes})


def pack_halves_from(pack: Pack, cat: Catalog, per_half_of: dict[str, int]) -> dict[str, int]:
    out = {}
    for sid, q in pack.contents.items():
        if sid not in cat.sizes or sid not in per_half_of:
            raise PackError(f"Pack '{pack.id}' uses unknown size '{sid}'.")
        n = per_half_of[sid]
        if q % n:
            raise PackError(f"Pack '{pack.id}': {q} {sid} labels is not a whole number of halves "
                            f"({n} per half).")
        out[sid] = q // n
    return out


def pack_sheets(pack: Pack, cat: Catalog, layouts_dir) -> dict[str, float]:
    """Material per pack, in sheets: halves / 2 when batched with other orders, and the sheets
    used when the order is printed on its own (each odd half takes a whole sheet)."""
    halves = pack_halves(pack, cat, layouts_dir)
    return {"halves": sum(halves.values()), "batched": sum(halves.values()) / 2,
            "alone": sum(math.ceil(n / 2) for n in halves.values())}
