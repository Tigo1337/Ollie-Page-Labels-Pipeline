"""Command line: python -m engine <command> ...

  fonts                       download the Google Fonts (+ licences)
  demo-art [--design ID]      write placeholder artwork for designs without art
  order ORDER.json            produce all files for an order (or several, = a batch)
  fontchart                   font chart PNG
  review DESIGN               design review sheet PNG
  packs                       labels per half / sheet, and halves / sheets per pack
  pack-samples --out DIR      a sample bundle for every pack × finish (demo art)
  calibration LAYOUT_ID       calibration PDF for one layout (marks + cut outlines, no art)
  layouts                     build the fixed half-sheet layouts (new versions only) + counts table
  layout-gallery --out DIR    one preview PNG per layout (printed view)
  templates --out DIR         cut templates per layout: SVG, DXF, JSON, calibration PDF (+ docs)
  docs                        docs/*.md and the generated README sections (French Studio steps)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .workspace import REPO


def _ws(args):
    from .workspace import open_workspace
    return open_workspace(args.config, args.data)


def cmd_fonts(args) -> int:
    from .config import load_catalog
    from .fonts_download import download_all
    cat = load_catalog(args.config)
    report = download_all(cat.fonts, Path(args.data) / "fonts", force=args.force)
    print("\n".join(report))
    return 1 if any("FAILED" in r for r in report) else 0


def cmd_demo_art(args) -> int:
    from .assets import LocalAssets
    from .config import load_catalog
    from .testart import write_design_art
    cat = load_catalog(args.config)
    la = LocalAssets(args.data)
    for d in cat.designs.values():
        if args.design and d.id not in args.design:
            continue
        if la.original_path(d.id, "wide") and not args.force:
            continue
        write_design_art(d, Path(args.data))
        print(f"placeholder art: {d.id}")
    return 0


def cmd_order(args) -> int:
    from .orders import Order
    ws = _ws(args)
    orders = [Order.load(p) for p in args.order]
    out = Path(args.out)
    t = time.time()
    res = ws.producer.run(orders, out, lang=args.lang, unpaired=args.unpaired)
    dt = time.time() - t
    print_run(res)
    print(f"{len(res.files)} files + {res.zip_path.name} in {out} ({dt:.1f} s)")
    return 0


def print_run(res) -> None:
    for f, s in res.summary["finishes"].items():
        print(f"{f}: {s['labels']} labels on {s['sheets']} sheet(s)")
    for sh in res.summary["sheets"]:
        bottom = sh["bottom"]["tag"] + (" (bonus)" if sh["bottom"]["bonus"] else "") if sh["bottom"] else "(blank)"
        print(f"  sheet {sh['n']}: {sh['layout_id']} {sh['finish']}  haut: {sh['top']['tag']}  |  bas: {bottom}")
    for w in res.summary["waiting"]:
        print(f"  WAITING: {w['tag']}")
    for w in res.warnings:
        print(f"WARNING: {w}")


def cmd_fontchart(args) -> int:
    from .proofs import font_chart
    ws = _ws(args)
    font_chart(ws.renderer, ws.ui, ws.texts, lang=args.lang).save(args.out)
    print(args.out)
    return 0


def cmd_review(args) -> int:
    from .proofs import review_sheet
    ws = _ws(args)
    out = args.out or f"review_{args.design}.png"
    review_sheet(ws.renderer, ws.ui, args.design, font_id=args.font, finish=args.finish).save(out)
    print(out)
    return 0


def cmd_packs(args) -> int:
    from .config import load_catalog
    from .proofs import pack_table
    cat = load_catalog(args.config)
    per, packs = pack_table(cat, _layouts_dir(args))
    print("Labels per layout")
    for sid, x in per.items():
        unit = " pairs" if x["pairs"] else ""
        print(f"  {cat.sizes[sid].label:<38} {x['layout_id']:<17} {x['per_half']:>4}{unit} per half "
              f"{x['per_sheet']:>4}{unit} per sheet")
    print("\nPacks (halves; sheets of material when batched / when printed alone)")
    for pid, x in packs.items():
        halves = ", ".join(f"{n} {s}" for s, n in x["halves_by_size"].items())
        print(f"  {cat.packs[pid].label:<42} {x['halves']} halves ({halves})  "
              f"{x['batched']:g} / {x['alone']} sheet(s)")
    return 0


def cmd_pack_samples(args) -> int:
    """For every pack × finish, a sample order with demo art, produced as a bundle."""
    from .assets import LocalAssets
    from .orders import Order, OrderLine
    from .testart import write_design_art
    ws = _ws(args)
    la = LocalAssets(args.data)
    design = ws.catalog.designs[args.design]
    if not la.original_path(design.id, "wide"):
        write_design_art(design, Path(args.data))
    out = Path(args.out)
    packs = args.pack or list(ws.catalog.packs)
    finishes = args.finish or list(ws.catalog.finishes)
    for pid in packs:
        for fid in finishes:
            order = Order(f"sample-{pid}-{fid}", [OrderLine(design.id, pid, fid, args.name, "", args.font)])
            res = ws.producer.run([order], out / f"{pid}_{fid}", unpaired=args.unpaired)
            sheets = res.summary["sheets"]
            print(f"{pid:<10} {fid:<12} {len(sheets)} sheet(s), {len(res.files)} files -> {res.zip_path}")
    return 0


def _layouts_dir(args) -> Path:
    return Path(args.layouts) if args.layouts else REPO / "layouts"


def cmd_layouts(args) -> int:
    from .config import load_catalog
    from .layout import rebuild
    cat = load_catalog(args.config)
    rows = rebuild(cat.sheet, cat.sizes, _layouts_dir(args))
    print(f"{'layout':<18} {'size':<24} {'arrangement':<11} {'per half':>9} {'per sheet':>10}  rows")
    for r in rows:
        lay, size = r.layout, cat.sizes[r.layout.size]
        unit = " pr" if size.shape == "pair" else ""
        note = {"new": "  (new file)", "unchanged": "",
                "differs": "  WARNING: the optimizer now gives different cells; published file kept"}[r.status]
        print(f"{lay.layout_id:<18} {size.dims_label:<24} {lay.arrangement:<11} {lay.per_half:>6}{unit:<3} "
              f"{lay.per_sheet:>7}{unit:<3}  {' + '.join(map(str, lay.rows))}{note}")
    return 1 if any(r.status == "differs" for r in rows) else 0


def cmd_layout_gallery(args) -> int:
    from .config import load_catalog
    from .gallery import write_gallery
    from .layout import current_layout
    cat = load_catalog(args.config)
    lays = [(current_layout(cat.sheet, s, _layouts_dir(args)), s) for s in cat.sizes.values()]
    font = Path(args.data) / "fonts" / "_ui" / "Nunito-UI-bold.ttf"
    for p in write_gallery(lays, cat.sheet, Path(args.out), dpi=args.dpi, font_path=font if font.exists() else None):
        print(p)
    return 0


def cmd_templates(args) -> int:
    from .config import load_catalog
    from .layout import current_layout
    from .templates import info, write_templates
    cat = load_catalog(args.config)
    print(f"{'template':<18} {'cut labels':>10}  cut group X / Y / W / H (mm, anchors excluded)")
    for size in cat.sizes.values():
        lay = current_layout(cat.sheet, size, _layouts_dir(args))
        write_templates(lay, size, cat.sheet, Path(args.out))
        i = info(lay, size, cat.sheet)
        b = i["cut_bbox"]
        print(f"{lay.layout_id:<18} {i['cut_labels']:>10}  {b['x']:g} / {b['y']:g} / {b['w']:g} / {b['h']:g}")
    from .templates import write_trim_line
    write_trim_line(cat.sheet, Path(args.out))
    print(f"written to {args.out} (+ the optional trim_line.svg / .dxf)")
    if not args.no_docs:
        return cmd_docs(args)
    return 0


def cmd_docs(args) -> int:
    """docs/studio-template-setup.md, docs/cut-settings.md and the generated sections of README.md."""
    from .config import load_catalog
    from .studio_docs import write_docs
    cat = load_catalog(args.config)
    for p in write_docs(cat, Path(args.config), _layouts_dir(args), REPO):
        print(p)
    return 0


def cmd_calibration(args) -> int:
    from .calibration import write_calibration
    from .config import load_catalog
    print(write_calibration(load_catalog(args.config), args.layout_id, Path(args.out), _layouts_dir(args)))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m engine", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(REPO / "config"))
    ap.add_argument("--data", default=str(REPO / "data"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fonts"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_fonts)
    p = sub.add_parser("demo-art"); p.add_argument("--design", nargs="*"); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_demo_art)
    p = sub.add_parser("order"); p.add_argument("order", nargs="+", help="order JSON file(s); several = one batch")
    p.add_argument("--out", default="out"); p.add_argument("--lang", default=None)
    p.add_argument("--unpaired", choices=["bonus", "blank", "wait"], default="bonus",
                   help="a half without a partner: print it with a bonus copy (default), with a blank half, or wait")
    p.set_defaults(fn=cmd_order)
    p = sub.add_parser("fontchart"); p.add_argument("--out", default="font_chart.png")
    p.add_argument("--lang", default="en"); p.set_defaults(fn=cmd_fontchart)
    p = sub.add_parser("review"); p.add_argument("design"); p.add_argument("--out")
    p.add_argument("--font", type=int, default=1); p.add_argument("--finish", default="matte")
    p.set_defaults(fn=cmd_review)
    p = sub.add_parser("packs"); p.add_argument("--layouts"); p.set_defaults(fn=cmd_packs)
    p = sub.add_parser("pack-samples"); p.add_argument("--out", default="out/pack-samples")
    p.add_argument("--pack", nargs="*"); p.add_argument("--finish", nargs="*")
    p.add_argument("--design", default="dino"); p.add_argument("--name", default="Léo")
    p.add_argument("--font", type=int, default=1)
    p.add_argument("--unpaired", choices=["bonus", "blank", "wait"], default="bonus")
    p.set_defaults(fn=cmd_pack_samples)
    p = sub.add_parser("calibration"); p.add_argument("layout_id"); p.add_argument("--out", default="out/calibration")
    p.add_argument("--layouts"); p.set_defaults(fn=cmd_calibration)
    p = sub.add_parser("layouts"); p.add_argument("--layouts", help="layouts folder (default: layouts/)")
    p.set_defaults(fn=cmd_layouts)
    p = sub.add_parser("layout-gallery"); p.add_argument("--out", default="out/layouts")
    p.add_argument("--layouts"); p.add_argument("--dpi", type=int, default=150)
    p.set_defaults(fn=cmd_layout_gallery)
    p = sub.add_parser("templates"); p.add_argument("--out", default=str(REPO / "templates"))
    p.add_argument("--no-docs", action="store_true", help="do not regenerate docs/ and the README sections")
    p.add_argument("--layouts"); p.set_defaults(fn=cmd_templates)
    p = sub.add_parser("docs"); p.add_argument("--layouts"); p.set_defaults(fn=cmd_docs)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except Exception as e:  # plain message, no stack trace
        if not isinstance(e, (ValueError, FileNotFoundError, KeyError)):
            raise
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
