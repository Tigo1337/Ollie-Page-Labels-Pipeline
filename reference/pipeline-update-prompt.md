# Claude Code prompt: thirds, bigger bundles, one finish, fixed name position, Mazie Page Creations brand and new listing images

Attach these 5 files, then paste everything below the line:
- `thirds_preview.png`
- `mazie-page-brand.zip`
- `fixed-name.patch`
- `listing_images.py`
- `listing-reference-images.zip`

---

## What this update does

This repo is my label pipeline (FastAPI + React on Replit, engine in `engine/`). It goes through six changes:

1. **Thirds.** Each US Letter sheet is trimmed into **three equal thirds** instead of two halves, so every piece ships flat in a **#10 envelope**.
2. **Bigger bundles.** New quantities, sized to the thirds.
3. **One finish.** Buyers no longer choose matte, glossy or holographic. Every label gets the same matte laminate.
4. **Fixed name position.** On the strip sizes, the name sits in the same place on every design, and the art slides left behind it.
5. **Brand.** The shop is now **Mazie Page Creations**, with its logo, icons, four colours and two fonts.
6. **New Etsy listing images.** Seven images in the new brand replace the current ones.

**Read the whole repo before you start.** "Half" is built into:
- `config/sheet.json`
- `engine/layout.py`, `packing.py`, `production.py`, `sheetpdf.py`, `gallery.py`, `templates.py`, `listing_images.py`, `listings.py`, `orders.py`, `art.py`
- `app/api.py`, `app/migrate.py`, `app/repo.py`, `app/listings_service.py`
- the Jinja templates in `config/templates/`
- the frontend pages
- the tests

The attachments:

| File | What it is |
|---|---|
| `thirds_preview.png` | The expected third-sheet layouts for all 7 sizes. |
| `mazie-page-brand.zip` | The brand files. Unzip its folder's contents into a new `brand/` folder at the repo root (`brand/mazie-page-logo-horizontal_2400.png`, `brand/icons/…`), and keep `build_logo.py` and the `README.txt` there. |
| `fixed-name.patch` | The fixed name position, as a working patch to `engine/art.py`. It applies cleanly to the current `main`. |
| `listing_images.py` | A working drop-in replacement for `engine/listing_images.py` that makes the 7 new listing images. I ran it against this repo, with the new bundles and the patch applied. |
| `listing-reference-images.zip` | What `listing_images.py` produced for the `dinosaurs-fantasy` group. Your output must match these. |

## Part A: thirds (sheet geometry, layouts, templates, PDF)

Everything about the sheet stays the same, except the trim:
- Studio frame, `/Rotate 270`
- Type 1 marks (inset 10, length 10, thickness 1)
- keep-outs 21.5 / 23.5 mm, laminate notch 22 mm
- edge margin 10 mm, gap 2.5 mm (2.0 mm between round labels), bleed 1.25 mm
- 5 mm clear on each side of every trim line

**A1. `config/sheet.json`**

Replace `"trim": {"x": 139.7, ...}` with:

```json
"trim": {"pieces": 3, "margin_each_side": 5.0, "ticks_mm": 6.0, "dashed_guide": true}
```

- Trim positions are computed, never typed in: Studio X = `paper_w × i / pieces` for i = 1 … pieces − 1, which gives **X = 93.133 and 186.267**. On the printed sheet these are y = 93.133 and 186.267.
- Replace `Sheet.trim_x` with `Sheet.pieces` and a `trims` property, the list of trim X values.
- Keep the code general for any `pieces` value of 2 or more. `pieces: 2` must still give exactly today's half layouts; add a test for that.

**A2. Layouts: three identical pieces.** A **piece** (French: *tiers*) replaces a half everywhere.

- **Top piece:** optimize only the printed top piece, exactly as the top half is optimized today. Its box runs from the 10 mm edge margin to the first trim line minus 5 mm, and only the top two corners are keep-outs. Generalise `_TopHalf` into `_TopPiece`.
- **Middle piece:** every top cell **translated** down by one piece height (printed y + 93.133).
- **Bottom piece:** every top cell **mirrored** about the page centre (printed y′ = 279.4 − y − h).
- With `pieces: 2` this is today's rule: top plus the mirrored bottom.
- **All pieces hold the same arrangement and count.** The middle piece could hold a few more labels; don't add them.
- **File format:** replace `top` / `bottom` with `"pieces": [[…], […], […]]` in printed order, and add `per_piece`. Keep `per_sheet`. Update `Layout.from_dict` so it still reads the v1 files (`top` / `bottom`) as two pieces.
- **Versions:** the geometry hash changes, so `python -m engine layouts` writes `chels-<size>-v2.json` for every size. Never edit the v1 files.
- **Counts:** I got these by running this repo's own optimizer on the top third. A test must assert them as the minimum:

