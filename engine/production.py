"""Production files for one order or a batch of orders (a "bundle").

Orders fill whole pieces of the fixed layouts; three pieces (thirds) of the same layout and finish
make a sheet (packing.py). For each finish × layout used: a print PDF (landscape pages with /Rotate 270,
like SCM's, one page per sheet). Plus, in the bundle ZIP:
  templates/<layout_id>.svg and .dxf   the layout's cut template (and its .studio3, when an
                                       up-to-date one was uploaded)
  laminate_notches.dxf                 laminate outline with the corner notches (every finish)
  page proofs, customer proof(s), the info sheet and a packing slip.
There are no per-order cut files: every sheet of a layout is cut with that layout's template.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas as rl_canvas

from . import cutfiles
from .config import Sheet
from .gallery import draw_cuts, draw_furniture, studio_canvas, to_printed_view
from .geometry import PT_PER_MM, px, shape_mask
from .layout import Layout, LayoutError, current_layout, piece_name
from .orders import Expanded, Order, OrderError, expand
from .packing import BatchPlan, Piece, SheetPlan, Unpaired, get_strategy
from .render import RenderedLabel, Renderer
from .sheetpdf import SheetPDF, studio_image
from .studio_docs import label_fn, studio_labels
from .templates import template_bytes
from .text import GlyphError
from .uifont import UIFonts

REPO = Path(__file__).resolve().parent.parent
GUTTER_START = 25.0      # mm from the printed left edge (page proofs: each piece's order text)

Studio3Provider = Callable[[str], "bytes | None"]


@dataclass
class ProductionResult:
    out_dir: Path
    prefix: str
    files: list[Path] = field(default_factory=list)
    arcnames: dict[str, str] = field(default_factory=dict)   # file name -> path inside the ZIP
    plan: BatchPlan = field(default_factory=BatchPlan)
    sheet_pdf: dict[int, tuple[str, int]] = field(default_factory=dict)  # sheet n -> (pdf name, page)
    warnings: list[str] = field(default_factory=list)
    labels: dict[str, RenderedLabel] = field(default_factory=dict)
    zip_path: Path | None = None
    summary: dict = field(default_factory=dict)
    envelopes: list[dict] = field(default_factory=list)   # one per order: pieces, bonus copies, postage


def safe_name(s: str) -> str:
    """ASCII-only file name part ("Émilie Rose" -> "Emilie-Rose")."""
    ascii_ = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    out = "".join(c if c.isalnum() or c in "-_." else "-" for c in ascii_)
    return re.sub(r"-{2,}", "-", out).strip("-.") or "order"


def laminate_outline(sheet: Sheet) -> list[tuple[float, float]]:
    """The laminate sheet's outline (Studio frame): the Letter page with a notch cut out of each
    mark corner, so the laminate never covers a mark. One closed path, clockwise on screen."""
    W, H, n = sheet.paper_w, sheet.paper_h, sheet.notch
    notched = {"TL", "TR", "BL"} | ({"BR"} if sheet.marks == 4 else set())
    corners = {   # each corner clockwise: the plain corner point, or the three points around its notch
        "TL": [(0, 0)] if "TL" not in notched else [(0, n), (n, n), (n, 0)],
        "TR": [(W, 0)] if "TR" not in notched else [(W - n, 0), (W - n, n), (W, n)],
        "BR": [(W, H)] if "BR" not in notched else [(W, H - n), (W - n, H - n), (W - n, H)],
        "BL": [(0, H)] if "BL" not in notched else [(n, H), (n, H - n), (0, H - n)],
    }
    return [pt for c in ("TL", "TR", "BR", "BL") for pt in corners[c]]


class Producer:
    def __init__(self, renderer: Renderer, ui: UIFonts, texts: dict, template_dir: Path,
                 strategy: str | None = None, layouts_dir: Path = REPO / "layouts",
                 config_dir: Path | None = None):
        self.r = renderer
        self.cat = renderer.cat
        self.ui = ui
        self.texts = texts
        self.env = Environment(loader=FileSystemLoader(str(template_dir)), undefined=StrictUndefined,
                               keep_trailing_newline=True)
        self.strategy = get_strategy(strategy)
        self.layouts_dir = Path(layouts_dir)
        self.config_dir = Path(config_dir) if config_dir else Path(template_dir).parent

    # ------------------------------------------------------------------
    def layouts(self, size_ids) -> dict[str, Layout]:
        out = {}
        for sid in size_ids:
            try:
                out[sid] = current_layout(self.cat.sheet, self.cat.sizes[sid], self.layouts_dir)
            except LayoutError as e:
                raise OrderError(str(e)) from e
        return out

    def expand(self, orders: list[Order]) -> Expanded:
        sizes = {s for o in orders for ln in o.lines if ln.pack in self.cat.packs
                 for s in self.cat.packs[ln.pack].contents if s in self.cat.sizes}
        return expand(orders, self.cat, self.layouts(sorted(sizes)))

    def render_all(self, ex: Expanded) -> tuple[dict[str, RenderedLabel], list[str]]:
        labels: dict[str, RenderedLabel] = {}
        warnings: list[str] = []
        for key, spec in ex.specs.items():
            try:
                lab = self.r.render(spec)
            except GlyphError as e:
                raise OrderError(f"Order {', '.join(ex.order_of_key[key])}: {e}") from e
            labels[key] = lab
            for w in lab.warnings:
                if w not in warnings:
                    warnings.append(w)
        return labels, warnings

    def plan(self, orders: list[Order], unpaired: Unpaired = "bonus") -> tuple[Expanded, BatchPlan]:
        ex = self.expand(orders)
        return ex, self.strategy.plan(ex.pieces, unpaired, list(self.cat.sizes), list(self.cat.finishes),
                                      per_sheet=self.cat.sheet.pieces)

    def run(self, orders: list[Order], out_dir: Path, prefix: str | None = None, lang: str | None = None,
            customer_proofs: bool = True, unpaired: Unpaired = "bonus",
            studio3: Studio3Provider | None = None) -> ProductionResult:
        from .proofs import customer_proof  # local import: proofs imports production helpers

        if not orders:
            raise OrderError("No orders to produce.")
        prefix = safe_name(prefix or (orders[0].order_id if len(orders) == 1
                                      else "batch-" + "-".join(o.order_id for o in orders)))
        out_dir.mkdir(parents=True, exist_ok=True)
        ex, plan = self.plan(orders, unpaired)
        labels, warnings = self.render_all(ex)
        warnings = ex.warnings + warnings
        res = ProductionResult(out_dir=out_dir, prefix=prefix, warnings=warnings, labels=labels, plan=plan)
        layouts = self.layouts(sorted({sh.size for sh in plan.sheets}))
        sheet = self.cat.sheet

        def add(path: Path, arc: str | None = None) -> None:
            res.files.append(path)
            res.arcnames[path.name] = arc or path.name

        # print PDFs: one per finish × layout, one page per sheet
        groups: dict[tuple[str, str], list[SheetPlan]] = {}
        for sh in plan.sheets:
            groups.setdefault((sh.finish, sh.layout_id), []).append(sh)
        for (finish_id, layout_id), sheets in groups.items():
            lay = layouts[sheets[0].size]
            pdf_path = out_dir / f"{prefix}_{finish_id}_{layout_id}_print.pdf"
            self.write_pdf(sheets, lay, labels, pdf_path)
            for page, sh in enumerate(sheets, 1):
                res.sheet_pdf[sh.n] = (pdf_path.name, page)
            add(pdf_path)
        for sh in plan.sheets:
            proof = out_dir / f"{prefix}_sheet{sh.n:02d}_proof.png"
            self.page_proof(sh, layouts[sh.size], labels).save(proof)
            add(proof)

        # the cut templates of every layout used (+ the .studio3 when an up-to-date one exists)
        templates_used = []
        for size_id, lay in layouts.items():
            size = self.cat.sizes[size_id]
            entry = {"layout_id": lay.layout_id, "studio3": False}
            for kind in ("svg", "dxf"):
                p = out_dir / f"{lay.layout_id}.{kind}"
                p.write_bytes(template_bytes(lay, size, sheet, kind))
                add(p, f"templates/{p.name}")
            data = studio3(lay.layout_id) if studio3 else None
            if data:
                p = out_dir / f"{lay.layout_id}.studio3"
                p.write_bytes(data)
                add(p, f"templates/{p.name}")
                entry["studio3"] = True
            templates_used.append(entry)

        if plan.sheets:
            p = out_dir / "laminate_notches.dxf"
            p.write_text(cutfiles.dxf_r12_layers({"NOTCH": [laminate_outline(sheet)]}, sheet.paper_w, sheet.paper_h,
                                                 comments=["Laminate outline with the mark-corner notches. "
                                                           "Studio frame (landscape Letter), place at X 0 / Y 0."]),
                         encoding="ascii")
            add(p)

        from .packing_guide import envelopes, write_guide
        res.envelopes = envelopes(self, orders, res)
        guide = out_dir / f"{prefix}_packing_guide.pdf"
        write_guide(self, res, res.envelopes, guide)
        add(guide)

        info_txt = self.info_sheet_text(orders, res, templates_used)
        for name, text in ((f"{prefix}_info_sheet", info_txt), (f"{prefix}_packing_slip", self.packing_slip(orders, res))):
            p_txt = out_dir / f"{name}.txt"
            p_txt.write_text(text, encoding="utf-8")
            p_pdf = out_dir / f"{name}.pdf"
            self.text_pdf(text, p_pdf)
            add(p_txt)
            add(p_pdf)

        if customer_proofs:
            for o in orders:
                cp = out_dir / f"{safe_name(o.order_id)}_customer_proof.png"
                customer_proof(self, o, lang=lang or o.lang or "en").save(cp)
                add(cp)

        res.summary = self.summary(orders, res, templates_used)
        summ = out_dir / f"{prefix}_summary.json"
        summ.write_text(json.dumps(res.summary, indent=2, ensure_ascii=False), encoding="utf-8")
        add(summ)

        zp = out_dir / f"{prefix}.zip"
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in res.files:
                z.write(f, res.arcnames[f.name])
        res.zip_path = zp
        return res

    # ------------------------------------------------------------------
    def summary(self, orders: list[Order], res: ProductionResult, templates_used: list[dict]) -> dict:
        from .packing_guide import look_alikes
        def piece(p: Piece | None) -> dict | None:
            if p is None:
                return None
            return {"order": p.order_id, "line": p.line, "size": p.size, "name": p.name, "finish": p.finish,
                    "index": p.index, "of": p.of, "bonus": p.bonus, "tag": p.tag}
        finishes: dict[str, dict] = {}
        for sh in res.plan.sheets:
            f = finishes.setdefault(sh.finish, {"sheets": 0, "labels": 0})
            f["sheets"] += 1
            per = self.layouts([sh.size])[sh.size].per_piece * (2 if self.cat.sizes[sh.size].shape == "pair" else 1)
            f["labels"] += per * len(sh.filled)
        return {
            "prefix": res.prefix, "orders": [o.order_id for o in orders], "finishes": finishes,
            "sheets": [{"n": sh.n, "finish": sh.finish, "layout_id": sh.layout_id, "size": sh.size,
                        "pdf": res.sheet_pdf[sh.n][0], "page": res.sheet_pdf[sh.n][1],
                        "proof": f"{res.prefix}_sheet{sh.n:02d}_proof.png",
                        "pieces": [piece(p) for p in sh.pieces]} for sh in res.plan.sheets],
            "waiting": [piece(p) for p in res.plan.waiting],
            "envelopes": [{"order": e["order"], "customer": e["customer"], "waiting": e["waiting"],
                           "labels": [{k: g[k] for k in ("size", "size_label", "name", "line2", "design_name", "font",
                                                         "count", "where")} for g in e["groups"]],
                           "bonus_where": [b["where"] for b in e["bonus"]], **e["envelope"]} for e in res.envelopes],
            "look_alikes": [{k: a[k] for k in ("size", "size_label", "name", "identical")} |
                            {"orders": [p["order"] for p in a["pieces"]]} for a in look_alikes(res.envelopes)],
            "packing_guide": f"{res.prefix}_packing_guide.pdf",
            "templates": templates_used, "warnings": res.warnings,
        }

    # ------------------------------------------------------------------
    def _cell_image(self, lab: RenderedLabel, size_id: str, cache: dict) -> Image.Image:
        """The label image for the PDF: round labels get their circular bleed as alpha."""
        size = self.cat.sizes[size_id]
        if size.shape != "circle":
            return lab.image
        key = id(lab)
        if key not in cache:
            b = self.cat.sheet.bleed
            im = lab.image.convert("RGBA")
            im.putalpha(shape_mask(size, b, (size.w + 2 * b, size.h + 2 * b), (b, b), lab.dpi))
            cache[key] = im
        return cache[key]

    def write_pdf(self, sheets: list[SheetPlan], lay: Layout, labels: dict[str, RenderedLabel], path: Path) -> None:
        """Landscape pages with /Rotate 270 holding only what belongs on the sheet: the registration
        marks, the art at true size in the layout's cells, and the trim ticks and guides delimiting the
        pieces. No text: which sheet and piece is which is on the page proofs, info sheet and packing
        slip (sheet number = page order, haut / milieu / bas)."""
        sheet = self.cat.sheet
        size = self.cat.sizes[lay.size]
        pdf = SheetPDF(path, sheet, title=path.stem,
                       keywords=f"layout_id={lay.layout_id}; geometry_hash={lay.geometry_hash}")
        cache: dict = {}
        for sh in sheets:
            images = []
            for p, cells in zip(sh.pieces, lay.pieces):
                im = self._cell_image(labels[p.key], sh.size, cache) if p is not None else None
                images += [im] * len(cells)
            pdf.marks()
            pdf.trim()
            pdf.art(lay, images, size)
            pdf.end_page()
        pdf.save()

    # ------------------------------------------------------------------
    def page_proof(self, sh: SheetPlan, lay: Layout, labels: dict[str, RenderedLabel]) -> Image.Image:
        """The printed sheet at proof resolution (printed view): art, red cut lines, hatched keep-outs,
        blue laminate notches, trim lines, each piece's order text; a bonus piece is tinted."""
        sheet = self.cat.sheet
        size = self.cat.sizes[sh.size]
        dpi = self.cat.production.proof_dpi
        img, k = studio_canvas(sheet, dpi)
        b = sheet.bleed
        cache: dict = {}
        resized: dict[tuple[int, bool], Image.Image] = {}
        for piece, cells in zip(sh.pieces, lay.pieces):
            if piece is None:
                continue
            src = self._cell_image(labels[piece.key], sh.size, cache)
            for X, Y, w, h, rot in cells:
                key = (id(src), rot)
                if key not in resized:
                    resized[key] = studio_image(src, rot).resize((px(w + 2 * b, dpi), px(h + 2 * b, dpi)),
                                                                 Image.Resampling.LANCZOS)
                im = resized[key]
                img.paste(im, (int(round((X - b) * k)), int(round((Y - b) * k))), im if im.mode == "RGBA" else None)
        d = ImageDraw.Draw(img, "RGBA")
        draw_furniture(d, sheet, k, gutter=False, margin=False)
        draw_cuts(d, lay, size, sheet, k, bleed_fill=False)
        tm = sheet.trim_margin
        for i, piece in enumerate(sh.pieces):
            if piece is not None and piece.bonus:
                x0, x1 = sheet.piece_span(i)
                x0, x1 = (x0 + tm if x0 > 0 else 0), (x1 - tm if x1 < sheet.paper_w else sheet.paper_w)
                d.rectangle([x0 * k, 0, x1 * k, sheet.paper_h * k], fill=(255, 200, 0, 50))
        img = to_printed_view(img)
        d = ImageDraw.Draw(img)
        f = self.ui.pil(max(10, int(2.4 * k)), "bold")
        trims_y = [(sheet.paper_w - T) * k for T in reversed(sheet.trims)]   # printed, top to bottom
        for i, piece in enumerate(sh.pieces):
            y = trims_y[0] - 3.6 * k if i == 0 else trims_y[i - 1] + 1.0 * k
            text = "(blank)" if piece is None else piece.tag + ("  ·  BONUS (free copy)" if piece.bonus else "")
            d.text((GUTTER_START * k, y), text, font=f, fill=(40, 40, 40))
        head = self.ui.pil(max(10, int(3.2 * k)), "bold")
        finish = self.cat.finishes[sh.finish].label if sh.finish in self.cat.finishes else sh.finish
        d.text((GUTTER_START * k, 2.5 * k), f"Sheet {sh.n} · {lay.layout_id} · {finish}", font=head, fill=(0, 0, 0))
        return img

    # ------------------------------------------------------------------
    def _studio_text_ctx(self) -> dict:
        labels = studio_labels(self.config_dir)
        return {"L": label_fn(labels, markdown=False), "sheet": self.cat.sheet}

    def info_sheet_text(self, orders: list[Order], res: ProductionResult, templates_used: list[dict]) -> str:
        sheets = []
        for sh in res.plan.sheets:
            pdf, page = res.sheet_pdf[sh.n]
            has_s3 = any(t["layout_id"] == sh.layout_id and t["studio3"] for t in templates_used)
            sheets.append({
                "n": sh.n, "pdf": pdf, "page": page, "layout_id": sh.layout_id,
                "finish": self.cat.finishes[sh.finish].label if sh.finish in self.cat.finishes else sh.finish,
                "template": f"{sh.layout_id}.studio3" if has_s3 else f"{sh.layout_id}.svg",
                "pieces": [{"where": piece_name(i, len(sh.pieces), "fr"),
                            "tag": "(blank)" if p is None else p.tag + (" · BONUS" if p.bonus else "")}
                           for i, p in enumerate(sh.pieces)],
            })
        tpl = self.env.get_template("info_sheet.txt.j2")
        return tpl.render(
            title=res.prefix, generated=_dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            orders=[o.order_id for o in orders], sheets=sheets, templates=templates_used,
            waiting=[h.tag for h in res.plan.waiting], notch_dxf="laminate_notches.dxf",
            finishes=sorted({s["finish"] for s in sheets}), **self._studio_text_ctx(),
        )

    def packing_slip(self, orders: list[Order], res: ProductionResult) -> str:
        """Per order: its pieces, the sheet each one is printed on and where (haut / milieu / bas), and its
        envelope (postage; bonus copies go in only when they keep the same postage tier)."""
        env_of = {e["order"]: e["envelope"] for e in res.envelopes}
        where: dict[tuple[str, int], list[str]] = {}
        for sh in res.plan.sheets:
            n = len(sh.pieces)
            for i, piece in enumerate(sh.pieces):
                if piece is None:
                    continue
                pos = f"{piece_name(i, n, 'fr')} ({piece_name(i, n)})"
                note = ""
                if piece.bonus:
                    env = env_of.get(piece.order_id, {})
                    note = (" — BONUS, copie gratuite (free copy), same envelope" if env.get("bonus_in_envelope")
                            else " — BONUS, copie gratuite: keep aside as a spare (it would raise the postage)")
                where.setdefault((piece.order_id, piece.index), []).append(f"sheet {sh.n}, {pos}{note}")
        waiting = {(p.order_id, p.index) for p in res.plan.waiting}
        out = [f"PACKING SLIP — {res.prefix}", "=" * 60, ""]
        for o in orders:
            out.append(f"Order #{o.order_id}" + (f" ({o.customer})" if o.customer else ""))
            for p in self._pieces_of(res, o.order_id):
                size = self.cat.sizes[p.size]
                spots = where.get((p.order_id, p.index), [])
                if (p.order_id, p.index) in waiting:
                    spots = ["WAITING for more pieces to fill a sheet (not printed yet)"]
                out.append(f"  {f'tiers {p.index}/{p.of}':<12} {size.label:<37} {p.name:<24} " + "; ".join(spots))
            env = env_of.get(o.order_id)
            if env:
                out.append(f"  Envelope: {env['pieces']} piece(s), about {env['weight_g']:g} g and "
                           f"{env['thickness_mm']:g} mm — {env['lettermail']}"
                           + (f"; {env['bonus_note']}" if env.get("bonus_note") else ""))
            out.append("")
        return "\n".join(out) + "\n"

    @staticmethod
    def _pieces_of(res: ProductionResult, order_id: str) -> list[Piece]:
        seen: dict[int, Piece] = {}
        for sh in res.plan.sheets:
            for p in sh.filled:
                if p.order_id == order_id and not p.bonus:
                    seen.setdefault(p.index, p)
        for p in res.plan.waiting:
            if p.order_id == order_id:
                seen.setdefault(p.index, p)
        return [seen[i] for i in sorted(seen)]

    def text_pdf(self, text: str, path: Path) -> None:
        """A text document as a printable portrait PDF (for reading, not for print & cut)."""
        sheet = self.cat.sheet
        W, H = sheet.paper_h * PT_PER_MM, sheet.paper_w * PT_PER_MM
        c = rl_canvas.Canvas(str(path), pagesize=(W, H))
        c.setTitle(path.stem)
        regular, _ = self.ui.reportlab()
        size = 8.0
        y = H - 40
        for line in text.splitlines():
            if y < 40:
                c.showPage()
                y = H - 40
            c.setFont(regular, size)
            c.drawString(30, y, line)
            y -= size * 1.35
        c.save()
