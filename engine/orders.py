"""Orders and their expansion into one job per physical label, grouped by finish."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import Catalog
from .packing import Job
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
    jobs_by_finish: dict[str, list[Job]]
    specs: dict[str, LabelSpec]          # key -> spec
    order_of_key: dict[str, list[str]]   # key -> order ids using it


def spec_key(spec: LabelSpec) -> str:
    return json.dumps([spec.design, spec.size, spec.name, spec.line2, spec.font, spec.finish], ensure_ascii=False)


def expand(orders: list[Order], cat: Catalog) -> Expanded:
    """One job per label. Jobs keep (order, line, size) order so each name stays together."""
    jobs: dict[str, list[Job]] = {}
    specs: dict[str, LabelSpec] = {}
    users: dict[str, list[str]] = {}
    seq = 0
    size_rank = {s: i for i, s in enumerate(cat.sizes)}
    for order in orders:
        for li, line in enumerate(order.lines):
            errs = validate_line(line, cat)
            if errs:
                raise OrderError(f"Order {order.order_id}, line {li + 1} ({line.name or 'no name'}): "
                                 + " ".join(errs))
            pack = cat.packs[line.pack]
            for size_id in sorted(pack.contents, key=lambda s: size_rank.get(s, 99)):
                if size_id not in cat.sizes:
                    raise OrderError(f"Pack '{pack.id}' uses unknown size '{size_id}'.")
                spec = line.label_spec(size_id)
                key = spec_key(spec)
                specs[key] = spec
                users.setdefault(key, [])
                if order.order_id not in users[key]:
                    users[key].append(order.order_id)
                for _ in range(pack.contents[size_id]):
                    jobs.setdefault(line.finish, []).append(
                        Job(size=size_id, key=key, group=f"{order.order_id}:{li}", order_id=order.order_id, seq=seq))
                    seq += 1
    return Expanded(jobs, specs, users)
