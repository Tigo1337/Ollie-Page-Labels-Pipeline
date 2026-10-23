"""Orders and their expansion into sheet pieces (see packing.py)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from .config import Catalog
from .layout import Layout
from .packing import PackError, Piece, pack_pieces_from
from .render import LabelSpec
from .text import normalise_name


class OrderError(ValueError):
    pass


# Finishes buyers could pick before there was one finish: old SKUs and orders still parse, and are
# produced in the shop's finish (with a warning on the run).
LEGACY_FINISHES = ("matte", "gloss", "holographic")


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
                     lines=[OrderLine(**{"finish": "matte",      # one finish: orders need not name it
                                         **{k: v for k, v in ln.items() if k in OrderLine.__dataclass_fields__}})
                            for ln in d.get("lines", [])])

    @staticmethod
    def load(path: str | Path) -> "Order":
        return Order.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> dict:
        return asdict(self)


def produced_finish(cat: Catalog) -> str:
    """The finish every order is produced in (there is one: matte laminate)."""
    return "matte" if "matte" in cat.finishes else next(iter(cat.finishes))


def parse_sku(sku: str, cat: Catalog) -> tuple[str, str, str]:
    """`<design>-<pack>` (finish = matte), or the old `<design>-<pack>-<finish>` (any old finish: a
    gloss or holographic order is produced in matte, see `expand`). Design ids may contain hyphens,
    so match from the right. Returns (design, pack, finish as written in the SKU)."""
    s = (sku or "").strip().lower()

    def split(rest: str) -> tuple[str, str] | None:
        for pid in cat.packs:
            if rest.endswith("-" + pid):
                did = rest[: -len(pid) - 1]
                if did in cat.designs:
                    return did, pid
        return None
    for fid in dict.fromkeys([*cat.finishes, *LEGACY_FINISHES]):
        if s.endswith("-" + fid) and (hit := split(s[: -len(fid) - 1])):
            return hit[0], hit[1], fid
    if hit := split(s):
        return hit[0], hit[1], produced_finish(cat)
    raise OrderError(f"Unknown SKU '{sku}'. Expected <design>-<pack>, e.g. dino-school.")


def validate_line(line: OrderLine, cat: Catalog) -> list[str]:
    """Plain-language problems that block the line (glyphs are checked by the renderer)."""
    errs = []
    if line.design not in cat.designs:
        errs.append(f"Unknown design '{line.design}'.")
    if line.pack not in cat.packs:
        errs.append(f"Unknown pack '{line.pack}'.")
    if line.finish not in cat.finishes and line.finish not in LEGACY_FINISHES:
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
    pieces: list[Piece]
    specs: dict[str, LabelSpec]          # key -> spec
    order_of_key: dict[str, list[str]]   # key -> order ids using it
    warnings: list[str] = field(default_factory=list)

    def by_finish(self) -> dict[str, list[Piece]]:
        out: dict[str, list[Piece]] = {}
        for p in self.pieces:
            out.setdefault(p.finish, []).append(p)
        return out


def spec_key(spec: LabelSpec) -> str:
    return json.dumps([spec.design, spec.size, spec.name, spec.line2, spec.font, spec.finish], ensure_ascii=False)


def expand(orders: list[Order], cat: Catalog, layouts: dict[str, Layout]) -> Expanded:
    """Every order line's pack as whole pieces, in (order, line, size) order: that is their age,
    so sheets are filled with the oldest pieces first. `layouts` maps size -> its current layout."""
    pieces: list[Piece] = []
    specs: dict[str, LabelSpec] = {}
    users: dict[str, list[str]] = {}
    warnings: list[str] = []
    seq = 0
    size_rank = {s: i for i, s in enumerate(cat.sizes)}
    for order in orders:
        planned = []
        for li, line in enumerate(order.lines):
            errs = validate_line(line, cat)
            if errs:
                raise OrderError(f"Order {order.order_id}, line {li + 1} ({line.name or 'no name'}): "
                                 + " ".join(errs))
            if line.finish not in cat.finishes:          # an old gloss / holographic order
                fin = produced_finish(cat)
                warnings.append(f"Order {order.order_id}, line {li + 1} ({line.name}): asked for the old "
                                f"'{line.finish}' finish, produced in {cat.finishes[fin].label.lower()} "
                                "(the only finish now).")
                line = replace(line, finish=fin)
            pack = cat.packs[line.pack]
            try:
                counts = pack_pieces_from(pack, cat, {s: lay.per_piece for s, lay in layouts.items()})
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
            pieces.append(Piece(order_id=order.order_id, line=li, size=size_id, key=key, finish=line.finish,
                               layout_id=layouts[size_id].layout_id, name=normalise_name(line.name),
                               design=line.design, font=int(line.font), index=i, of=len(planned), seq=seq))
            seq += 1
    return Expanded(pieces, specs, users, warnings)
