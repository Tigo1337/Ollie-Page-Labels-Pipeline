"""Telling the pieces apart after trimming, with nothing printed on the sheet.

The print PDF carries no text, so after trimming the pieces are sorted into envelopes by what is
printed on them: each piece's labels show a child's name and a design. `envelopes` lists, per order
(one envelope), the pieces that go in it with where to find them (sheet number, haut / milieu / bas),
what the labels look like (size, name, design, font) and the envelope's postage (packing.order_envelope:
bonus copies go in only when they keep the same postage tier). `look_alikes` finds the pieces of
different orders that could be confused (same size and name, another design, font or accent), and
the pieces that are identical (any of them will do).

`write_guide` makes the printable packing guide: a card per envelope with a picture of each piece's
label and a box to tick, then the look-alikes side by side.
"""
from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from .geometry import PT_PER_MM as PT
from .layout import piece_name
from .packing import order_envelope

if TYPE_CHECKING:
    from .orders import Order
    from .production import ProductionResult, Producer


def _fold(s: str) -> str:
    """What the eye reads: no accents, no case, letters and digits only ("Léo-Paul" -> "leopaul")."""
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if c.isalnum() and not unicodedata.combining(c)).casefold()


def envelopes(producer: "Producer", orders: list["Order"], res: "ProductionResult") -> list[dict]:
    """One entry per order, in order: its pieces (grouped when several pieces carry the same label),
    its bonus copies and its envelope."""
    cat = producer.cat
    spots: dict[tuple[str, int], list[str]] = {}
    bonus: dict[str, list[tuple[object, str]]] = {}
    pieces: dict[str, dict[int, object]] = {}
    for sh in res.plan.sheets:
        n = len(sh.pieces)
        for i, p in enumerate(sh.pieces):
            if p is None:
                continue
            where = f"sheet {sh.n} {piece_name(i, n, 'fr')}"
            if p.bonus:
                bonus.setdefault(p.order_id, []).append((p, where))
            else:
                spots.setdefault((p.order_id, p.index), []).append(where)
                pieces.setdefault(p.order_id, {})[p.index] = p
    waiting: dict[str, int] = {}
    for p in res.plan.waiting:
        waiting[p.order_id] = waiting.get(p.order_id, 0) + 1
    out = []
    for o in orders:
        groups: dict[str, dict] = {}
        for idx in sorted(pieces.get(o.order_id, {})):
            p = pieces[o.order_id][idx]
            g = groups.get(p.key)
            if g is None:
                spec = res.labels[p.key].spec
                size = cat.sizes[p.size]
                g = groups[p.key] = {
                    "key": p.key, "size": p.size, "size_label": size.label.split(" (")[0], "name": spec.name,
                    "line2": spec.line2, "design": p.design,
                    "design_name": cat.designs[p.design].name if p.design in cat.designs else p.design,
                    "font": spec.font, "count": 0, "where": [], "tiers": []}
            g["count"] += 1
            g["where"] += spots[(o.order_id, idx)]
            g["tiers"].append(f"{p.index}/{p.of}")
        extra = bonus.get(o.order_id, [])
        env = order_envelope(sum(g["count"] for g in groups.values()), len(extra), cat.production)
        out.append({"order": o.order_id, "customer": o.customer, "groups": list(groups.values()),
                    "bonus": [{"key": p.key, "where": w} for p, w in extra], "waiting": waiting.get(o.order_id, 0),
                    "envelope": env})
    return out


def look_alikes(envs: list[dict]) -> list[dict]:
    """Pieces of different orders that could be mixed up after trimming: the same size and the same
    name as read (accents and case aside). `identical` = the very same label (interchangeable)."""
    by_look: dict[tuple, list[tuple[str, dict]]] = {}
    for e in envs:
        for g in e["groups"]:
            by_look.setdefault((g["size"], _fold(g["name"]), _fold(g["line2"])), []).append((e["order"], g))
    out = []
    for (size, _, _), items in by_look.items():
        if len({order for order, _ in items}) < 2:
            continue
        out.append({"size": size, "size_label": items[0][1]["size_label"], "name": items[0][1]["name"],
                    "identical": len({g["key"] for _, g in items}) == 1,
                    "pieces": [{"order": order,
                                "same_as": [o for o, h in items if h["key"] == g["key"] and o != order],
                                **{k: g[k] for k in ("key", "name", "line2", "design_name", "font", "where")}}
                               for order, g in items]})
    return out


