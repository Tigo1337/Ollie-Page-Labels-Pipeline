"""Etsy orders from the shop's "Sold Order Items" CSV (Shop Manager → Settings → Options → Download Data).

One row per order item. A label item is recognised by its SKU, the one the listings CSV gives each
bundle: `<sku_prefix>-<listing code>-<bundle code>` (e.g. LBL-DINO-START). The old `<design>-<pack>`
and `<design>-<pack>-<finish>` SKUs are read too. The design comes from the Design option, and the name,
the second line and the font number from the buyer's personalization text, which is free text: anything
that is not clear (no font number, an unknown design, extra lines...) is kept and flagged for review,
never guessed silently. Rows for other items are skipped and listed.

`parse_orders_csv` returns plain dicts (no database), so the app stores them and the tests check them.
"""
from __future__ import annotations

import csv
import html
import io
import re
import unicodedata
from dataclasses import dataclass, field

from .config import Catalog
from .orders import LEGACY_FINISHES, OrderError, parse_sku
from .text import normalise_name

PERSONALIZATION_KEYS = ("personalization", "personalisation", "personnalisation")
FONT_RE = re.compile(r"(?i)\b(?:font|fonte|police|typo(?:graphie)?|caract[eè]res?)\s*(?:#|no\.?|n°|nº|num(?:ber|[ée]ro)?)?"
                     r"\s*[:=#]?\s*(\d{1,2})\b")
TRAILING_NUMBER_RE = re.compile(r"(?:^|[\s,;:\-–—/(])#?(\d{1,2})\)?\s*$")
QUEBEC = {"qc", "quebec", "québec", "pq"}


class OrdersCsvError(ValueError):
    pass


@dataclass
class ImportResult:
    orders: list[dict] = field(default_factory=list)      # new orders, ready to store
    skipped: list[str] = field(default_factory=list)      # rows that are not label items, with why
    rows: int = 0


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower())


def _col(header: list[str], *names: str) -> int | None:
    keys = [_key(h) for h in header]
    for n in names:
        if _key(n) in keys:
            return keys.index(_key(n))
    return None


def split_variations(text: str, names: list[str]) -> dict[str, str]:
    """Etsy's "Variations" cell: "Bundle:Starter (73),Design:Dino Stomp,Personalization:Emma, font 3".
    Values may contain commas, so the cell is cut at the known option names only. Keys come back
    lower-case ("bundle", "design", "personalization")."""
    text = html.unescape(text or "")
    found = []
    for name in names:
        for m in re.finditer(rf"(?:^|,)\s*({re.escape(name)})\s*:", text, flags=re.IGNORECASE):
            found.append((m.start(), m.end(), name.lower()))
    found.sort()
    out = {}
    for i, (start, end, name) in enumerate(found):
        stop = found[i + 1][0] if i + 1 < len(found) else len(text)
        out[name] = text[end:stop].strip()
    return out


def parse_personalization(text: str, cat: Catalog) -> tuple[dict, list[str]]:
    """The buyer's personalization -> ({name, line2, font}, problems). Problems mean "check before making"."""
    raw = html.unescape(text or "").replace("\r", "\n").strip()
    problems: list[str] = []
    font = None
    m = FONT_RE.search(raw)
    if m:
        font = int(m.group(1))
        raw = (raw[:m.start()] + raw[m.end():]).strip()
    else:
        m = TRAILING_NUMBER_RE.search(raw)
        if m:
            font = int(m.group(1))
            raw = raw[:m.start()].strip()
    lines = [ln.strip(" \t-–—,;:/()") for ln in raw.split("\n")]
    lines = [ln for ln in lines if ln]
    if len(lines) == 1 and " / " in lines[0]:
        lines = [p.strip(" \t-–—,;:") for p in lines[0].split(" / ") if p.strip(" \t-–—,;:")]
    name = normalise_name(lines[0]) if lines else ""
    line2 = normalise_name(lines[1]) if len(lines) > 1 else ""
    if not name:
        problems.append("no name in the personalization")
    if len(lines) > 2:
        problems.append(f"more than two lines in the personalization ({len(lines)})")
    if font is None:
        problems.append("no font number in the personalization: font 1 is assumed")
        font = 1
    elif font not in cat.fonts:
        problems.append(f"font {font} does not exist (fonts 1-{max(cat.fonts)})")
    if re.search(r"\d", name + line2):
        problems.append("a number is left in the name: check it")
    return {"name": name, "line2": line2, "font": font}, problems


def _design_by_name(value: str, cat: Catalog, candidates: list[str]) -> str | None:
    v = _key(value)
    for pool in (candidates, list(cat.designs)):
        for did in pool:
            if did in cat.designs and (_key(cat.designs[did].name) == v or did == value.strip().lower()):
                return did
    return None


