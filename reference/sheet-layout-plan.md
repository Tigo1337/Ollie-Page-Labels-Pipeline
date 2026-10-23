# Claude Code prompt: max-density US Letter label sheets with Cameo 5 marks and envelope thirds

> **Updated for the thirds** (`reference/pipeline-update-prompt.md`, layouts `-v2`, geometry v3).
> This spec first described half-sheets; it now describes what the engine does:
> - each sheet is trimmed into **three equal thirds** (`trim.pieces: 3`), each shipped flat in a **#10 envelope**;
> - the trim lines are computed: Studio X = 279.4 × i / 3 = **93.133 and 186.267**;
> - only the printed top third is optimized; the **middle third is the top third translated** (printed y + 93.133)
>   and the **bottom third is the top third mirrored about the page centre** (printed y′ = 279.4 − y − h);
> - there is **one finish** (matte laminate), the bundles are sized to the thirds, and the print PDF holds only the
>   labels, the marks and the trim marks (no header, no order text).
> With `pieces: 2` the same optimizer gives exactly the half-sheet layouts below (`-v1`, kept, never edited).
> Sections that only describe the old half-sheets are marked *(half-sheets, v1)*.

Paste everything below the line into Claude Code, opened in the **label Pipeline App repository** (the FastAPI + React app built from `label-pipeline-prompt.md`). It replaces the current shelf-packing layout (`pack()` in the engine) with fixed, optimized layouts.

Attach or copy these files into the repo's `reference/` folder before you paste the prompt:
- `sheet_opt.py`: my prototype optimizer, which produced the counts below
- `test_sheets_pdf.py` and `label-layout-test-sheets.pdf`: a prototype SCM-style PDF with marks and cut outlines, verified to print like my proxies
- `Starter_15-22_portrait.pdf`: one of my SCM proxy PDFs, used as the orientation fixture

---

## Context

I sell custom kids' name labels on Etsy. I print them on an **Epson ET-2980** onto white inkjet printable vinyl, laminate them (matte cold overlaminate; there used to be gloss and holographic too), and kiss-cut them on a **Silhouette Cameo 5** using print-and-cut registration marks. After cutting, I trim each Letter sheet into **three thirds (215.9 × 93.133 mm)** so each piece ships flat in a **#10 envelope** (Canada Post Lettermail: up to 30 g / 50 g, 5 mm thick). *(Half-sheets, v1: two halves of 215.9 × 139.7 mm.)*

My card-proxy business already uses a proven print-and-cut workflow: **Alan-Cha/silhouette-card-maker (SCM, MIT licence)**. It works like this:
- The PDF has the registration marks drawn into it.
- A matching `.studio3` template holds the same marks plus the cut lines. It is set up once per layout and reused.
- I print the PDF from my PDF viewer at 100 %, open the template in Silhouette Studio, and send the cut.

The labels must work the same way.

Silhouette Studio is in **French** on my PC. Any instructions you write for me must use the French interface labels (for example ENVOYER, Découper, Fichier → Ouvrir, AutoLame, Profondeur, Force, Vitesse, Passages).

## Goal

1. One **fixed, maximum-density layout per label size**. Every order of that size uses the same cut grid, so each layout needs only **one Studio template**, made once. That is **7 templates in total**, one per size.
2. Each sheet is split into **three pieces (top, middle, bottom)**, with a trim gutter at each trim line. Each piece must be a self-contained, shippable piece.
3. **All pieces are identical.** The middle piece is the top piece moved down by one third, and the bottom piece is the top piece mirrored about the page centre, so after trimming the three pieces have exactly the same arrangement and count (the middle piece could hold a few more labels; it does not). This is a hard rule.
4. The marks and page orientation must be **exactly like my SCM card-proxy PDFs** (see "Orientation" below). I place every sheet on the mat in Silhouette's **landscape** orientation, the same way as my proxies.
5. Packing, the PDF, the DXF, proofs and the Studio template all derive from **one layout definition**, so they can never disagree.

## Orientation: copy my SCM proxy PDFs exactly