# ---------------------------------------------------------------- the printable guide
PLUM = (0x3E / 255, 0x23 / 255, 0x52 / 255)
MUTED = (0.42, 0.35, 0.50)
LINE = (0.82, 0.78, 0.88)
WARN = (0.70, 0.12, 0.12)


def _thumb(lab, max_w_mm: float, max_h_mm: float, dpi: int = 200) -> tuple[ImageReader, float, float]:
    """A label render (cut size + bleed) scaled down for the guide; returns (image, w_mm, h_mm)."""
    w_mm, h_mm = lab.bleed_mm
    k = min(max_w_mm / w_mm, max_h_mm / h_mm)
    w, h = w_mm * k, h_mm * k
    px = (max(1, round(w / 25.4 * dpi)), max(1, round(h / 25.4 * dpi)))
    im = lab.image.convert("RGB").resize(px, Image.Resampling.LANCZOS)
    return ImageReader(im), w, h


def write_guide(producer: "Producer", res: "ProductionResult", envs: list[dict], path) -> None:
    """Portrait Letter pages: a card per envelope (a row per label: a box to tick, a picture of the
    label, what it says and where to find it), then the look-alikes side by side."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    regular, bold = producer.ui.reportlab()
    W, H = 215.9, 279.4
    c = rl_canvas.Canvas(str(path), pagesize=(W * PT, H * PT))
    c.setTitle(f"{res.prefix} packing guide")
    margin, pic_h, tx = 14.0, 12.0, 74.0        # page margin, picture height, where a row's text starts
    text_w = W - margin - 3 - tx
    y = margin
    thumbs: dict[tuple, tuple] = {}

    def Y(v: float) -> float:                  # mm from the top -> PDF points from the bottom
        return (H - v) * PT

    def wrap(s: str, font: str, size: float, width: float) -> list[str]:
        words, lines, cur = s.split(" "), [], ""
        for w in words:
            t = f"{cur} {w}".strip()
            if cur and stringWidth(t, font, size) / PT > width:
                lines.append(cur)
                cur = w
            else:
                cur = t
        return lines + ([cur] if cur else [])

    def block(parts: list[tuple[str, str, float, tuple]], width: float) -> list[tuple[str, str, float, tuple]]:
        """(text, font, size, colour) paragraphs -> wrapped lines."""
        return [(ln, f, sz, col) for t, f, sz, col in parts for ln in wrap(t, f, sz, width)]

    def draw_lines(x: float, top: float, lines) -> float:
        yy = top
        for ln, f, sz, col in lines:
            yy += sz * 0.42 + 1.2
            c.setFillColorRGB(*col)
            c.setFont(f, sz)
            c.drawString(x * PT, Y(yy), ln)
        return yy - top

    def lines_h(lines) -> float:
        return sum(sz * 0.42 + 1.2 for _, _, sz, _ in lines)

    def thumb(key: str):
        if key not in thumbs:
            thumbs[key] = _thumb(res.labels[key], tx - margin - 14, pic_h)
        return thumbs[key]

    def picture(key: str, top: float) -> None:
        rd, tw, th = thumb(key)
        c.drawImage(rd, (margin + 10) * PT, Y(top + 1.5 + th), tw * PT, th * PT)

    def new_page() -> None:
        nonlocal y
        c.showPage()
        y = margin

    def frame(top: float, bottom: float) -> None:
        c.setStrokeColorRGB(*LINE)
        c.setLineWidth(0.6)
        c.roundRect(margin * PT, Y(bottom), (W - 2 * margin) * PT, (bottom - top) * PT, 6, stroke=1, fill=0)

    intro = block([(f"Packing guide · {res.prefix}", bold, 15, PLUM),
                   ("Nothing is printed on the sheets but the labels. After trimming, sort the pieces into "
                    "envelopes by the pictures below (size, name, design). Where: the sheet number (the page order "
                    "of the print PDFs, see the info sheet), then haut / milieu / bas.", regular, 8.5, MUTED)],
                  W - 2 * margin)
    y += draw_lines(margin, y, intro) + 5

    for n, e in enumerate(envs, 1):
        env = e["envelope"]
        rows = []                              # (picture key or None, wrapped lines, tick box?)
        for g in e["groups"]:
            name = g["name"] + (f" / {g['line2']}" if g["line2"] else "")
            count = f"{g['count']} pieces · " if g["count"] > 1 else ""
            rows.append((g["key"], block([(f"{count}{g['size_label']} · {name}", bold, 9.5, PLUM),
                                          (f"{g['design_name']} · font {g['font']} · tiers {', '.join(g['tiers'])}",
                                           regular, 8, MUTED),
                                          (", ".join(g["where"]), regular, 8, MUTED)], text_w), True))
        if e["bonus"]:
            nb = len(e["bonus"])
            where = ", ".join(b["where"] for b in e["bonus"])
            copies = f"{nb} bonus cop{'ies' if nb > 1 else 'y'}"
            if env["bonus_in_envelope"]:
                head, col = f"+ {copies} (free): put {'them' if nb > 1 else 'it'} in this envelope", PLUM
            else:
                head = f"{copies} (free): keep {'them' if nb > 1 else 'it'} aside as spares"
                col = WARN
            parts = [(head, bold, 9, col), (where, regular, 8, MUTED)]
            if not env["bonus_in_envelope"]:
                parts.append((env["bonus_note"].split(": ", 1)[1].capitalize() + ".", regular, 8, MUTED))
            rows.append((e["bonus"][0]["key"], block(parts, text_w), False))
        if e["waiting"]:
            rows.append((None, block([(f"{e['waiting']} more piece(s) not printed yet: they wait for a full sheet",
                                       bold, 9, WARN)], text_w), False))
        who = f" · {e['customer']}" if e["customer"] else ""
        head = block([(f"Envelope {n} · Order #{e['order']}{who}", bold, 11, PLUM),
                      (f"{env['pieces']} piece{'s' if env['pieces'] != 1 else ''} · about {env['weight_g']:g} g, "
                       f"{env['thickness_mm']:g} mm · {env['lettermail']}", regular, 8.5,
                       WARN if env["kind"] != "standard" else MUTED)], W - 2 * margin - 6)
        heights = [max(pic_h + 3, lines_h(ln) + 3) for _, ln, _ in rows]
        if y + lines_h(head) + 4 + sum(heights) + 4 > H - margin and y > margin + 30:
            new_page()                         # keep a card on one page when it fits on one
        top = y
        y += draw_lines(margin + 3, y + 2, head) + 4
        for (key, ln, tick), h in zip(rows, heights):
            if y + h > H - margin:             # a very long card continues on the next page
                frame(top, y)
                new_page()
                top = y
            if tick:
                c.setStrokeColorRGB(*PLUM)
                c.rect((margin + 3) * PT, Y(y + 7), 4 * PT, 4 * PT, stroke=1, fill=0)
            if key is not None:
                picture(key, y)
            draw_lines(tx, y, ln)
            y += h
        frame(top, y + 2)
        y += 6

    alikes = look_alikes(envs)
    if alikes:
        if y + 40 > H - margin:
            new_page()
        y += 2
        y += draw_lines(margin, y, block([("Look-alikes: check these pieces twice", bold, 12, PLUM)],
                                         W - 2 * margin)) + 3
        for a in alikes:
            note = ("identical labels: any of these pieces will do" if a["identical"]
                    else "different labels with the same name: tell them apart by the design and the font")
            head = block([(f"{a['size_label']} · \u201c{a['name']}\u201d · {note}", bold, 9,
                           PLUM if a["identical"] else WARN)], W - 2 * margin - 6)
            rows = []
            for p in a["pieces"]:
                same = (" · same label as " + ", ".join(f"#{o}" for o in p["same_as"]) + " (either will do)"
                        if p["same_as"] and not a["identical"] else "")
                rows.append((p["key"], block([(f"Order #{p['order']} · {p['design_name']} · font {p['font']}{same}",
                                               bold, 9, PLUM), (", ".join(p["where"]), regular, 8, MUTED)], text_w)))
            heights = [max(pic_h + 3, lines_h(ln) + 3) for _, ln in rows]
            if y + lines_h(head) + 2 + sum(heights) > H - margin:
                new_page()
            y += draw_lines(margin + 3, y, head) + 2
            for (key, ln), h in zip(rows, heights):
                if y + h > H - margin:
                    new_page()
                picture(key, y)
                draw_lines(tx, y, ln)
                y += h
            y += 3
    c.save()