def parse_orders_csv(text: str, cfg: dict, cat: Catalog) -> ImportResult:
    """Etsy's Sold Order Items CSV -> orders (dicts with lines). `cfg` is the listings setting (SKU
    prefix, bundle codes and option names, listing codes)."""
    text = text.lstrip("﻿")
    reader = list(csv.reader(io.StringIO(text)))
    if not reader:
        raise OrdersCsvError("The file is empty.")
    header = reader[0]
    c_order = _col(header, "Order ID", "Order Number")
    c_var = _col(header, "Variations")
    c_sku = _col(header, "SKU")
    if c_order is None or (c_var is None and c_sku is None):
        if _col(header, "Number of Items") is not None:
            raise OrdersCsvError("This is Etsy's Sold Orders file. Download the Sold Order Items file instead "
                                 "(Shop Manager → Settings → Options → Download Data → Orders, type Order Items).")
        raise OrdersCsvError("This does not look like Etsy's Sold Order Items CSV (no Order ID, SKU or Variations "
                             "column).")
    c_qty = _col(header, "Quantity")
    c_buyer = _col(header, "Ship Name", "Buyer", "Full Name")
    c_date = _col(header, "Sale Date", "Order Date", "Date Paid")
    c_item = _col(header, "Item Name", "Title")
    c_tx = _col(header, "Transaction ID")
    c_country = _col(header, "Ship Country")
    c_state = _col(header, "Ship State")
    c_pers = next((i for i, h in enumerate(header) if "personali" in _key(h) or "personnali" in _key(h)), None)

    prefix = str(cfg.get("sku_prefix", "LBL")).upper()
    code_to_pack = {str(v).upper(): k for k, v in cfg.get("pack_code", {}).items() if k in cat.packs}
    short_to_pack = {_key(str(v)): k for k, v in cfg.get("pack_short", {}).items() if k in cat.packs}
    groups = {str(g["code"]).upper(): g for g in cfg.get("groups", [])}
    vn = cfg.get("variation_names", {})
    names = [vn.get("bundle", "Bundle"), vn.get("design", "Design"), *PERSONALIZATION_KEYS]
    bundle_key, design_key = vn.get("bundle", "Bundle").lower(), vn.get("design", "Design").lower()

    res = ImportResult()
    orders: dict[str, dict] = {}

    def cell(row, i):
        return row[i].strip() if i is not None and i < len(row) else ""

    for n, row in enumerate(reader[1:], 2):
        if not any(x.strip() for x in row):
            continue
        res.rows += 1
        order_id = cell(row, c_order)
        item = cell(row, c_item) or cell(row, c_sku) or f"row {n}"
        if not order_id:
            res.skipped.append(f"Row {n}: no order ID.")
            continue
        var = split_variations(cell(row, c_var), names)
        sku = cell(row, c_sku)
        problems: list[str] = []
        pack = design = None
        finish = "matte"
        group = None
        parts = sku.upper().split("-")
        if len(parts) >= 3 and parts[0] == prefix and parts[-1] in code_to_pack:
            pack = code_to_pack[parts[-1]]
            group = groups.get("-".join(parts[1:-1]))
        elif sku:
            try:
                design, pack, finish = parse_sku(sku, cat)
            except OrderError:
                pass
        if pack is None and var.get(bundle_key):
            pack = short_to_pack.get(_key(var[bundle_key]))
        if pack is None:
            res.skipped.append(f"Order {order_id}: '{item}' is not a label bundle (SKU '{sku or '-'}').")
            continue
        if design is None:
            if var.get(design_key):
                design = _design_by_name(var[design_key], cat, list(group["designs"]) if group else [])
                if design is None:
                    problems.append(f"unknown design '{var[design_key]}'")
            else:
                problems.append("no design option in the order")
        pers_text = cell(row, c_pers) or next((var[k] for k in PERSONALIZATION_KEYS if k in var), "")
        person, p_problems = parse_personalization(pers_text, cat)
        problems += p_problems
        if finish not in ("matte",) and finish in LEGACY_FINISHES:
            problems.append(f"old '{finish}' finish in the SKU: it is made in matte")
        try:
            qty = max(1, int(float(cell(row, c_qty) or 1)))
        except ValueError:
            qty = 1
        o = orders.get(order_id)
        if o is None:
            country, state = cell(row, c_country), cell(row, c_state)
            lang = "fr" if _key(state) in {_key(q) for q in QUEBEC} and _key(country) in ("canada", "ca") else "en"
            o = orders[order_id] = {"id": order_id, "customer": cell(row, c_buyer), "order_date": cell(row, c_date),
                                    "lang": lang, "lines": [], "transactions": [], "source": "etsy-csv"}
        tx = cell(row, c_tx)
        if tx:
            o["transactions"].append(tx)
        for _ in range(qty):
            o["lines"].append({"design": design or "", "pack": pack, "finish": "matte", **person,
                               "personalization": pers_text, "sku": sku, "review": list(problems)})
    res.orders = list(orders.values())
    return res