I measured my proxy PDF (`letter-standard-v6`).
- **The PDF page:** MediaBox `[0 0 792 612]` (landscape Letter). Page 1 (the fronts) has `/Rotate 270`. The page content is one 600 ppi raster, 6600 × 5100 px, with the marks drawn into it.
- **Unrotated, in Silhouette Studio's landscape view** (the "Studio frame"):
  - The page is 279.4 × 215.9 mm, origin top-left, y down.
  - Standard Type 1 marks: a **filled square at top-left** (bounding box 9.5–15.5 mm, a 5 mm square at inset 10 with a 1 mm stroke).
  - An **L at top-right**, with its corner at (269.4, 10).
  - An **L at bottom-left**, with its corner at (10, 205.9).
  - The bottom-right corner has no mark.
- **As the PDF opens and prints** (the "printed view": portrait, after `/Rotate 270`):
  - **Square at bottom-left.**
  - **L at top-left** (shaped ┌).
  - **L at bottom-right** (shaped ┘).
  - Top-right has no mark.

Rules:
1. **All geometry is defined in the Studio frame**: marks, cells, DXF, Studio template, keep-outs and laminate notch. Every PDF page is a landscape 792 × 612 pt page with **`/Rotate 270`**, like SCM. Labels are single-sided, so there is no back page.
2. The **printed view** is used only for human-facing wording (top, middle and bottom piece, as I hold the sheet) and for proofs. Map between the two frames with:
   - point: printed `(x, y)` ↔ Studio `(X, Y) = (279.4 − y, x)`
   - rect: printed `(x, y, w, h)` → Studio `(279.4 − y − h, x, h, w)`
   - Put this transform in one tested function, `to_studio()` and its inverse, and nowhere else.
3. The marks are drawn exactly as SCM's `page_manager.generate_reg_mark` draws them in **THREE-mark mode**. Port that function, credit SCM (MIT) in a comment, and follow **the code, not the SPECIFICATION.md wording**: the 5 × 5 mm filled square has its *corner* at (inset, inset), and the L arms run `length` mm inward from the corner point at `inset`. Use our `sheet.json` values for inset, length and thickness. SCM's v6 uses a length of 8.04 mm; ours is 10 mm, and the Studio template uses the same 10 mm.
4. In the Studio frame, **the trim lines are vertical at X = 93.133 and 186.267 mm**. The printed "top piece" is the Studio **right** third (X > 186.267), and the printed "bottom piece" is the Studio **left** third, which holds the square mark. *(Half-sheets, v1: one trim line at X = 139.7.)*
5. **Acceptance test**: rasterize page 1 of our PDF the same way as `Starter_15-22_portrait.pdf` (attached to this prompt; keep a copy in `tests/fixtures/`). The square and both L marks must be at the same positions as in SCM's PDF within 0.2 mm, except for the arm length (10 mm vs 8.04 mm). Also render both PDFs in the printed view and check that the square lands at bottom-left in both.

## Fixed geometry (single source of truth: `config/sheet.json`)

```json
{
  "paper": {"w": 279.4, "h": 215.9, "frame": "studio_landscape", "pdf_rotate": 270},
  "registration": {"style": "type1", "marks": 3, "inset": 10.0, "length": 10.0, "thickness": 1.0, "padding": 1.5},
  "corner_ink_keepout": 21.5,
  "corner_cut_keepout": 23.5,
  "laminate_notch": 22.0,
  "edge_margin": 10.0,
  "trim": {"pieces": 3, "margin_each_side": 5.0, "ticks_mm": 6.0, "dashed_guide": true},
  "gap": 2.5,
  "bleed": 1.25,
  "dpi": 600
}
```

What each value means:

- **`registration`**
  - Type 1, three marks, drawn as described in "Orientation" above.
  - Every mark value is a setting in `sheet.json`, and the Studio template must use the same values.
