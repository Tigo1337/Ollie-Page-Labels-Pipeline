"""Sheet packing. Strategies sit behind `PackingStrategy` so they can be swapped.

Coordinates: page mm, y down; a placement's (x, y) is the top-left of the CUT box.
Rules every strategy must respect:
  * bleed boxes stay inside the print margin and outside the keep-out squares
  * neighbouring cut lines are at least `gap` apart
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Protocol, Sequence

from .config import Production, Size

EPS = 1e-6


@dataclass
class Job:
    """One physical label to place."""
    size: str
    key: str                 # render key (identical labels share it)
    group: str = ""          # name grouping key, e.g. "order:line"
    order_id: str = ""
    seq: int = 0             # stable order within the run


@dataclass
class Placement:
    job: Job
    x: float
    y: float
    w: float
    h: float

    def bleed_box(self, b: float) -> tuple[float, float, float, float]:
        return self.x - b, self.y - b, self.x + self.w + b, self.y + self.h + b


@dataclass
class Sheet:
    placements: list[Placement] = field(default_factory=list)


class PackingStrategy(Protocol):
    name: str

    def pack(self, jobs: Sequence[Job], sizes: dict[str, Size], prod: Production) -> list[Sheet]:
        ...


def x_interval(prod: Production, y0: float, y1: float) -> tuple[float, float]:
    """Usable x range for a bleed box spanning [y0, y1] given the margins and keep-outs."""
    left, right = prod.margin, prod.page_w - prod.margin
    for kx0, ky0, kx1, ky1 in prod.keepout_rects():
        if y0 < ky1 - EPS and y1 > ky0 + EPS:  # vertical overlap
            if kx0 <= EPS:
                left = max(left, kx1)
            else:
                right = min(right, kx0)
    return left, right


class TidyRowPacker:
    """Rows of identical sizes, left-aligned, filled edge to edge, top to bottom.

    * Each size sits on a fixed column grid starting at the left margin, so its
      columns line up down the page; rows beside a keep-out square simply skip the
      grid columns the square covers.

    * Labels of one size stay together; within a size the job order is kept, so
      every name's labels are contiguous.
    * A row never mixes sizes; when a size runs out the next size starts a new row.
    * The order in which sizes are laid down is chosen to minimise sheets, then to
      keep each size on as few sheets as possible; remaining ties go to the
      tallest-first order, so the layout is predictable.
    """
    name = "tidy-rows"
    grid = True

    def pack(self, jobs: Sequence[Job], sizes: dict[str, Size], prod: Production) -> list[Sheet]:
        if not jobs:
            return []
        groups: dict[str, list[Job]] = {}
        for j in sorted(jobs, key=lambda j: j.seq):
            groups.setdefault(j.size, []).append(j)
        canonical = sorted(groups, key=lambda s: (-(sizes[s].h), -(sizes[s].w), s))
        best: tuple[tuple, list[Sheet]] | None = None
        for rank, perm in enumerate(itertools.permutations(canonical)):
            sheets = self._lay(perm, groups, sizes, prod)
            spread = sum(len({p.job.size for p in sh.placements}) for sh in sheets)
            score = (len(sheets), spread, rank)
            if best is None or score < best[0]:
                best = (score, sheets)
            if len(canonical) > 6 and rank > 720:
                break
        assert best is not None
        return best[1]

    def _lay(self, order: Sequence[str], groups: dict[str, list[Job]], sizes: dict[str, Size],
             prod: Production) -> list[Sheet]:
        b = prod.bleed
        spacing = prod.gap - 2 * b           # space between neighbouring bleed boxes
        bottom = prod.page_h - prod.margin
        boundaries = sorted({r[3] for r in prod.keepout_rects()} | {r[1] for r in prod.keepout_rects()})
        sheets = [Sheet()]
        y = prod.margin                      # top of the next row's bleed box
        for sid in order:
            size = sizes[sid]
            bw, bh = size.w + 2 * b, size.h + 2 * b
            todo = list(groups[sid])
            while todo:
                n = 0
                left = 0.0
                fresh = not sheets[-1].placements
                while True:
                    if y + bh > bottom + EPS:
                        if fresh:
                            raise ValueError(f"Label size '{sid}' does not fit on the page.")
                        sheets.append(Sheet())
                        y = prod.margin
                        fresh = True
                        continue
                    left, right = x_interval(prod, y, y + bh)
                    if self.grid:  # snap to the size's column grid
                        pitch = bw + spacing
                        left = prod.margin + math.ceil((left - prod.margin) / pitch - EPS) * pitch
                    n = int(math.floor((right - left + spacing) / (bw + spacing) + EPS))
                    if n >= 1:
                        break
                    nxt = [v for v in boundaries if v > y + EPS]
                    if not nxt:
                        y = bottom + 1  # force a new sheet
                    else:
                        y = nxt[0]
                row, todo = todo[:n], todo[n:]
                for i, job in enumerate(row):
                    x = left + i * (bw + spacing) + b
                    sheets[-1].placements.append(Placement(job, x, y + b, size.w, size.h))
                y += bh + spacing
        return sheets


class CompactRowPacker(TidyRowPacker):
    """Like tidy-rows, but rows beside a keep-out start right after the square
    (can fit one more label in those rows; columns no longer line up)."""
    name = "compact-rows"
    grid = False


STRATEGIES: dict[str, PackingStrategy] = {s.name: s for s in (TidyRowPacker(), CompactRowPacker())}
DEFAULT_STRATEGY = TidyRowPacker.name


def get_strategy(name: str | None = None) -> PackingStrategy:
    return STRATEGIES[name or DEFAULT_STRATEGY]


def labels_per_sheet(size: Size, prod: Production, strategy: str | None = None) -> int:
    jobs = [Job(size=size.id, key="x", seq=i) for i in range(2000)]
    sheets = get_strategy(strategy).pack(jobs, {size.id: size}, prod)
    return len(sheets[0].placements)


def sheets_for(contents: dict[str, int], sizes: dict[str, Size], prod: Production,
               strategy: str | None = None) -> int:
    jobs, seq = [], 0
    for sid, q in contents.items():
        for _ in range(q):
            jobs.append(Job(size=sid, key=sid, seq=seq))
            seq += 1
    return len(get_strategy(strategy).pack(jobs, sizes, prod))
