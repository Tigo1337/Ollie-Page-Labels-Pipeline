"""Command line: python -m engine <command> ...

  fonts                       download the Google Fonts (+ licences)
  demo-art [--design ID]      write placeholder artwork for designs without art
  order ORDER.json            produce all files for an order (or several, = a batch)
  fontchart                   font chart PNG
  review DESIGN               design review sheet PNG
  packs                       labels per sheet and sheets per pack
  calibrate                   test sheet to check print/cut alignment on plain paper
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
    res = ws.producer.run(orders, out, lang=args.lang)
    dt = time.time() - t
    for f, s in res.summary["finishes"].items():
        print(f"{f}: {s['labels']} labels on {s['sheets']} sheet(s)")
    for p in res.pages:
        print(f"  {p.finish} page {p.n}: {p.count} labels, cut box X {p.x:.2f} Y {p.y:.2f} "
              f"W {p.w:.2f} H {p.h:.2f} mm")
    for w in res.warnings:
        print(f"WARNING: {w}")
    print(f"{len(res.files)} files + {res.zip_path.name} in {out} ({dt:.1f} s)")
    return 0


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
    per, sheets = pack_table(cat)
    print("Labels per full sheet")
    for sid, n in per.items():
        print(f"  {cat.sizes[sid].label:<24} {cat.sizes[sid].dims_label:<14} {n:>4}")
    print("\nSheets per pack (per finish)")
    for pid, n in sheets.items():
        p = cat.packs[pid]
        print(f"  {p.label:<28} {p.total:>4} labels  {n} sheet(s)")
    return 0


def cmd_calibrate(args) -> int:
    from .calibration import write_calibration
    from .config import load_catalog
    info = write_calibration(load_catalog(args.config).production, Path(args.out))
    print(f"calibration files in {args.out}: cut file at X {info['x']:.2f} Y {info['y']:.2f} mm")
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
    p.add_argument("--out", default="out"); p.add_argument("--lang", default=None); p.set_defaults(fn=cmd_order)
    p = sub.add_parser("fontchart"); p.add_argument("--out", default="font_chart.png")
    p.add_argument("--lang", default="en"); p.set_defaults(fn=cmd_fontchart)
    p = sub.add_parser("review"); p.add_argument("design"); p.add_argument("--out")
    p.add_argument("--font", type=int, default=1); p.add_argument("--finish", default="matte")
    p.set_defaults(fn=cmd_review)
    p = sub.add_parser("packs"); p.set_defaults(fn=cmd_packs)
    p = sub.add_parser("calibrate"); p.add_argument("--out", default="calibration")
    p.set_defaults(fn=cmd_calibrate)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except Exception as e:  # plain message, no stack trace
        if not isinstance(e, (ValueError, FileNotFoundError, KeyError)):
            raise
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