- **Corner keep-outs.** There are two square zones, each measured from the paper corner. A cell must satisfy both.
  - **`corner_ink_keepout` = 21.5 mm** (inset 10 + mark length 10 + SCM's 1.5 mm padding). No ink inside it: the bleed box must stay out. This is the same clearance SCM uses around the marks.
  - **`corner_cut_keepout` = 23.5 mm** (laminate notch 22 + 1.5 mm hand-alignment tolerance). No cut line inside it: the cut box must stay out, so every label is fully covered by laminate even if the laminate is laid 1.5 mm off.
  - It applies to **all four corners**, including the unmarked one (Studio bottom-right, printed top-right), because the bottom piece mirrors the top piece. As a result, the layouts also work unchanged with 4-mark registration (Cameo 5 Alpha style). Support `marks: 4` as an option.
- **`laminate_notch`**
  - The laminate sheet has 22 × 22 mm squares removed at the three mark corners (Studio top-left, top-right and bottom-left), so the laminate never covers a mark. Shiny gloss and holographic laminate break mark scanning.
  - Use it for every sheet (there is one finish, matte laminate, and the notch stays).
  - Keep a generator for `laminate_notches.dxf`: a Letter-size outline with the 3 notches, cut from the laminate sheet before it is applied.
- **`edge_margin`**: cut lines stay at least 10 mm from the outer paper edges, inside the mark rectangle, like SCM. Bleed may extend into that margin.
- **`trim`**
  - `pieces`: the sheet is trimmed into this many equal pieces. The trim lines are computed, never typed in: Studio X = 279.4 × i / pieces for i = 1 … pieces − 1, i.e. **93.133 and 186.267** for thirds (printed y = 93.133 and 186.267).
  - No cut line may come within 5 mm of any trim line, so each gutter is 10 mm wide, and no bleed crosses a trim line.
  - Print 6 mm black trim ticks at both side edges of every trim line, plus a light-grey dashed guide across each gutter.
  - The marks never touch a gutter.
- **`gap` / `bleed`**
  - Cut lines are 2.5 mm apart, and the art extends 1.25 mm past every cut line, so neighbouring bleeds meet but never overlap.
  - Round labels get a **circular** bleed mask, not a square one.

## Label sizes (`config/sizes.json`)

The sizes are the **standard Etsy kids' name-label sizes**: inch-based dimensions used by the top-selling Etsy label shops, cross-checked against Mabel's Labels, Name Bubbles, Colle à Moi, Stuck On You and others.

Thirds (layouts `-v2`, the counts a test asserts as the minimum):

| id | use | cut size (mm) | inches | corner r | arrangement (top third) | per third | per sheet |
|---|---|---|---|---|---|---|---|
| pencil | pencils, markers, crayons | 57 × 9.5 | 2.25 × 0.375 | 3 | normal, rows 2 + 3 + 3 + 3 + 3 + 3 | 17 | **51** |
| small | supplies, containers (most common Etsy size) | 44.5 × 12.7 | 1.75 × 0.5 | 3 | normal, rows 3 + 4 + 4 + 4 + 4 | 19 | **57** |
| medium | bottles, lunch boxes | 63.5 × 19 | 2.5 × 0.75 | 4 | normal, rows 2 + 3 + 3 | 8 | **24** |
| large | books, bins, lunch bags | 63.5 × 25.4 | 2.5 × 1 | 5 | rotated, one row of 6 | 6 | **18** |
| tag | clothing care-tag stickers | 25.4 × 12.7 | 1 × 0.5 | 2 | normal, rows 6 + 7 + 7 + 7 + 7 | 34 | **102** |
| round | bottle caps, toys, shoe dots | 32 Ø | 1.25 Ø | – | normal, 2 rows of 5, 2.0 mm gap | 10 | **30** |
| shoe | left/right pair, one design split across both | 2 × (30 × 38), 2.5 gap | – | 4 | rotated, one row of 4 pairs | 4 pairs | **12 pairs** |

*(Half-sheets, v1, still what `pieces: 2` gives:* pencil 30 / 60 rotated rows 14 + 16, small 31 / 62, medium 15 / 30, large 11 / 22, tag 55 / 110, round 20 / 40 staggered 4 rows of 5, shoe 8 / 16 pairs.*)*

Rows are listed from the mark-corner edge of the top piece inward (printed view: top row first).

The 63.5 mm width is deliberate. Three columns plus two gaps take 195.5 mm of the 195.9 mm usable width, so three columns fit. At 66 mm only two columns fit (on the v1 halves: 10 medium or 8 large per half instead of 15 or 10).

The shoe size uses `shape: "pair"`: one layout cell holds **two** cut labels side by side. The design's crop is split down the middle, so the two labels form one picture when the shoes sit side by side, and each label shows a small "G" or "D" (gauche/droite) marker in its safe area.

## Layout optimizer (`engine/layout.py`)

You may optimize in the printed view (it is easier to reason about), then convert with `to_studio()`.

Optimize **only the printed top piece** (from the 10 mm edge margin to the first trim line minus 5 mm; corner keep-outs at printed top-left and top-right). Every other piece repeats it: a **middle piece** is every top cell **translated** down by one piece height (printed `y + 93.133`), and the **bottom piece** is every top cell **mirrored about the page centre** (printed `y_bottom = 279.4 − y_top − cell_h`, x unchanged; in the Studio frame a mirror about X = 139.7). With two pieces this is the half-sheet rule. Never optimize another piece on its own.

Candidates to try for the top piece:
1. A normal grid (label horizontal).
2. A rotated grid (label turned 90°), for non-square sizes.
3. For `round` only, a **staggered** grid: 4 rows of 5 at a 2.0 mm gap (only fits a half; a third holds 2 rows of 5). The top row is centred on the page (between the two mark corners), the next row is offset by the stagger `s` (≈14.2 mm) toward the left edge, and the row pitch is √(pitch² − s²) ≈ 30.9 mm. Search `s`, the top-row x (± 1 mm from centre) and y, and keep the layout with the most corner clearance.

Round labels use a **2.0 mm** gap between circles (`round_gap`) instead of 2.5 mm, so 4 staggered rows of 5 fit per half: the top row is centred between the two mark corners, the next row is shifted about 14 mm to the left so it sits in the dips, and so on. Corner clearance for circles is checked against the **real circle** (centre distance to the keep-out square minus the radius, plus bleed for the ink zone), not its bounding box.

For each candidate:
- Place rows at a fixed vertical pitch (cell height + gap; × √3/2 for hex), with the block of rows centred vertically in the piece. Search a vertical shift of ±5 mm in 0.25 mm steps.
- **Centre each row on its own.** A row's free x-range is the full usable width. If the row reaches into a corner zone vertically, its range shrinks to the space between the two corner zones (ink zone for the bleed box, cut zone for the cut box). Fit as many cells as possible into that range, centred. Rows must **not** share fixed columns: a row beside the marks may hold, for example, 2 large labels centred while the rows below hold 3. My earlier version used shared columns and lost 1 pencil, 1 large and 1 shoe pair per half this way.
- For round labels, also try the classic hex grid (alternate rows offset by half a pitch, the whole grid shifted in x and y) and keep whichever gives more. With the 2.5 mm gap the best is 19 per half; the 2.0 mm staggered grid gives 20.
- Do not shrink the whole grid the way SCM does.

Keep the candidate with the most cells. **Every label in a layout has the same orientation, in every piece.** SCM uses this rule because it keeps X/Y calibration error uniform.

The counts in the size table are the minimum the optimizer must reach. My prototype, `tools/sheet_opt.py`, reached them with exactly this algorithm. A test must assert them.

Output: `layouts/<layout_id>.json`.
- Each file stores:
  - `layout_id` (for example `chels-pencil-v1`)
  - `size`
  - the geometry hash of `sheet.json` + `sizes.json`
  - `pieces`: one cell list per piece in printed order (top, middle, bottom), each cell as `[X, Y, W, H, rotated]` in mm in the **Studio frame**, plus `per_piece` and `per_sheet` (the v1 files' `top` / `bottom` are read as two pieces)
- The layout id carries a version. Never change a published layout in place: any geometry change creates `-v2`, because the user's Studio template must match it exactly.
- Commit the generated layouts to the repo.

## Packs (`config/packs.json`): built from whole pieces

A pack is a whole number of **single-size pieces** (thirds). Combo packs are combinations of single-size pieces, never mixed rows inside a piece: mixed rows lose their end labels to the mark corners. Whole pieces keep every layout at full density, and keep the template count at 7.

| id | contents | pieces |
|---|---|---|
| pencil51 | pencil × 51 | 3 |
| small57 | small × 57 | 3 |
| medium24 | medium × 24 | 3 |
| large18 | large × 18 | 3 |
| tag102 | tag × 102 | 3 |
| round30 | round × 30 | 3 |
| shoe12 | 12 shoe pairs | 3 |
| starter (73) | pencil 17, small 38, medium 8, round 10 | 5 |
| daycare (113 + 4 shoe pairs) | tag 68, medium 16, small 19, round 10, shoe 4 | 7 |
| school (208 + 8 shoe pairs) | pencil 51, small 57, medium 16, large 6, round 10, tag 68, shoe 8 | 14 |

`python -m engine packs` prints, for each pack, the pieces per size, the sheets when batched (pieces / 3) and when printed alone (Σ ceil(pieces of a size / 3)), the envelope estimate (pieces × `piece_weight_g` + `envelope_weight_g`) and its Canada Post Lettermail class (up to 30 g, up to 50 g, over 50 g = oversized), with a warning above 12 pieces (standard Lettermail is at most 5 mm thick).

## Orders → pieces → sheets (production batching)

- **The production unit is a piece.** Each pack expands into its pieces, for example `starter` gives five: pencil, small, small, medium, round. Every piece carries its order number, line, name, design and font; its tag reads `#<order> · <name> · tiers i/n`.
- **A sheet holds three pieces with the same size (`layout_id`).**
  - The pieces can come from different orders or from the same order. For example, three `starter` orders give 3 pencil pieces (one sheet), 6 small pieces (two sheets), 3 medium and 3 round pieces (one sheet each).
  - Sheets are filled oldest piece first.
  - A sheet left with only 1 or 2 pieces: "bonus" (the default) fills the empty pieces with **bonus copies** of the last real piece (free to the customer, same envelope); "blank" leaves them empty; "wait" keeps the pieces waiting for more orders.
- Because every order fills whole pieces, there are no partly filled pieces and no spare cells to manage.
- **Packing slip:** for each order, list its pieces, the sheet number each one is printed on, and the position on that sheet (**haut / milieu / bas**), so I can collect the right pieces after trimming.
- **Print-PDF**
  - One PDF per batch, per layout.
  - Each page holds **only** what belongs on the sheet:
    - the marks
    - the art at 600 dpi, placed at the exact cell positions, with no scaling
    - trim ticks and the dashed trim guide at each trim line
  - No text on the sheet (no header, no order text): the page proofs, the info sheet and the packing slip say which order each piece belongs to. *(Half-sheets, v1, had 6 pt gutter text per half and a header line.)*
  - Use landscape pages (792 × 612 pt) with **`/Rotate 270`**, exactly like SCM (the calibration sheet keeps a header line, ending at Studio X 181, before the upper trim line).
  - Set the PDF's print-scaling preference to none (`/ViewerPreferences /PrintScaling /None`).

## Cut files and Studio templates

1. **`templates/<layout_id>.dxf`**
   - All cells of the layout, written as **closed POLYLINE** entities only (arcs flattened to segments of ≤ 0.1 mm chord error). Never loose LINE segments.
   - Units mm, y flipped for DXF.
   - Put two 0.01 mm **anchor dots** on a separate layer `ANCHOR`, at the Studio page's top-left (0, 0) and bottom-right (279.4, 215.9). They let Studio's import keep the absolute position.
   - Keep the anchors as a `--anchors` option, on by default. The instructions tell me to delete them in Studio after positioning.
2. **`templates/<layout_id>.json`**: the exact position of the cut group's bounding box, without the anchors (X, Y, width, height in mm), for when positioning is done by hand.
3. **Optional automation**
   - Add `tools/make_studio_templates.md` explaining how to run SCM's `dxf_to_studio3.py single` (Windows only, GUI automation) on my DXFs, with `--paper_size letter --orientation landscape --registration --unit mm --reg_length 10 --reg_thickness 1 --reg_inset 10 --no_center`.
   - `--no_center` is required, because our grids are not symmetric.
   - Do not vendor SCM's automation. Link to it.
4. **Manual setup, in French, in `docs/studio-template-setup.md`.** I do this once per layout:
   - Fichier → Nouveau.
   - Paramètres de page: Lettre, Paysage (same as the SCM templates).
   - Fichier → Ouvrir the DXF.
   - Select all, then Grouper.
   - Panneau Transformer: set the position X/Y from `templates/<layout_id>.json`.
   - Repères d'impression: Type 1, Longueur 10 mm, Épaisseur 1 mm, Retrait 10 mm.
   - Delete the anchors.
   - Fichier → Enregistrer sous `<layout_id>.studio3`.
   - Write each French label with the English label after it in brackets, because I want to check every one on screen.
5. **Calibration sheet**: `python -m engine calibration <layout_id>`.
   - Prints the marks plus each cell's cut outline as a 0.2 mm grey hairline, with no art.
   - I cut it on plain paper with the template. If every cut lands on its hairline, the template is right.
   - Document in French what to check and how to fix an offset: Calibrage in Studio, and re-checking the Retrait value.

## Cutting instructions (`docs/cut-settings.md`, French UI terms)

Starting points only. One custom material (vinyl + matte laminate, `Chels – vinyle + lam. mat`), set up with a **Test de découpe** first.

- Kiss cut: the blade goes through the laminate and the vinyl but not the liner.
- Start with AutoLame Profondeur 2, Force 12, Vitesse 4, Passages 1.
- Notes carried over from my proxy work:
  - Use a fresh premium blade.
  - The mat needs good tack; tape the sheet edges if the mat is tired.
  - If the left edge under-cuts, check the mat tack and the pinch-roller position before raising Force.
- Optional, off by default: a through-cut on both trim lines, on their own layer `TRIM`, with their own settings ("Découper par couleur de ligne"). Document that it scores the mat.

## Proofs

- **Page proof (per sheet)**: the layout at 150 dpi. Show the keep-out squares hatched, the laminate notch outlines, both trim lines, each piece's order text, and any bonus piece tinted.
- **Customer proof**: it shows the buyer's labels, not the sheet, in the Mazie Page Creations brand.
- **Layout gallery**: one preview per layout with its counts per piece. This is how I check a layout before making its Studio template.

## Tests (pytest)

- The counts per piece match or beat the size table above, and `pieces: 2` reproduces the v1 half-sheet layouts.
- Every piece holds the same count; the middle piece is the top piece translated (printed y + 93.133) and the bottom piece is the top piece mirrored (printed y_bottom = 279.4 − y_top − h; Studio: mirror about X = 139.7), ±0.01 mm; every cell lies inside its own piece.
- No cell's bleed box intersects any corner keep-out or crosses a trim line, no cut line is within 5 mm of a trim line, and none extends past the edge margin. Check this for every layout, every piece, and 3-mark and 4-mark modes.
- No two cells' cut boxes are closer than `gap` (circles: centre distance ≥ diameter + gap).
- The DXF has only closed POLYLINE entities on the cut layer, the cell count equals the layout's, and a round-trip parse gives positions within 0.01 mm.
- The PDF page MediaBox is exactly 792 × 612 pt with `/Rotate 270`, and the marks rasterize at the expected pixel positions at 600 dpi. Compare against the SCM fixture as described in "Orientation".
- `to_studio()` and its inverse round-trip, and the printed-view square lands at bottom-left, L at top-left and L at bottom-right.
- Changing `sheet.json` without bumping the layout version fails a test (geometry-hash check).
- Batching: three `starter` orders fill only full sheets (pencil 1, small 2, medium 1, round 1) with no bonus pieces; one `school` order printed alone gives 7 sheets with bonus copies in the empty pieces; a sheet never mixes sizes.

## Phases (of the original half-sheet work; the thirds followed reference/pipeline-update-prompt.md). Stop after each phase and show me the output.

1. `sheet.json`, the optimizer, `layouts/*.json`, the layout gallery PNGs, and the counts table. **Stop.** I review the layouts.
2. Mark rendering (ported from SCM), the print PDF, the calibration PDF, the DXF with anchors, and the French setup doc. **Stop.** I build one template and cut the calibration sheet.
3. `packs.json` seeded from the packs table, plus `packs-report` with the envelope weight estimate. **Stop.** I check the pack weights against real envelopes.
4. Batching into halves and sheets, bonus fill, the batch screen, page proofs, and the laminate notch DXF.
5. Tests green, README section "Imprimer et découper une planche".

## Do not

- Do not hand-place labels per order. Orders only fill pre-defined cells.
- Do not mix sizes or orientations inside a layout or on a sheet, and never let the pieces of a sheet differ in arrangement or count.
- Do not draw anything (art, text, guides) inside a corner keep-out.
- Do not edit a published layout in place.
- Do not change pack quantities or prices.
- Do not reuse SCM's template **names**. Our templates are named `chels-<size>-v<N>`, and their README credits SCM.
