# Label Pipeline

Turns Etsy orders for personalised kids' name labels into print-and-cut
production files for an Epson ET-2980 (US Letter) and a Silhouette Cameo 5.

## Status

- **Phase 1 – engine + CLI** ✅
- **Phase 2 – web app + design library** ✅ (plus a first "Make labels" screen)
- **Phase 3 – crop editor** ✅
- **Fixed half-sheet layouts** (reference/layout-update-prompt.md) ✅ phases 1–4: layouts,
  cut templates, half-sheet batching and bundles, new sizes and the database migration
- Orders screen (CSV import, status tracking), pricing helper – to do

## Running the app (Replit)

1. Import this GitHub repo into Replit and press **Run** (`scripts/start.sh`: installs
   builds the React frontend if needed, starts FastAPI on port 5000).
   Python packages must first be installed through Replit's package manager
   (see `requirements.txt`; optional storage package: `replit-object-storage`).
2. In **Secrets** add `LABELS_API_SECRET` (the password for the app). Without it the
   app is open to anyone who has the URL and shows a warning banner.
3. **Object Storage:** create a bucket in the Replit Object Storage tool. Artwork,
   fonts and generated files go there. Outside Replit they go to `data/blobs/`.
4. **Database:** SQLite in `data/app.db` by default. For a Replit *deployment*
   (whose disk is not persistent) add a Replit PostgreSQL database: the app picks up
   `DATABASE_URL` automatically.
5. Fonts are downloaded automatically on first start (see the Fonts page).

Environment variables: `LABELS_API_SECRET`, `LABELS_DATA_DIR`, `LABELS_STORAGE`
(`auto` | `replit` | `local`), `LABELS_DATABASE_URL` / `DATABASE_URL`, `PORT`.

Local development: `pip install -r requirements-dev.txt`, `bash scripts/start.sh`
(or `uvicorn app.main:_app_factory --factory --reload` plus `cd frontend && npm run dev`).

## Layout

```
engine/            pure-Python rendering engine (no web dependencies)
  config.py        catalogue dataclasses, loads config/*.json (incl. sheet.json geometry)
  frames.py        Studio frame <-> printed view (the only place frames are converted)
  layout.py        fixed half-sheet layout optimizer (port of reference/sheet_opt.py)
  gallery.py       layout preview PNGs
  marks.py         Type 1 registration marks (port of SCM's generate_reg_mark)
  sheetpdf.py      landscape /Rotate 270 PDF pages in the Studio frame (marks, trim, art)
  templates.py     cut templates per layout: SVG, DXF (+ anchors), JSON, calibration PDF
  studio_docs.py   French Studio instructions from config/studio_labels.json
  calibration.py   per-layout calibration sheet
  art.py           white-band trimming, crop presets, automatic layout
  text.py          NFC normalising, glyph check, text fitting
  render.py        one label at 600 dpi (+ render cache)
  packing.py       half-sheet batching (pairs halves of the same layout and finish)
  cutfiles.py      R12 DXF + SVG writers
  production.py    bundle: print PDFs per finish × layout, templates, page proofs, info sheet, packing slip, ZIP
  proofs.py        customer proof, holographic preview, review sheet, font chart
  fonts_download.py  Google Fonts downloader (+ licence files)
  cli.py           python -m engine ...
config/            seed data: sheet geometry (sheet.json), production numbers, sizes, packs,
                   finishes, fonts, designs, proof wording (en/fr), info-sheet template
layouts/           published fixed layouts, chels-<size>-v<N>.json (never edited in place)
templates/         generated cut templates for the current layouts (python -m engine templates)
docs/              studio-template-setup.md (generated, French)
reference/         prototype code and specs the engine is ported from
app/               FastAPI app: storage interface (repo.py), blob storage, auth,
                   engine wiring, API routes (api.py)
frontend/          React + Vite + TypeScript UI, built into frontend/dist
scripts/start.sh   one run command
tests/             pytest suite (alignment, packing, text fit, golden, speed…)
examples/          sample order JSON
```

## Quick start

```bash
pip install -r requirements-dev.txt
python -m engine fonts                 # download the 17 fonts into data/fonts
python -m engine demo-art              # placeholder art for designs that have none
python -m engine packs                 # labels per half / sheet, halves and sheets per pack
python -m engine pack-samples --out out/samples      # a bundle for every pack × finish (demo art)
python -m engine layouts               # fixed half-sheet layouts + counts (writes -v2… only on a geometry change)
python -m engine layout-gallery --out out/layouts   # one preview PNG per layout
python -m engine templates             # templates/*.svg|dxf|json|_calibration.pdf + docs/studio-template-setup.md
python -m engine calibration chels-small-v1         # one calibration PDF
python -m engine order examples/order_school.json --out out/   # [--lang fr]
python -m engine review axolotl --out review.png
python -m engine fontchart --out font_chart.png
pytest
```

Real artwork goes in `data/designs/<id>/<id>_wide.jpg` and `<id>_square.jpg`
(the trimmed wide strip is cached next to it as `<id>_wide_trimmed.png`).

## Production numbers

Sheet geometry is in `config/sheet.json` (mm, Silhouette Studio's landscape frame): Type 1 marks
(3 marks, inset 10, length 10, thickness 1), 21.5 mm ink / 23.5 mm cut keep-outs on all four
corners, 22 mm laminate notch (every finish), 10 mm edge margin, trim line at Studio X 139.7 with
5 mm clear each side, 2.5 mm gap (2.0 mm between round labels), 1.25 mm bleed, 600 dpi.
`config/production.json` keeps the 1 mm text safe zone, the 1.7 mm minimum cap height and the
150 dpi proof resolution.

Every size has one fixed layout (`layouts/`) with two identical halves per sheet; a pack is a whole
number of halves, two halves of the same size and finish make a sheet, and every sheet of a layout
is cut with that layout's template (`templates/`, built once in Studio: `docs/studio-template-setup.md`).
