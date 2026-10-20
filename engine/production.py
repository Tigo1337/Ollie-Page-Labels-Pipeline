"""Production files for one order or a batch of orders (a "bundle").

Orders fill whole halves of the fixed layouts; two halves of the same layout and finish make a
sheet (packing.py). For each finish × layout used: a print PDF (landscape pages with /Rotate 270,
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
from .layout import Layout, LayoutError, current_layout
from .orders import Expanded, Order, OrderError, expand
from .packing import BatchPlan, Half, SheetPlan, Unpaired, get_strategy
from .render import RenderedLabel, Renderer
from .sheetpdf import SheetPDF, studio_image
from .studio_docs import label_fn, studio_labels
from .templates import template_bytes
from .text import GlyphError
from .uifont import UIFonts

REPO = Path(__file__).resolve().parent.parent
GUTTER_PT = 6.0          # order text in the gutter
GUTTER_START = 25.0      # mm from the printed left edge
TOP_BASELINE = 1.5       # mm above the trim line (top half text, glyphs pointing away from the trim)
BOTTOM_BASELINE = 3.0    # mm below the trim line (bottom half text: cap top ≈ 1.5 mm below the trim)

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
        return ex, self.strategy.plan(ex.halves, unpaired, list(self.cat.sizes), list(self.cat.finishes))

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
        def half(h: Half | None) -> dict | None:
            if h is None:
                return None
            return {"order": h.order_id, "line": h.line, "size": h.size, "name": h.name, "finish": h.finish,
                    "index": h.index, "of": h.of, "bonus": h.bonus, "tag": h.tag}
        finishes: dict[str, dict] = {}
        for sh in res.plan.sheets:
            f = finishes.setdefault(sh.finish, {"sheets": 0, "labels": 0})
            f["sheets"] += 1
            per = len(self.layouts([sh.size])[sh.size].top) * (2 if self.cat.sizes[sh.size].shape == "pair" else 1)
            f["labels"] += per * len(sh.halves)
        return {
            "prefix": res.prefix, "orders": [o.order_id for o in orders], "finishes": finishes,
            "sheets": [{"n": sh.n, "finish": sh.finish, "layout_id": sh.layout_id, "size": sh.size,
                        "pdf": res.sheet_pdf[sh.n][0], "page": res.sheet_pdf[sh.n][1],
                        "proof": f"{res.prefix}_sheet{sh.n:02d}_proof.png",
                        "top": half(sh.top), "bottom": half(sh.bottom)} for sh in res.plan.sheets],
            "waiting": [half(h) for h in res.plan.waiting],
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
        """Landscape pages with /Rotate 270: marks, art at true size in the layout's cells only,
        trim ticks and guide, the order text in the gutter and a header line."""
        sheet = self.cat.sheet
        size = self.cat.sizes[lay.size]
        pdf = SheetPDF(path, sheet, title=path.stem,
                       keywords=f"layout_id={lay.layout_id}; geometry_hash={lay.geometry_hash}")
        regular, _ = self.ui.reportlab()
        cache: dict = {}
        for sh in sheets:
            top = self._cell_image(labels[sh.top.key], sh.size, cache)
            bottom = self._cell_image(labels[sh.bottom.key], sh.size, cache) if sh.bottom else None
            pdf.marks()
            pdf.trim()
            pdf.art(lay, [top] * len(lay.top) + [bottom] * len(lay.bottom), size)
            self._gutter_pdf(pdf.c, sheet, sh, regular)
            pdf.header(f"sheet: {sh.n} · template: {lay.layout_id}", font=regular)
            pdf.end_page()
        pdf.save()

    @staticmethod
    def _gutter_pdf(c: rl_canvas.Canvas, sheet: Sheet, sh: SheetPlan, font: str) -> None:
        """6 pt grey text in the gutter, reading left to right on the printed sheet, one line per half."""
        T, H = sheet.trim_x, sheet.paper_h
        k = PT_PER_MM
        c.saveState()
        c.setFillColorRGB(0.45, 0.45, 0.48)
        c.setFont(font, GUTTER_PT)
        for half, X in ((sh.top, T + TOP_BASELINE), (sh.bottom, T - BOTTOM_BASELINE)):
            text = "(blank)" if half is None else half.tag + (" · BONUS" if half.bonus else "")
            c.saveState()
            c.translate(X * k, (H - GUTTER_START) * k)
            c.rotate(-90)                     # Studio +Y = printed left to right; glyph tops toward +X
            c.drawString(0, 0, text)
            c.restoreState()
        c.restoreState()

    # ------------------------------------------------------------------
    def page_proof(self, sh: SheetPlan, lay: Layout, labels: dict[str, RenderedLabel]) -> Image.Image:
        """The printed sheet at proof resolution (printed view): art, red cut lines, hatched keep-outs,
        blue laminate notches, trim line, each half's order text; a bonus half is tinted."""
        sheet = self.cat.sheet
        size = self.cat.sizes[sh.size]
        dpi = self.cat.production.proof_dpi
        img, k = studio_canvas(sheet, dpi)
        b = sheet.bleed
        cache: dict = {}
        resized: dict[tuple[int, bool], Image.Image] = {}
        halves = [(sh.top, lay.top), (sh.bottom, lay.bottom)]
        for half, cells in halves:
            if half is None:
                continue
            src = self._cell_image(labels[half.key], sh.size, cache)
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
        T, tm = sheet.trim_x, sheet.trim_margin
        for half, x0, x1 in ((sh.top, T + tm, sheet.paper_w), (sh.bottom, 0, T - tm)):
            if half is not None and half.bonus:
                d.rectangle([x0 * k, 0, x1 * k, sheet.paper_h * k], fill=(255, 200, 0, 50))
        img = to_printed_view(img)
        d = ImageDraw.Draw(img)
        f = self.ui.pil(max(10, int(2.4 * k)), "bold")
        trim_y = (sheet.paper_w - T) * k
        for half, dy in ((sh.top, -3.6), (sh.bottom, 1.0)):
            text = "(blank)" if half is None else half.tag + ("  ·  BONUS (free copy)" if half.bonus else "")
            d.text((GUTTER_START * k, trim_y + dy * k), text, font=f, fill=(40, 40, 40))
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
                "top": sh.top.tag, "bottom": "(blank)" if sh.bottom is None else
                sh.bottom.tag + (" · BONUS" if sh.bottom.bonus else ""),
            })
        tpl = self.env.get_template("info_sheet.txt.j2")
        return tpl.render(
            title=res.prefix, generated=_dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            orders=[o.order_id for o in orders], sheets=sheets, templates=templates_used,
            waiting=[h.tag for h in res.plan.waiting], notch_dxf="laminate_notches.dxf",
            finishes=sorted({s["finish"] for s in sheets}), **self._studio_text_ctx(),
        )

    def packing_slip(self, orders: list[Order], res: ProductionResult) -> str:
        """Per order: its halves, the sheet each one is printed on and where (haut / bas)."""
        where: dict[tuple[str, int], list[str]] = {}
        for sh in res.plan.sheets:
            for half, pos in ((sh.top, "haut (top)"), (sh.bottom, "bas (bottom)")):
                if half is None:
                    continue
                note = " — BONUS, copie gratuite (free copy), same envelope" if half.bonus else ""
                where.setdefault((half.order_id, half.index), []).append(f"sheet {sh.n}, {pos}{note}")
        waiting = {(h.order_id, h.index) for h in res.plan.waiting}
        out = [f"PACKING SLIP — {res.prefix}", "=" * 60, ""]
        for o in orders:
            out.append(f"Order #{o.order_id}" + (f" ({o.customer})" if o.customer else ""))
            halves = [h for h in self._halves_of(res, o.order_id)]
            for h in halves:
                size = self.cat.sizes[h.size]
                spots = where.get((h.order_id, h.index), [])
                if (h.order_id, h.index) in waiting:
                    spots = ["WAITING for a partner half (not printed yet)"]
                out.append(f"  half {h.index}/{h.of}  {size.label:<34} {h.name:<24} {h.finish:<12} "
                           + "; ".join(spots))
            out.append("")
        return "\n".join(out) + "\n"

    @staticmethod
    def _halves_of(res: ProductionResult, order_id: str) -> list[Half]:
        seen: dict[int, Half] = {}
        for sh in res.plan.sheets:
            for h in sh.halves:
                if h.order_id == order_id and not h.bonus:
                    seen.setdefault(h.index, h)
        for h in res.plan.waiting:
            if h.order_id == order_id:
                seen.setdefault(h.index, h)
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
