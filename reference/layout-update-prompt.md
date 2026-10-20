# Claude Code prompt: switch the app to the fixed half-sheet layouts, new packs and matching cut templates

Attach the 7 files that come with this prompt, then paste everything below the line.

---

## Context

**First step:** save the attached files into the repo. Put `Starter_15-22_portrait.pdf` in `tests/fixtures/`, and the other 6 (`sheet-layout-plan.md`, `label-pipeline-prompt.md`, `label-shop-code.zip`, `sheet_opt.py`, `test_sheets_pdf.py`, `label-layout-test-sheets.pdf`) in `reference/`.

This repo is my label pipeline: a FastAPI + React app on Replit, with the pure-Python engine in `engine/`. I sell custom kids' name labels on Etsy. I print on an **Epson ET-2980** onto white printable vinyl, laminate, and kiss-cut on a **Silhouette Cameo 5** with print-and-cut registration marks. After cutting, I trim each Letter sheet into **two halves** that ship flat in a letter envelope.

The engine still uses my **old** geometry, and it must be replaced:

| Area | Now in the repo | Target |
|---|---|---|
| Page | portrait PDF; filled square top-left, L top-right, L bottom-left | SCM-style landscape page with `/Rotate 270` (square prints bottom-left) |
| Marks | 20 mm L arms, 36 mm keep-outs, 34 mm notch | 10 mm arms, 21.5 mm ink / 23.5 mm cut keep-outs, 22 mm notch |
| Margins / gap | 12 mm margin, 3 mm gap | 10 mm edge margin, 2.5 mm gap (2.0 mm between round labels) |
| Packing | `TidyRowPacker` mixes sizes on a sheet and lays out every order differently | **fixed layouts per size**, two identical halves per sheet |
| Cut files | a new DXF/SVG for every page, with an X/Y to type in | **one template per layout**, reused for every order |
| Sizes | mini, small, medium, large, round 30, square | pencil, small, medium, large, tag, round 32, shoe pair |
| Packs | mini60 … school (132) | the new pack table below |

The full geometry spec is `reference/sheet-layout-plan.md`. Treat it as **authoritative** for marks, orientation, keep-outs, the trim line, the layout algorithm and the counts. This prompt adds what that spec doesn't cover:
- how to fit it into **this** codebase
- the new packs
- the cut-template deliverables

`reference/sheet_opt.py` is my working prototype of the optimizer. It produces exactly the counts below. `reference/test_sheets_pdf.py` and `reference/label-layout-test-sheets.pdf` are a working prototype of the SCM-style PDF with marks; I have test-printed them. Port from these. Don't reinvent them.

Silhouette Studio runs in **French** on my PC. Every instruction you write for me must use the French interface labels, with the English label in brackets after each one. Keep every Studio label in one dictionary (like the one at the top of `config/templates/info_sheet.txt.j2`), and mark the ones you are not sure of so I can confirm them.

## Target numbers

The geometry is in the Studio frame (landscape, 279.4 × 215.9 mm). Put these values in `config/sheet.json`, which replaces the geometry parts of `production.json`:

