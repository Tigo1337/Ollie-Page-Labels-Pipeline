"""Orders and their expansion into half-sheets (see packing.py)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import Catalog
from .layout import Layout
from .packing import Half, PackError, pack_halves_from
from .render import LabelSpec
from .text import normalise_name


class OrderError(ValueError):
    pass


@dataclass
class OrderLine:
    design: str
    pack: str
    finish: str
    name: str
    line2: str = ""
    font: int = 1

    def label_spec(self, size: str) -> LabelSpec:
        return LabelSpec(self.design, size, self.name, self.line2, int(self.font), self.finish).normalised()


@dataclass
class Order:
    order_id: str
    lines: list[OrderLine] = field(default_factory=list)
    customer: str = ""
    lang: str = "en"

    @staticmethod
    def from_dict(d: dict) -> "Order":
        return Order(order_id=str(d["order_id"]), customer=d.get("customer", ""), lang=d.get("lang", "en"),
                     lines=[OrderLine(**{k: v for k, v in ln.items() if k in OrderLine.__dataclass_fields__})
                            for ln in d.get("lines", [])])

    @staticmethod
    def load(path: str | Path) -> "Order":
        return Order.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> dict:
        return asdict(self)


def parse_sku(sku: str, cat: Catalog) -> tuple[str, str, str]:
    """`<design>-<pack>-<finish>`; design ids may contain hyphens, so match from the right."""
    s = (sku or "").strip().lower()
    for fid in cat.finishes:
        if s.endswith("-" + fid):
            rest = s[: -len(fid) - 1]
            for pid in cat.packs:
                if rest.endswith("-" + pid):
                    did = rest[: -len(pid) - 1]
                    if did in cat.designs:
                        return did, pid, fid
    raise OrderError(f"Unknown SKU '{sku}'. Expected <design>-<pack>-<finish>, e.g. dino-school-holographic.")


def validate_line(line: OrderLine, cat: Catalog) -> list[str]:
    """Plain-language problems that block the line (glyphs are checked by the renderer)."""
    errs = []
    if line.design not in cat.designs:
        errs.append(f"Unknown design '{line.design}'.")
    if line.pack not in cat.packs:
        errs.append(f"Unknown pack '{line.pack}'.")
    if line.finish not in cat.finishes:
        errs.append(f"Unknown finish '{line.finish}'.")
    try:
        if int(line.font) not in cat.fonts:
            errs.append(f"Unknown font number {line.font}.")
    except (TypeError, ValueError):
        errs.append(f"Font must be a number, got '{line.font}'.")
    if not normalise_name(line.name):
        errs.append("The name is empty.")
    return errs


@dataclass
class Expanded:
    halves: list[Half]
    specs: dict[str, LabelSpec]          # key -> spec
    order_of_key: dict[str, list[str]]   # key -> order ids using it

    def by_finish(self) -> dict[str, list[Half]]:
        out: dict[str, list[Half]] = {}
        for h in self.halves:
            out.setdefault(h.finish, []).append(h)
        return out


def spec_key(spec: LabelSpec) -> str:
    return json.dumps([spec.design, spec.size, spec.name, spec.line2, spec.font, spec.finish], ensure_ascii=False)


def expand(orders: list[Order], cat: Catalog, layouts: dict[str, Layout]) -> Expanded:
    """Every order line's pack as whole halves, in (order, line, size) order: that is their age,
    so pairing takes the oldest halves first. `layouts` maps size -> its current layout."""
    halves: list[Half] = []
    specs: dict[str, LabelSpec] = {}
    users: dict[str, list[str]] = {}
    seq = 0
    size_rank = {s: i for i, s in enumerate(cat.sizes)}
    for order in orders:
        planned = []
        for li, line in enumerate(order.lines):
            errs = validate_line(line, cat)
            if errs:
                raise OrderError(f"Order {order.order_id}, line {li + 1} ({line.name or 'no name'}): "
                                 + " ".join(errs))
            pack = cat.packs[line.pack]
            try:
                counts = pack_halves_from(pack, cat, {s: lay.per_half for s, lay in layouts.items()})
            except PackError as e:
                raise OrderError(str(e)) from e
            for size_id in sorted(counts, key=lambda s: size_rank.get(s, 99)):
                spec = line.label_spec(size_id)
                key = spec_key(spec)
                specs[key] = spec
                users.setdefault(key, [])
                if order.order_id not in users[key]:
                    users[key].append(order.order_id)
                planned += [(li, line, size_id, key)] * counts[size_id]
        for i, (li, line, size_id, key) in enumerate(planned, 1):
            halves.append(Half(order_id=order.order_id, line=li, size=size_id, key=key, finish=line.finish,
                               layout_id=layouts[size_id].layout_id, name=normalise_name(line.name),
                               design=line.design, font=int(line.font), index=i, of=len(planned), seq=seq))
            seq += 1
    return Expanded(halves, specs, users)
