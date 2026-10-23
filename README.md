# Label Pipeline

Turns Etsy orders for personalised kids' name labels into print-and-cut
production files for an Epson ET-2980 (US Letter) and a Silhouette Cameo 5.

## Status

- **Phase 1 – engine + CLI** ✅
- **Phase 2 – web app + design library** ✅ (plus a first "Make labels" screen)
- **Phase 3 – crop editor** ✅
- **Fixed half-sheet layouts** (reference/layout-update-prompt.md) ✅ phases 1–4: layouts,
  cut templates, half-sheet batching and bundles, new sizes and the database migration
- **Etsy listings** ✅ designs grouped into listings, listing images, Etsy import CSV
  (`docs/etsy-listings.md`)
- Orders screen (CSV import, status tracking) – to do

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
Optional, to host the Etsy listing images on Cloudflare R2 (`docs/etsy-listings.md`): `R2_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL`, `R2_ENDPOINT`,
`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ZONE_ID`.

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
  listings.py      Etsy listings: design groups, checks, import CSV (binder pipeline's format)
  listing_images.py  listing photos: close-ups on a sheet, designs, fonts, bundles, sizes
  fonts_download.py  Google Fonts downloader (+ licence files)
  cli.py           python -m engine ...
config/            seed data: sheet geometry (sheet.json), production numbers, sizes, packs,
                   finishes, fonts, designs, proof wording (en/fr), info-sheet template
layouts/           published fixed layouts, chels-<size>-v<N>.json (never edited in place)
templates/         generated cut templates for the current layouts (python -m engine templates)
docs/              studio-template-setup.md (generated, French), etsy-listings.md
reference/         prototype code and specs the engine is ported from
app/               FastAPI app: storage interface (repo.py), blob storage, auth,
                   engine wiring, API routes (api.py), Etsy listings (listings_*.py, r2.py)
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
python -m engine listings --out out/listings --group pets-cuddly   # listing images + Etsy CSV
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
150 dpi proof resolution. Changing `sheet.json` changes the layouts' geometry hash: run
`python -m engine layouts` (new `-v2` layouts), then rebuild the Studio templates.

Starting kiss-cut settings: `docs/cut-settings.md`. Building a Studio template once per layout:
`docs/studio-template-setup.md`.

<!-- generated:layouts -->
## Fixed layouts in thirds

*Generated by `python -m engine docs` from `layouts/`.*

Every label size has one fixed layout. A sheet is trimmed into 3 identical pieces
(thirds, each ships flat in a #10 envelope): the middle piece is the top piece moved down by one
piece, the bottom piece is the top piece mirrored about the page centre. A pack is a whole number of
pieces, and 3 pieces of the same size make a sheet. Each layout has one cut template,
built once in Silhouette Studio.

| Layout | Size | Arrangement | Per piece | Per sheet | Rows (top piece) |
|---|---|---|---:|---:|---|
| `chels-pencil-v2` | 57 × 9.5 mm | normal | 17 | 51 | 2 + 3 + 3 + 3 + 3 + 3 |
| `chels-small-v2` | 44.5 × 12.7 mm | normal | 19 | 57 | 3 + 4 + 4 + 4 + 4 |
| `chels-medium-v2` | 63.5 × 19 mm | normal | 8 | 24 | 2 + 3 + 3 |
| `chels-large-v2` | 63.5 × 25.4 mm | rotated | 6 | 18 | 6 |
| `chels-tag-v2` | 25.4 × 12.7 mm | normal | 34 | 102 | 6 + 7 + 7 + 7 + 7 |
| `chels-round-v2` | 32 mm Ø | normal | 10 | 30 | 5 + 5 |
| `chels-shoe-v2` | 2 × (30 × 38) mm | rotated | 4 pairs | 12 pairs | 4 |

Commands: `python -m engine layouts` (rebuild; a geometry change writes a new `-v2` file, a published
layout is never edited), `python -m engine layout-gallery --out DIR`, `python -m engine templates`,
`python -m engine calibration <layout_id>`, `python -m engine docs`.
<!-- /generated:layouts -->

<!-- generated:print-and-cut -->
## Imprimer et découper une planche

*Section générée par `python -m engine docs` (libellés Studio : `config/studio_labels.json`).
Les libellés marqués ⚠ sont à confirmer dans votre Studio.*

**Une fois par mise en page** : créez le modèle Studio et vérifiez-le avec la feuille de calibrage
(`docs/studio-template-setup.md`), puis téléversez le `.studio3` dans la page **Templates** de l'appli.

**Pour chaque planche** (le lot ZIP contient tout ; la fiche d'info dit quel modèle ouvrir) :

1. **Imprimer** le PDF d'impression à 100 % (**Taille réelle** (Actual size) ⚠, sans « ajuster à la page »),
   une feuille à la fois sur l'Epson ET-2980. Le PDF se tourne tout seul en portrait : ne changez pas
   l'orientation.
2. **Sécher** : laissez sécher l'encre, idéalement une nuit (encre à colorant).
3. **Encocher le laminé** : découpez `laminate_notches.dxf` dans la feuille
   de laminé (coupe simple, sans repères, placée à X 0 / Y 0) pour ouvrir les trois coins de
   22 × 22 mm. Posez le laminé encoches sur les
   trois repères, puis laminez.
4. **Studio**, page **Paysage** (Landscape) : **Fichier** (File) → **Ouvrir…** (Open…) le modèle de la mise en
   page (`<layout_id>.studio3`). **Repères d'impression** (Registration Marks) : **Type 1**, **Longueur** (Length)
   10 mm, **Épaisseur** (Thickness) 1 mm,
   **Retrait** (Inset) 10 mm. Posez la feuille sur le tapis en paysage,
   comme les cartes : le carré noir en haut à gauche.
5. **Découper** : **Envoyer** (Send), le **Matériau** (Material) ⚠ `Chels – vinyle + lam. mat` (réglages et
   **Test de découpe** (Test Cut) : `docs/cut-settings.md`). Découpe à mi-chair : laminé et vinyle, pas le support.
6. **Couper** la feuille aux traits de coupe en trois tiers (haut / milieu / bas), puis rangez
   chaque tiers selon le bordereau (`packing_slip`) : rien n'est imprimé sur la feuille à part les
   étiquettes, les repères et les traits de coupe ; le bordereau et l'aperçu de chaque feuille disent
   quelle commande va dans chaque tiers (numéro de feuille = ordre des pages, puis haut / milieu / bas).
   Chaque tiers part à plat dans une enveloppe n° 10.
<!-- /generated:print-and-cut -->