- **Registration:** Type 1, 3 marks, inset 10, length 10, thickness 1 (marks drawn like SCM's `generate_reg_mark`; see the spec)
- **Corner keep-outs:** ink 21.5 mm, cut 23.5 mm, on all 4 corners
- **Laminate notch:** 22 mm, used for **every** finish, matte included
- **Edge margin:** 10 mm
- **Trim line:** Studio X = 139.7, 5 mm clear each side
- **Gap:** 2.5 mm between cut lines, or **2.0 mm for round** (store it per size as `"gap"` in `sizes.json`)
- **Bleed:** 1.25 mm
- **Resolution:** 600 dpi

Sizes (cut size in mm):

| id | size | per half | per sheet | arrangement |
|---|---|---|---|---|
| pencil | 57 × 9.5, r 3 | 30 | 60 | rotated, rows 14 + 16 |
| small | 44.5 × 12.7, r 3 | 31 | 62 | rows 3 + 7 × 4 |
| medium | 63.5 × 19, r 4 | 15 | 30 | 5 rows × 3 |
| large | 63.5 × 25.4, r 5 | 11 | 22 | rows 2 + 3 + 3 + 3 |
| tag | 25.4 × 12.7, r 2 | 55 | 110 | rows 6 + 7 × 7 |
| round | 32 Ø | 20 | 40 | staggered, 4 rows of 5, gap 2.0 |
| shoe | pair: 2 × (30 × 38), 2.5 apart, r 4 | 8 pairs | 16 pairs | rows 2 + 3 + 3 pairs |

**Round.** The top row (printed view) is centred between the two mark corners. Each following row is shifted about 14.2 mm toward the left edge, and the row pitch is about 30.9 mm. For circles, check the corner keep-outs against the **real circle** (centre distance to the keep-out square minus the radius, plus bleed for the ink zone), not its bounding box. With a bounding-box check, 20 doesn't fit.

**Packs.** Every pack is a whole number of single-size halves:

| id | label | contents | halves |
|---|---|---|---|
| pencil60 | 60 Skinny pencil labels | pencil 60 | 2 |
| small62 | 62 Small labels | small 62 | 2 |
| medium30 | 30 Medium labels | medium 30 | 2 |
| large22 | 22 Large labels | large 22 | 2 |
| tag110 | 110 Clothing tag labels | tag 110 | 2 |
| round40 | 40 Round labels | round 40 | 2 |
| shoe8 | 8 pairs of shoe labels | shoe 8 pairs | 1 |
| starter | Starter pack (61) | pencil 30, small 31 | 2 |
| daycare | Daycare pack (86) | small 31, tag 55 | 2 |
| school | Back-to-school pack (96 + 8 shoe pairs) | pencil 30, small 31, medium 15, round 20, shoe 8 pairs | 5 |

`reference/label-shop-code.zip` has the same values in `labelshop/config/sizes.json` and `packs.json`. They are keyed objects, while this repo uses lists, so convert them.

## Phase 1: layouts (engine only)

1. Add `config/sheet.json` and the new `sizes.json` and `packs.json`. Extend `Size` with:
   - `shape: "pair"` with `pair: {each_w, gap}`
   - an optional per-size `gap`
2. Add `engine/frames.py` with `to_studio()` and its inverse, as the spec describes. This is the **only** place frames are converted.
3. Add `engine/layout.py`, a port of `reference/sheet_opt.py`:
   - Optimize the printed top half only.
   - Mirror the bottom half about the trim line.
   - Write `layouts/chels-<size>-v1.json`. Each file holds:
     - `layout_id` and `size`
     - a `geometry_hash` of `sheet.json` plus that size's entry
     - the `top` and `bottom` cells as `[X, Y, W, H, rotated]` in the Studio frame
   - Commit the files.
   - Never edit a published layout. If the geometry changes, write `-v2`.
4. Add `python -m engine layouts` (rebuild and print the counts table) and `python -m engine layout-gallery --out <dir>` (one PNG per layout, printed view, with keep-outs hatched, notch outlines, the trim line and the counts).
5. Tests for this phase:
   - the counts per half match or beat the table
   - the bottom half mirrors the top half (±0.01 mm)
   - no bleed in an ink zone, no cut in a cut zone, nothing in the trim gutter or past the edge margin (check with 3-mark and 4-mark registration)
   - gaps respected (circles: centre distance ≥ diameter + 2.0)
   - the geometry-hash check fails if `sheet.json` changes without a version bump

**Stop.** Show me the counts table and the gallery PNGs.

## Phase 2: one cut template per layout, matching the PDF exactly

Because every order of a size uses the same cells, the cut file belongs to the **layout**, not the order. There are 7 layouts, so 7 templates are made once and reused for every bundle.

For each layout, generate into `templates/`:

1. **`<layout_id>.svg`: the main cut file.**
   - `width="279.4mm" height="215.9mm" viewBox="0 0 279.4 215.9"`, in the Studio frame, y down (no flip needed).
   - Write true shapes, not polylines: `<circle>` for round, `<rect rx ry>` for rounded rectangles, one `<path>` per shoe label. Studio keeps them as smooth curves.
   - Stroke only (0.1 mm red hairline), no fill, no transforms, no groups other than one `<g id="cut">`. Every number is in mm with up to 3 decimals.
   - Add two 0.01 mm anchor dots in `<g id="anchors">`, at (0, 0) and (279.4, 215.9). When I select everything and place it at X 0 / Y 0 in Transformer, every cut lands exactly where the PDF printed its label. I then delete the anchors.
   - Add an SVG round-trip test: parse it back and check every shape against the layout file within 0.01 mm.
2. **`<layout_id>.dxf`: a fallback** for Silhouette Studio Basic Edition, which can't open SVG (SVG import needs Designer Edition or higher).
   - R12 format, millimetres, Studio frame, y flipped.
   - Closed `POLYLINE` entities only (arcs flattened to ≤ 0.1 mm chord error), on layer `CUT`, with the same anchors on layer `ANCHOR`.
   - Reuse and extend `engine/cutfiles.py`.
3. **`<layout_id>.json`**
   - The cut group's bounding box (X, Y, W, H in mm, anchors excluded), for positioning by hand in Transformer.
4. **`<layout_id>_calibration.pdf`**
   - Marks plus every cell's cut outline as a 0.2 mm grey hairline, no art.
   - I cut it on plain paper with the template. If every cut lands on its hairline, the template is right.
5. **`.studio3` (optional, saved by me)**
   - Do **not** try to write `.studio3` files. The format is proprietary and undocumented, and a guessed file could cut in the wrong place.
   - Instead, add a **Templates page** to the app (`/templates`) that lists the 7 layouts. For each one it shows:
     - the gallery preview
     - downloads for the DXF, SVG, JSON and calibration PDF
     - an upload slot for my finished `<layout_id>.studio3`
   - Store each upload in blob storage, together with the layout's `geometry_hash` at upload time.
   - If a layout's hash ever changes, mark its `.studio3` as **outdated** in red and stop including it in bundles.
   - Write `docs/studio-template-setup.md` in French. These are the steps I follow once per layout:
     - Fichier → Nouveau
     - page settings: Lettre, Paysage
     - Fichier → Ouvrir (or Fusionner) the SVG
     - select all, Grouper, then Transformer: X 0, Y 0 (thanks to the anchors), and check that L/H are 279.4 × 215.9
     - check the cut group's X/Y/L/H against the JSON after deleting the anchors
     - registration marks: Type 1, Longueur 10, Épaisseur 1, Retrait 10
     - Enregistrer sous `<layout_id>.studio3`
     - cut the calibration PDF
     - upload the file to the app
   - Mention SCM's `dxf_to_studio3.py` (Windows GUI automation) as an optional shortcut, with `--no_center`. Link to it; don't vendor it.

**"Matches perfectly" is a test, not a hope.** Add `tests/test_template_match.py`. For every layout:
- Render a print-PDF page and rasterize it at 600 dpi in the Studio frame, undoing `/Rotate 270`.
- Parse the layout SVG and the layout DXF.
- Check that every cut path falls inside its own label's bleed band (reuse the approach in `tests/test_alignment.py`).
- Check that the cell count in the SVG and in the DXF equals the layout's.
- Check that the marks rasterize where SCM's fixture has them, within 0.2 mm. The arm length is the only allowed difference.

Also check that the PDF page and the DXF both come from the same `layouts/*.json` file, and that the SVG and DXF bounding boxes equal the JSON one within 0.01 mm.

**Stop.** I'll build one template, cut the calibration sheet and tell you the result.

## Phase 3: print PDFs and bundles

1. Replace `TidyRowPacker` and `CompactRowPacker` in production with **half-sheet batching**. Keep the `PackingStrategy` seam, but the new default works like this:
   - An order line's pack expands into **halves**, one per size in the pack. Each half has an order, line, size, design, name, font and finish.
   - A **sheet** is two halves with the same `layout_id` and the same finish. Pair halves oldest first; the halves can come from different orders.
   - A half left without a partner is listed as waiting. "Imprimer seul" prints it now and fills the other half with a **bonus copy** of the same order; a toggle prints that half blank instead.
   - Delete the old strategies once nothing uses them.
2. **Print PDF**, one per batch × finish × layout:
   - landscape 792 × 612 pt with `/Rotate 270`
   - `/ViewerPreferences /PrintScaling /None`
   - art at 600 dpi in the layout's cells, no scaling
   - marks
   - trim ticks and a light dashed trim guide
   - 6 pt grey order text in the gutter: `#<order> · <name> · <finish> · <half i/n>`
   - a header line `sheet: N · template: <layout_id>`, outside the keep-outs

   Round labels get a circular bleed mask. The PDF must never place anything the template doesn't cut.
3. **Each run's ZIP (the bundle)** contains:
   - the print PDF(s)
   - for every layout used:
     - `templates/<layout_id>.svg` and `templates/<layout_id>.dxf`, always
     - `templates/<layout_id>.studio3` too, if I've uploaded one and it is current (with the cut settings already saved in it, it is the quickest to use)
   - the laminate notch DXF
   - the page proofs
   - the customer proof(s)
   - the info sheet
   - a **packing slip**: per order, its halves, the sheet number and the position (haut/bas), so I can collect the right pieces after trimming

   The info sheet table lists each PDF page with its `layout_id` and which template file to open. There is no more per-page X/Y to type, because the template is already positioned.
4. **Every pack must produce a working bundle.** Add `python -m engine pack-samples --out <dir>`. For every pack × finish, it makes a sample order with demo art and writes the bundle.

   Add a test that, for every pack:
   - the run produces at least one print PDF
   - every page's `layout_id` has its SVG and DXF in the bundle
   - the labels per size equal the pack's contents
   - no half mixes sizes or finishes
   - two `starter` orders give exactly one pencil sheet and one small sheet
5. Rewrite `config/templates/info_sheet.txt.j2` for the new workflow:
   - Paysage, not portrait
   - mark length 10
   - open the layout's `.studio3` if there is one, otherwise the SVG (steps from `docs/studio-template-setup.md`)
   - notch the laminate for every finish
   - print at 100 %

   Rewrite `engine/calibration.py` around the per-layout calibration PDF.

**Stop.** Send me the `pack-samples` output for `school` and `starter` (matte), and the page proofs.

## Phase 4: rendering the new sizes, and data migration

1. **Rendering.** `reference/label-pipeline-prompt.md` section 6 describes these:
   - **tag** has no character: crop the strip from `mini_start` (per design, default 0.24), and the name fills the label.
   - **shoe** is one crop over the whole pair cell from the square art, split into left and right labels with a small "G" / "D" in each safe area.
   - **round** and **shoe** use the square art.

   Update `engine/art.py` and `engine/render.py`, the crop editor (show the pair split line), and `review_sheet`.
2. **Database migration.** Sizes, packs and production values are seeded into the DB only once (`Repo.seed`), so an existing database keeps the old geometry. Add a `geometry_version` setting and a startup migration that:
   - replaces the `production`, `sizes` and `packs` settings with the new ones
   - keeps presets for small, medium, large and round, flagged "à revoir"
   - archives presets for the removed sizes (mini, square) instead of deleting them

   Back up the database first, and log what changed.
3. **Designs.** Make sure all 100 designs from `reference/label-shop-code.zip` (`config/themes.json`) exist with:
   - name, fill, stroke and `stroke_ratio`
   - `char_end`
   - `mini_start`, `square_text` and `no_character_sizes`

   Import the 7 `themes/<id>/crops.json` presets. The existing ZIP import already matches art by folder name, so I'll upload the art myself.
4. **Frontend.** On the Make page:
   - show the halves and sheets for each pack
   - change the `"mini"` warning to `"pencil"`
   - add links to the Templates page and the layout gallery

## Phase 5: tests green and docs

- `python -m pytest` and `cd frontend && npm run build` both pass.
- Update `README.md`:
  - "Production numbers"
  - the layout section
  - a new section "Imprimer et découper une planche", in French with English in brackets
- Add `docs/cut-settings.md` with starting kiss-cut settings: AutoLame Profondeur 2, Force 12, Vitesse 4, Passages 1. Each finish gets a Test de découpe first.

## Do not

- Don't hand-place labels per order. Orders only fill a layout's cells.
- Don't mix sizes, orientations or finishes on a sheet, and never let the bottom half differ from the top half.
- Don't draw anything inside a corner keep-out.
- Don't edit a published layout in place. Don't change pack quantities or prices.
- Don't try to write `.studio3` files; the SVG is the cut file the app generates.
- Keep Replit's run setup as it is (`scripts/start.sh`, packages through Replit's package manager, no pip against system Python).
