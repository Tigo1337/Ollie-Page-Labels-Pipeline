"""Production files for one order (or a batch of orders).

For each finish: a print PDF; per page a DXF + SVG cut file and a page proof PNG.
Plus laminate_notches.dxf (when a finish needs it), an info sheet, the customer
proof(s) and a ZIP of everything.
"""
from __future__ import annotations

import datetime as _dt
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from PIL import Image, ImageDraw
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from . import cutfiles
from .config import Catalog, Production
from .geometry import PT_PER_MM, bbox, cut_path, mm_to_px, px
from .orders import Expanded, Order, OrderError, expand
from .packing import Sheet, get_strategy
from .render import RenderedLabel, Renderer
from .text import GlyphError
from .uifont import UIFonts


@dataclass
class PageInfo:
    finish: str
    n: int
    count: int
    x: float
    y: float
    w: float
    h: float
    dxf: str
    svg: str
    proof: str
    orders: list[str]


@dataclass
class ProductionResult:
    out_dir: Path
    prefix: str
    files: list[Path] = field(default_factory=list)
    pages: list[PageInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sheets: dict[str, list[Sheet]] = field(default_factory=dict)
    labels: dict[str, RenderedLabel] = field(default_factory=dict)
    zip_path: Path | None = None
    summary: dict = field(default_factory=dict)


def safe_name(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "-" for c in s).strip("-") or "order"


def sheet_paths(sheet: Sheet, cat: Catalog) -> list[list[tuple[float, float]]]:
    prod = cat.production
    return [cut_path(cat.sizes[p.job.size], p.x, p.y, prod.rrect_segments, prod.circle_segments)
            for p in sheet.placements]


def notch_paths(prod: Production) -> list[list[tuple[float, float]]]:
    return [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)] for x0, y0, x1, y1 in prod.notch_rects()]


def draw_marks_pdf(c: rl_canvas.Canvas, prod: Production) -> None:
    if not prod.print_marks:
        return
    c.setFillColorRGB(0, 0, 0)
    for x0, y0, x1, y1 in prod.mark_rects():
        c.rect(x0 * PT_PER_MM, (prod.page_h - y1) * PT_PER_MM, (x1 - x0) * PT_PER_MM, (y1 - y0) * PT_PER_MM,
               stroke=0, fill=1)