| size | per third | per sheet | arrangement (top third) |
|---|---|---|---|
| pencil | 17 | 51 | normal, rows 2 + 3 + 3 + 3 + 3 + 3 |
| small | 19 | 57 | normal, rows 3 + 4 + 4 + 4 + 4 |
| medium | 8 | 24 | normal, rows 2 + 3 + 3 |
| large | 6 | 18 | rotated, one row of 6 |
| tag | 34 | 102 | normal, rows 6 + 7 + 7 + 7 + 7 |
| round | 10 | 30 | normal, 2 rows of 5 (gap 2.0) |
| shoe | 4 pairs | 12 pairs | rotated, one row of 4 pairs |

- **`check_layout`** checks:
  - every piece has the same count
  - the middle piece is the top translated, and the bottom is the top mirrored (±0.01 mm)
  - no cut line within 5 mm of **any** trim line, and no bleed crossing one
  - every cell lies inside its own piece
  - plus the existing corner, edge and gap rules

**A3. Templates, PDF and proofs**
- **Templates:** rebuild every template from the v2 layouts (`templates/chels-*-v2.*`). The Templates page must show the v1 `.studio3` uploads as outdated; the geometry hash already does this.
- **Print PDF:**
  - trim ticks and a dashed guide at **both** trim lines
  - the 6 pt gutter text for **every** piece, beside its own trim line (the middle piece's text goes along its upper trim line)
  - the header stays where it is
- **Trim-line cut file:** both lines, on layer `TRIM`.
- **Gallery and page proofs:** three pieces, with a bonus piece tinted and the order text on each piece.

**Stop here.** Show me the counts table and the v2 gallery PNGs.

## Part B: batching, bundles, one finish, migration

**B1. Batching: three pieces per sheet**
- A pack expands into **pieces**, one size each. Each piece carries its order, line, name, design and font.
- A sheet is **three pieces** with the same layout. Fill sheets oldest first; the pieces can come from different orders.
- When a sheet is left with only 1 or 2 pieces:
  - "bonus" (the default) fills the empty pieces with free copies of the last real piece
  - "blank" leaves them empty
  - "wait" keeps the pieces waiting for more orders
- Renames:
  - `Half` → `Piece`
  - `SheetPlan.top/bottom` → `SheetPlan.pieces`
  - `HalfSheetBatcher` → `PieceBatcher`
- The piece tag reads `#<order> · <name> · tiers i/n`.
- **Packing slip:** for each order, its pieces with the sheet number and the position **haut / milieu / bas** (top / middle / bottom).
- **Pack math:** every quantity must be a whole number of pieces (`pack_pieces`). Sheets of material are counted two ways:
  - batched: pieces / 3
  - printed alone: Σ ceil(pieces of a size / 3)

**B2. Bundles: `config/packs.json`**

| id | label | contents | pieces |
|---|---|---|---|
| pencil51 | 51 Skinny pencil labels | pencil 51 | 3 |
| small57 | 57 Small labels | small 57 | 3 |
| medium24 | 24 Medium labels | medium 24 | 3 |
| large18 | 18 Large labels | large 18 | 3 |
| tag102 | 102 Clothing tag labels | tag 102 | 3 |
| round30 | 30 Round labels | round 30 | 3 |
| shoe12 | 12 pairs of shoe labels | shoe 12 | 3 |
| starter | Starter pack (73) | pencil 17, small 38, medium 8, round 10 | 5 |
| daycare | Daycare pack (113 + 4 shoe pairs) | tag 68, medium 16, small 19, round 10, shoe 4 | 7 |
| school | Back-to-school pack (208 + 8 shoe pairs) | pencil 51, small 57, medium 16, large 6, round 10, tag 68, shoe 8 | 14 |

In `config/listings.json`, change:
- `pack_short`: `51 Skinny`, `57 Small`, `24 Medium`, `18 Large`, `102 Clothing Tags`, `30 Round`, `12 Shoe Pairs`, `Starter (73)`, `Daycare (121)`, `Back to School`
- `pack_code`: `PEN51`, `SML57`, `MED24`, `LRG18`, `TAG102`, `RND30`, `SHOE12`, `START`, `DAYC`, `SCHL`
- `prices`: the new ids, left empty
- `shop_name`: `"Mazie Page Creations"`
- add `"ship_time": "[X] business days"`, editable on the Listings page and used by the How-to-order image

Remove any text that says "half sheets" or "letter envelope". Pieces now ship in a #10 envelope.

**B3. One finish only**
- `config/finishes.json`: a single finish, `{"id": "matte", "label": "Matte laminate", "media": "white inkjet printable vinyl", "laminate": "matte clear overlaminate", "notch": true, ...}`.
- The laminate notch stays.
- Remove the finish choice from the Settings page and the Make page. The Make page shows "Matte laminate" as plain text.
- **SKUs:**
  - `parse_sku` accepts the new `<design>-<pack>` (finish = matte) as well as the old `<design>-<pack>-<finish>`.
  - An old gloss or holographic SKU still parses, but the order is produced in matte, with a warning on the run.
- **History:** runs already stored keep their finish text as it is.
- **Docs:** `docs/cut-settings.md` and `cut_settings.md.j2` describe one custom material (vinyl + matte laminate). Remove the holographic notes.

**B4. Packs report: envelope weight.** `python -m engine packs` and the Make page show, for each pack:
- the pieces per size
- the sheets when batched and when printed alone
- an envelope estimate: pieces × `piece_weight_g` (setting, default 6 g, which I'll replace after weighing a real third) + `envelope_weight_g` (default 5 g)
- the Canada Post Lettermail class: up to 30 g, up to 50 g, or over 50 g (oversized)

Also warn above 12 pieces: standard Lettermail is limited to 5 mm thick (`piece_thickness_mm` setting, default 0.35).

**B5. Migration: `geometry_version` 3.** On startup, a database below 3:
1. Backs up the database, exactly as v2 does.
2. Replaces the `sizes`, `packs` and `finishes` settings with `config/*.json`, and sets the shop's finish to `matte`.
3. Updates the stored Listings settings:
   - new pack ids in `pack_short`, `pack_code` and `prices` (keep any price whose pack id still exists)
   - `shop_name` set to "Mazie Page Creations" if it is empty
   - `ship_time` added
4. **Archives** (never deletes) every saved crop preset for `pencil`, `small`, `medium` and `large`, using the existing archive table, with the note "fixed name position (geometry v3)". Part C explains why. Presets for `tag`, `round` and `shoe` stay.
5. Records the change log.

Runs and files made before v3 stay downloadable as they are.

**Stop here.** Run `python -m engine pack-samples` and show me the `school` and `starter` output and their page proofs.

## Part C: fixed name position (strip sizes)

Today the name box starts wherever each design's character ends (`char_end`), so the name moves from design to design. From now on, **the name box starts at the same spot on every design**, and the art slides left so the character ends just before it. A wide character gets its left side cut off, which is fine.

1. Apply `fixed-name.patch` to `engine/art.py`.
2. Move its `NAME_START` constants into `config/sizes.json` as a `name_start` field on `pencil` (0.24), `small` (0.36), `medium` (0.36) and `large` (0.42), and keep `NAME_GAP_MM` = 0.8.
   - `name_start` is not cut geometry, so it must **not** change the layout geometry hash.
   - Sizes without `name_start` keep today's behaviour: tag (no character), and round and shoe (square art, `square_text`).
3. **Crop editor**, for sizes with `name_start`:
   - The name box is locked to the fixed box and shown but not draggable.
   - I can still slide and zoom the art behind it, saved as the preset's `center` and `height`.
   - A saved preset's `text` is ignored for these sizes; the fixed box always wins.
   - Add a "Reset to automatic" button.
4. **Tests:**
   - For every design, the medium (and large, small, skinny) name box has the same x0 and x1 (±0.01).
   - The crop never runs past either end of the strip.
   - The review sheet still shows names at or above the minimum cap height, or flags them as today.

**Stop here.** Show me the review sheet (`python -m engine review`) for `dino`, `narwhal`, `tractor` and `camping`.

## Part D: Mazie Page Creations brand and the new listing images

**D1. Brand**
- **Files:** the brand files live in `brand/` (from `mazie-page-brand.zip`). The SVGs are the masters, with text as outlines; the PNGs are the exports. `build_logo.py` rebuilds them from Fredoka.
- **Colours:** Plum `#3E2352`, Lilac `#C9B5F0`, Blush `#F5BFD0`, Pearl `#FBF7FB`. A deeper Blush tone (`#EFA3BF`) appears only in the logo's heart and cheeks. Text is always Plum, or Pearl on Plum.
- **Fonts:** Fredoka SemiBold (font 1) for titles and Nunito (font 3) for text, both already in the pipeline.
- **The app:**
  - page title "Mazie Page Creations · Label pipeline"
  - the favicon from `brand/mazie-page-icon_32.png`
  - the horizontal logo in the header
  - accent colours from the palette, keeping text contrast at 4.5:1 or more
- **Customer proof** (the image buyers see), `engine/proofs.py`:
  - Pearl background, Plum text, Fredoka titles
  - the horizontal logo at the top
  - no other colours

**D2. Listing images**
1. Replace `engine/listing_images.py` with the attached `listing_images.py`.
2. In `engine/listings.py`, replace `IMAGE_VARIANTS` with this list (gallery order):

```python
IMAGE_VARIANTS = [
    ("Hero", False, "{group_name} kids name labels on a sheet — personalized waterproof name stickers by {shop_name}"),
    ("Designs", False, "The {design_count} {group_name} label designs, numbered — choose your design"),
    ("Bundles", False, "Bundle options for the {group_name} name labels — label counts per bundle"),
    ("Sizes", False, "{group_name} name label sizes at the same scale — large, medium, small, skinny, clothing tag, "
                     "round and shoe pair"),
    ("Fonts", True, "The {font_count} numbered fonts for the kids name labels — choose your font"),
    ("Durable", False, "Close-up of laminated {group_name} name labels — waterproof, peel and stick, made in Québec"),
    ("HowToOrder", False, "How to order the {group_name} name labels in three steps"),
]
```

3. Remove the old variants (`Closeup_Small`, `Closeup_Round`) from the Listings page, the CSV and the R2 upload. The CSV's image columns follow `IMAGE_VARIANTS`, so the listings get 7 images.
4. **How the module works.** Keep these rules if you change it:
   - Every image is laid out on a 1200 × 1200 grid and drawn at 2× (2400 × 2400).
   - It uses only flat fills, rounded rectangles with a 4 px Plum outline and an 8 px Plum ledge, circles, the two fonts, and pasted PNGs (logo, icons, label renders, sheet close-ups). No gradients, blurs or blend modes.
   - The hero keeps its important content between y 150 and 1050, which Etsy keeps in its 4:3 search thumbnails.
   - "Choose your design" shows up to 10 designs in 2 × 5 tiles. For more designs the rows get shorter. The design name shrinks to fit 2 lines.
   - The bundle cards and pills come from `packs.json`: bundles with more than one size are cards, single sizes are pills. The bundle with the most labels is marked "Most complete".
   - The sizes image has no ruler, on purpose: it can't be accurate on screens.
   - The label renders come from the normal renderer, so they show the fixed name position.
5. Match `listing-reference-images.zip`. Run `python -m engine listings --group dinosaurs-fantasy` and compare your 7 PNGs with mine by eye; they should look the same.
6. **Tests:**
   - Every group's 7 images are 2400 × 2400.
   - Groups of 1, 6, 10 and 16 designs render without errors and without text running out of its card. Check text widths against the boxes in code.
   - The alt texts and asset names follow `IMAGE_VARIANTS`.

**Stop here.** Show me the 7 images for `dinosaurs-fantasy` and one other group.

## Part E: docs and tests

- **Update:**
  - `README.md`: thirds, the counts table, #10 envelope, one finish, the brand
  - `reference/sheet-layout-plan.md`
  - `docs/studio-template-setup.md`: rebuild the 7 templates for v2
  - `info_sheet.txt.j2` step 6: "Couper la feuille aux traits de coupe en trois tiers (haut / milieu / bas)"
  - `cut_settings.md.j2`: two trim lines, one material
- **Tests:**
  - the counts and piece rules
  - `pieces: 2` reproduces the v1 layouts
  - the template match test for v2
  - batching:
    - three `starter` orders fill only full sheets (pencil 1, small 2, medium 1, round 1), with no bonus pieces
    - one `school` order printed alone gives 7 sheets, with bonus copies in the empty pieces
  - every pack produces a print PDF plus its SVG and DXF
  - migration to v3, including the archived presets and the updated Listings settings
  - SKU parsing, old and new
  - the fixed name box
  - the listing images
- `python -m pytest` and `cd frontend && npm run build` must both pass.

## Do not

- Don't change the label sizes, the marks, the keep-outs, the gap or the bleed.
- Don't let the pieces of one sheet differ in arrangement or count, and don't mix sizes on a sheet.
- Don't edit or delete the v1 layout files, the stored `.studio3` uploads, or any saved preset (archive them).
- Don't use colours outside the brand palette in anything a buyer sees: listing images, customer proofs.
- Keep Replit's run setup as it is: `scripts/start.sh`, packages through Replit's package manager, no pip against system Python.
