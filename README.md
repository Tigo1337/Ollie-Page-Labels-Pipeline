# Label Pipeline

Turns Etsy orders for personalised kids' name labels into print-and-cut
production files for an Epson ET-2980 (US Letter) and a Silhouette Cameo 5.

## Status

- **Phase 1 – engine + CLI** ✅ (this commit)
- Phase 2 – design library (web app)
- Phase 3 – crop editor
- Phase 4 – orders
- Phase 5 – batching + polish

## Layout

```
engine/            pure-Python rendering engine (no web dependencies)
  config.py        catalogue dataclasses, loads config/*.json
  art.py           white-band trimming, crop presets, automatic layout
  text.py          NFC normalising, glyph check, text fitting
  render.py        one label at 600 dpi (+ render cache)
  packing.py       sheet packing strategies (tidy-rows default, compact-rows)
  cutfiles.py      R12 DXF + SVG writers
  production.py    print PDF, cut files, page proofs, info sheet, ZIP
  proofs.py        customer proof, holographic preview, review sheet, font chart
  fonts_download.py  Google Fonts downloader (+ licence files)
  cli.py           python -m engine ...
config/            seed data: production numbers, sizes, packs, finishes, fonts,
                   designs, proof wording (en/fr), info-sheet template
tests/             pytest suite (alignment, packing, text fit, golden, speed…)
examples/          sample order JSON
```

## Quick start

```bash
pip install -r requirements-dev.txt
python -m engine fonts                 # download the 17 fonts into data/fonts
python -m engine demo-art              # placeholder art for designs that have none
python -m engine packs                 # labels per sheet / sheets per pack
python -m engine order examples/order_school.json --out out/   # [--lang fr]
python -m engine review axolotl --out review.png
python -m engine fontchart --out font_chart.png
pytest
```

Real artwork goes in `data/designs/<id>/<id>_wide.jpg` and `<id>_square.jpg`
(the trimmed wide strip is cached next to it as `<id>_wide_trimmed.png`).

## Production numbers

All in `config/production.json` (mm): Letter page, 12 mm margin, 36 mm
keep-out squares at TL/TR/BL, 1.25 mm bleed, 3 mm gap between cut lines,
1 mm text safe zone, 600 dpi, 1.7 mm minimum cap height, 34 mm laminate notch.