class Producer:
    def __init__(self, renderer: Renderer, ui: UIFonts, texts: dict, template_dir: Path,
                 strategy: str | None = None):
        self.r = renderer
        self.cat = renderer.cat
        self.ui = ui
        self.texts = texts
        self.env = Environment(loader=FileSystemLoader(str(template_dir)), undefined=StrictUndefined,
                               keep_trailing_newline=True)
        self.strategy = get_strategy(strategy)

    # ------------------------------------------------------------------
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

    def run(self, orders: list[Order], out_dir: Path, prefix: str | None = None,
            lang: str | None = None, customer_proofs: bool = True) -> ProductionResult:
        from .proofs import customer_proof  # local import: proofs imports production helpers

        if not orders:
            raise OrderError("No orders to produce.")
        prefix = safe_name(prefix or (orders[0].order_id if len(orders) == 1
                                      else "batch-" + "-".join(o.order_id for o in orders)))
        out_dir.mkdir(parents=True, exist_ok=True)
        ex = expand(orders, self.cat)
        labels, warnings = self.render_all(ex)
        res = ProductionResult(out_dir=out_dir, prefix=prefix, warnings=warnings, labels=labels)
        multi = len(orders) > 1
        prod = self.cat.production

        for finish_id in [f for f in self.cat.finishes if f in ex.jobs_by_finish]:
            sheets = self.strategy.pack(ex.jobs_by_finish[finish_id], self.cat.sizes, prod)
            res.sheets[finish_id] = sheets
            pdf_path = out_dir / f"{prefix}_{finish_id}_print.pdf"
            self.write_pdf(sheets, labels, pdf_path)
            res.files.append(pdf_path)
            for n, sheet in enumerate(sheets, 1):
                paths = sheet_paths(sheet, self.cat)
                base = f"{prefix}_{finish_id}_p{n}"
                dxf = out_dir / f"{base}_cut.dxf"
                svg = out_dir / f"{base}_cut.svg"
                proof = out_dir / f"{base}_proof.png"
                dxf.write_text(cutfiles.dxf_r12(paths, prod.page_h, prod.page_w), encoding="ascii")
                svg.write_text(cutfiles.svg(paths, prod.page_w, prod.page_h), encoding="utf-8")
                self.page_proof(sheet, labels, self.cat.finishes[finish_id].notch, multi).save(proof)
                x0, y0, x1, y1 = bbox([p for path in paths for p in path])
                res.pages.append(PageInfo(finish_id, n, len(sheet.placements), x0, y0, x1 - x0, y1 - y0,
                                          dxf.name, svg.name, proof.name,
                                          sorted({p.job.order_id for p in sheet.placements})))
                res.files += [dxf, svg, proof]

        notch_name = f"{prefix}_laminate_notches.dxf"
        if any(self.cat.finishes[f].notch for f in res.sheets):
            p = out_dir / notch_name
            p.write_text(cutfiles.dxf_r12(notch_paths(prod), prod.page_h, prod.page_w, layer="NOTCH"),
                         encoding="ascii")
            res.files.append(p)

        info_txt = self.info_sheet_text(orders, res, notch_name)
        p_txt = out_dir / f"{prefix}_info_sheet.txt"
        p_txt.write_text(info_txt, encoding="utf-8")
        p_pdf = out_dir / f"{prefix}_info_sheet.pdf"
        self.text_pdf(info_txt, p_pdf)
        res.files += [p_txt, p_pdf]

        if customer_proofs:
            for o in orders:
                cp = out_dir / f"{safe_name(o.order_id)}_customer_proof.png"
                customer_proof(self, o, lang=lang or o.lang or "en").save(cp)
                res.files.append(cp)

        res.summary = {
            "prefix": prefix, "orders": [o.order_id for o in orders],
            "finishes": {f: {"sheets": len(s), "labels": sum(len(x.placements) for x in s)}
                         for f, s in res.sheets.items()},
            "pages": [p.__dict__ for p in res.pages], "warnings": warnings,
        }
        summ = out_dir / f"{prefix}_summary.json"
        summ.write_text(json.dumps(res.summary, indent=2, ensure_ascii=False), encoding="utf-8")
        res.files.append(summ)

        zp = out_dir / f"{prefix}.zip"
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in res.files:
                z.write(f, f.name)
        res.zip_path = zp
        return res

    # ------------------------------------------------------------------
    def write_pdf(self, sheets: list[Sheet], labels: dict[str, RenderedLabel], path: Path) -> None:
        """True size: every label image is drawn at its bleed-box size in mm, plus the
        registration marks (when `print_marks` is on). Nothing else is printed."""
        prod = self.cat.production
        b = prod.bleed
        c = rl_canvas.Canvas(str(path), pagesize=(prod.page_w * PT_PER_MM, prod.page_h * PT_PER_MM),
                             pageCompression=1)
        c.setTitle(path.stem)
        c.setCreator("Label Pipeline")
        readers: dict[str, ImageReader] = {}
        for sheet in sheets:
            for p in sheet.placements:
                lab = labels[p.job.key]
                rd = readers.get(p.job.key)
                if rd is None:
                    rd = readers[p.job.key] = ImageReader(lab.image)
                bw, bh = p.w + 2 * b, p.h + 2 * b
                x = (p.x - b) * PT_PER_MM
                y = (prod.page_h - (p.y - b) - bh) * PT_PER_MM
                c.drawImage(rd, x, y, width=bw * PT_PER_MM, height=bh * PT_PER_MM)
            draw_marks_pdf(c, prod)
            c.showPage()
        c.save()

    def page_proof(self, sheet: Sheet, labels: dict[str, RenderedLabel], notch: bool,
                   show_orders: bool) -> Image.Image:
        prod = self.cat.production
        dpi = prod.proof_dpi
        b = prod.bleed
        k = mm_to_px(1, dpi)
        page = Image.new("RGB", (px(prod.page_w, dpi), px(prod.page_h, dpi)), "white")
        small: dict[str, Image.Image] = {}
        for p in sheet.placements:
            im = small.get(p.job.key)
            if im is None:
                im = labels[p.job.key].image.resize((px(p.w + 2 * b, dpi), px(p.h + 2 * b, dpi)),
                                                    Image.Resampling.LANCZOS)
                small[p.job.key] = im
            page.paste(im, (int(round((p.x - b) * k)), int(round((p.y - b) * k))))
        for x0, y0, x1, y1 in prod.keepout_rects():
            page.paste(self._hatch(px(x1 - x0, dpi), px(y1 - y0, dpi), int(3 * k)),
                       (int(round(x0 * k)), int(round(y0 * k))))
        d = ImageDraw.Draw(page, "RGBA")
        if prod.print_marks:
            for x0, y0, x1, y1 in prod.mark_rects():
                d.rectangle([x0 * k, y0 * k, x1 * k - 1, y1 * k - 1], fill=(0, 0, 0, 255))
        if notch:
            for x0, y0, x1, y1 in prod.notch_rects():
                d.rectangle([x0 * k, y0 * k, x1 * k - 1, y1 * k - 1], outline=(0, 90, 255, 255), width=2)
        for path in sheet_paths(sheet, self.cat):
            pts = [(x * k, y * k) for x, y in path]
            d.line(pts + [pts[0]], fill=(230, 0, 0, 255), width=2)
        if show_orders:
            f = self.ui.pil(max(10, int(1.8 * k)), "bold")
            for p in sheet.placements:
                tag = f"#{p.job.order_id}"
                tx, ty = p.x * k + 3, p.y * k + 2
                tb = d.textbbox((tx, ty), tag, font=f)
                d.rectangle([tb[0] - 2, tb[1] - 1, tb[2] + 2, tb[3] + 1], fill=(255, 255, 255, 210))
                d.text((tx, ty), tag, font=f, fill=(0, 0, 0, 255))
        return page

    @staticmethod
    def _hatch(w: int, h: int, step: int) -> Image.Image:
        tile = Image.new("RGB", (w, h), (225, 225, 225))
        d = ImageDraw.Draw(tile)
        for t in range(-h, w, max(2, step)):
            d.line([(t, 0), (t + h, h)], fill=(150, 150, 150), width=1)
        d.rectangle([0, 0, w - 1, h - 1], outline=(120, 120, 120))
        return tile

    # ------------------------------------------------------------------
    def info_sheet_text(self, orders: list[Order], res: ProductionResult, notch_name: str) -> str:
        prod = self.cat.production
        finishes = []
        for fid, sheets in res.sheets.items():
            f = self.cat.finishes[fid]
            finishes.append({
                "id": fid, "label": f.label, "media": f.media, "laminate": f.laminate, "notch": f.notch,
                "sheets": len(sheets), "labels": sum(len(s.placements) for s in sheets),
                "pdf": f"{res.prefix}_{fid}_print.pdf",
                "pages": [p.__dict__ for p in res.pages if p.finish == fid],
            })
        notch_finishes = [f["label"] for f in finishes if f["notch"]]
        tpl = self.env.get_template("info_sheet.txt.j2")
        return tpl.render(
            title=res.prefix, generated=_dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            orders=[o.order_id for o in orders], finishes=finishes, notch_dxf=notch_name,
            any_notch=bool(notch_finishes), notch_finishes=notch_finishes, notch=f"{prod.notch:g}",
            mark_inset=f"{prod.mark_inset:g}", mark_length=f"{prod.mark_length:g}",
            mark_thickness=f"{prod.mark_thickness:g}",
        )

    def text_pdf(self, text: str, path: Path) -> None:
        """The info sheet as a printable PDF (for reading, not for print & cut)."""
        prod = self.cat.production
        W, H = prod.page_w * PT_PER_MM, prod.page_h * PT_PER_MM
        c = rl_canvas.Canvas(str(path), pagesize=(W, H))
        c.setTitle(path.stem)
        size = 8.0
        y = H - 40
        for line in text.splitlines():
            if y < 40:
                c.showPage()
                y = H - 40
            c.setFont("Courier", size)
            c.drawString(30, y, line.encode("cp1252", "replace").decode("cp1252"))
            y -= size * 1.35
        c.save()
