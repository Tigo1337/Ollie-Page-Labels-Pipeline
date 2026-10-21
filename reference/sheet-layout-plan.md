# Claude Code prompt: max-density US Letter label sheets with Cameo 5 marks and envelope halves

Paste everything below the line into Claude Code, opened in the **label Pipeline App repository** (the FastAPI + React app built from `label-pipeline-prompt.md`). It replaces the current shelf-packing layout (`pack()` in the engine) with fixed, optimized layouts.

Attach or copy these files into the repo's `reference/` folder before you paste the prompt:
- `sheet_opt.py`: my prototype optimizer, which produced the counts below
- `test_sheets_pdf.py` and `label-layout-test-sheets.pdf`: a prototype SCM-style PDF with marks and cut outlines, verified to print like my proxies
- `Starter_15-22_portrait.pdf`: one of my SCM proxy PDFs, used as the orientation fixture

---

## Context

I sell custom kids' name labels on Etsy. I print them on an **Epson ET-2980** onto white inkjet printable vinyl, laminate them (matte, gloss or holographic cold overlaminate), and kiss-cut them on a **Silhouette Cameo 5** using print-and-cut registration marks. After cutting, I trim each Letter sheet into **two half-sheets (215.9 × 139.7 mm)** so they ship flat in a standard letter envelope (Canada Post Lettermail, max 245 × 156 mm, 5 mm thick; a 6×9 in envelope fits).

My card-proxy business already uses a proven print-and-cut workflow: **Alan-Cha/silhouette-card-maker (SCM, MIT licence)**. It works like this:
- The PDF has the registration marks drawn into it.
- A matching `.studio3` template holds the same marks plus the cut lines. It is set up once per layout and reused.
- I print the PDF from my PDF viewer at 100 %, open the template in Silhouette Studio, and send the cut.

The labels must work the same way.

Silhouette Studio is in **French** on my PC. Any instructions you write for me must use the French interface labels (for example ENVOYER, Découper, Fichier → Ouvrir, AutoLame, Profondeur, Force, Vitesse, Passages).

## Goal

1. One **fixed, maximum-density layout per label size**. Every order of that size uses the same cut grid, so each layout needs only **one Studio template**, made once. That is **7 templates in total**, one per size.
2. Each sheet is split into a **top half and a bottom half**, with a trim gutter between them. Each half must be a self-contained, shippable piece.
3. **Both halves are identical.** The bottom half is the top half mirrored about the trim line, so after trimming the two pieces have exactly the same arrangement and count. It is never a different arrangement. This is a hard rule.
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
2. The **printed view** is used only for human-facing wording (top half and bottom half, as I hold the sheet) and for proofs. Map between the two frames with:
   - point: printed `(x, y)` ↔ Studio `(X, Y) = (279.4 − y, x)`
   - rect: printed `(x, y, w, h)` → Studio `(279.4 − y − h, x, h, w)`
   - Put this transform in one tested function, `to_studio()` and its inverse, and nowhere else.
3. The marks are drawn exactly as SCM's `page_manager.generate_reg_mark` draws them in **THREE-mark mode**. Port that function, credit SCM (MIT) in a comment, and follow **the code, not the SPECIFICATION.md wording**: the 5 × 5 mm filled square has its *corner* at (inset, inset), and the L arms run `length` mm inward from the corner point at `inset`. Use our `sheet.json` values for inset, length and thickness. SCM's v6 uses a length of 8.04 mm; ours is 10 mm, and the Studio template uses the same 10 mm.
4. In the Studio frame, **the envelope trim line is vertical at X = 139.7 mm**. The printed "top half" is the Studio **right** half (X > 139.7), and the printed "bottom half" is the Studio **left** half, which holds the square mark.
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
  "trim": {"y": 139.7, "margin_each_side": 5.0, "ticks_mm": 6.0, "dashed_guide": true},
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
  - It applies to **all four corners**, including the unmarked one (Studio bottom-right, printed top-right), because the two halves mirror each other. As a result, the layouts also work unchanged with 4-mark registration (Cameo 5 Alpha style). Support `marks: 4` as an option.
- **`laminate_notch`**
  - The laminate sheet has 22 × 22 mm squares removed at the three mark corners (Studio top-left, top-right and bottom-left), so the laminate never covers a mark. Shiny gloss and holographic laminate break mark scanning.
  - Use it for **all finishes**, matte included, so every finish shares the same templates.
  - Keep a generator for `laminate_notches.dxf`: a Letter-size outline with the 3 notches, cut from the laminate sheet before it is applied.
- **`edge_margin`**: cut lines stay at least 10 mm from the outer paper edges, inside the mark rectangle, like SCM. Bleed may extend into that margin.
- **`trim`**
  - The sheet is trimmed at Studio X = 139.7 mm (printed y = 139.7 mm, across the middle of the portrait sheet).
  - No cut line may come within 5 mm of the trim line, so the gutter is 10 mm wide.
  - Print 6 mm black trim ticks at both side edges, plus a light-grey dashed guide across the gutter.
  - The marks never touch the gutter.
- **`gap` / `bleed`**
  - Cut lines are 2.5 mm apart, and the art extends 1.25 mm past every cut line, so neighbouring bleeds meet but never overlap.
  - Round labels get a **circular** bleed mask, not a square one.

## Label sizes (`config/sizes.json`)

The sizes are the **standard Etsy kids' name-label sizes**: inch-based dimensions used by the top-selling Etsy label shops, cross-checked against Mabel's Labels, Name Bubbles, Colle à Moi, Stuck On You and others.

| id | use | cut size (mm) | inches | corner r | arrangement | per half | per sheet |
|---|---|---|---|---|---|---|---|
| pencil | pencils, markers, crayons | 57 × 9.5 | 2.25 × 0.375 | 3 | rotated (vertical), rows 14 + 16 | 30 | **60** |
| small | supplies, containers (most common Etsy size) | 44.5 × 12.7 | 1.75 × 0.5 | 3 | normal, rows 3 + 7 × 4 | 31 | **62** |
| medium | bottles, lunch boxes | 63.5 × 19 | 2.5 × 0.75 | 4 | normal, 5 rows × 3 | 15 | **30** |
| large | books, bins, lunch bags | 63.5 × 25.4 | 2.5 × 1 | 5 | normal, rows 2 + 3 + 3 + 3 | 11 | **22** |
| tag | clothing care-tag stickers | 25.4 × 12.7 | 1 × 0.5 | 2 | normal, rows 6 + 7 × 7 | 55 | **110** |
| round | bottle caps, toys, shoe dots | 32 Ø | 1.25 Ø | – | staggered, 4 rows of 5, 2.0 mm gap | 20 | **40** |
| shoe | left/right pair, one design split across both | 2 × (30 × 38), 2.5 gap | – | 4 | normal, rows 2 + 3 + 3 pairs | 8 pairs | **16 pairs** |

Rows are listed from the mark-corner edge of the half inward (printed view: top row first in the top half).

The 63.5 mm width is deliberate. Three columns plus two gaps take 195.5 mm of the 195.9 mm usable width, so three columns fit. At 66 mm only two columns fit (10 medium or 8 large per half instead of 15 or 10).

The shoe size uses `shape: "pair"`: one layout cell holds **two** cut labels side by side. The design's crop is split down the middle, so the two labels form one picture when the shoes sit side by side, and each label shows a small "G" or "D" (gauche/droite) marker in its safe area.

## Layout optimizer (`engine/layout.py`)

You may optimize in the printed view (it is easier to reason about), then convert with `to_studio()`.

Optimize **only the printed top half** (corner keep-outs at printed top-left and top-right). The printed bottom half is then generated by **mirroring every cell about the trim line**: printed `y_bottom = 279.4 − y_top − cell_h`, with x unchanged. In the Studio frame this is a mirror about X = 139.7. Never optimize the second half on its own.

Candidates to try for the top half:
1. A normal grid (label horizontal).
2. A rotated grid (label turned 90°), for non-square sizes.
3. For `round` only, a **staggered** grid: 4 rows of 5 at a 2.0 mm gap. The top row is centred on the page (between the two mark corners), the next row is offset by the stagger `s` (≈14.2 mm) toward the left edge, and the row pitch is √(pitch² − s²) ≈ 30.9 mm. Search `s`, the top-row x (± 1 mm from centre) and y, and keep the layout with the most corner clearance.

Round labels use a **2.0 mm** gap between circles (`round_gap`) instead of 2.5 mm, so 4 staggered rows of 5 fit per half: the top row is centred between the two mark corners, the next row is shifted about 14 mm to the left so it sits in the dips, and so on. Corner clearance for circles is checked against the **real circle** (centre distance to the keep-out square minus the radius, plus bleed for the ink zone), not its bounding box.

For each candidate:
- Place rows at a fixed vertical pitch (cell height + gap; × √3/2 for hex), with the block of rows centred vertically in the half. Search a vertical shift of ±5 mm in 0.25 mm steps.
- **Centre each row on its own.** A row's free x-range is the full usable width. If the row reaches into a corner zone vertically, its range shrinks to the space between the two corner zones (ink zone for the bleed box, cut zone for the cut box). Fit as many cells as possible into that range, centred. Rows must **not** share fixed columns: a row beside the marks may hold, for example, 2 large labels centred while the rows below hold 3. My earlier version used shared columns and lost 1 pencil, 1 large and 1 shoe pair per half this way.
- For round labels, also try the classic hex grid (alternate rows offset by half a pitch, the whole grid shifted in x and y) and keep whichever gives more. With the 2.5 mm gap the best is 19 per half; the 2.0 mm staggered grid gives 20.
- Do not shrink the whole grid the way SCM does.

Keep the candidate with the most cells. **Every label in a layout has the same orientation, in both halves.** SCM uses this rule because it keeps X/Y calibration error uniform.

The counts in the size table are the minimum the optimizer must reach. My prototype, `tools/sheet_opt.py`, reached them with exactly this algorithm. A test must assert them.

Output: `layouts/<layout_id>.json`.
- Each file stores:
  - `layout_id` (for example `chels-pencil-v1`)
  - `size`
  - the geometry hash of `sheet.json` + `sizes.json`
  - `top` and `bottom` cell lists (printed view naming), each cell as `[X, Y, W, H, rotated]` in mm in the **Studio frame**
- The layout id carries a version. Never change a published layout in place: any geometry change creates `-v2`, because the user's Studio template must match it exactly.
- Commit the generated layouts to the repo.

## Packs (`config/packs.json`): built from whole halves

A pack is a whole number of **single-size halves**. Combo packs are combinations of single-size halves, never mixed rows inside a half. My prototype tried mixed rows, and they fit only about 20 labels per half because rows lose their end labels to the mark corners. Whole halves keep every layout at full density, and keep the template count at 7.

| id | contents | halves | labels |
|---|---|---|---|
| pencil60 | pencil × 60 | 2 | 60 |
| small62 | small × 62 | 2 | 62 |
| medium30 | medium × 30 | 2 | 30 |
| large22 | large × 22 | 2 | 22 |
| tag110 | tag × 110 | 2 | 110 |
| round40 | round × 40 | 2 | 40 |
| shoe8 | 8 shoe pairs | 1 | 16 |
| starter | 1 pencil half + 1 small half | 2 | 61 |
| daycare | 1 small half + 1 tag half | 2 | 86 |
| school | 1 half each of pencil, small, medium, round, shoe | 5 | 96 + 8 pairs |

Seed `packs.json` with this table. Add `python -m engine packs-report`. For each pack it prints the halves used, labels per size, the envelope weight estimate (halves × measured g per half, plus the envelope and a stiffener card), and whether the pack still fits standard Lettermail (30 g, 5 mm) or needs oversized letter / Small Packet.

## Orders → halves → sheets (production batching)

- **The production unit is a half.** Each pack expands into its halves, for example `school` gives five halves: pencil, small, medium, round and shoe. Every half carries its order number, name, design and finish.
- **A sheet holds two halves with the same size (`layout_id`) and the same finish.**
  - The halves can come from two different orders or from the same order. For example, two `starter` orders give 2 pencil halves (one sheet) and 2 small halves (one sheet).
  - The batch screen pairs halves automatically, oldest first, and lists any half that is waiting for a partner.
  - A button "Imprimer seul" prints a waiting half alone. Its other half becomes a **bonus copy** of the same order (same name and design), which is free to the customer and goes in the same envelope. A toggle prints that other half blank instead.
- Because every order fills whole halves, there are no partly filled halves and no spare cells to manage.
- **Packing slip:** for each order, list its halves, the sheet number each one is printed on, and the half position on that sheet (haut/bas), so I can collect the right pieces after trimming.
- **Print-PDF**
  - One PDF per batch, per finish, per layout.
  - Each page has:
    - the marks
    - the art at 600 dpi, placed at the exact cell positions, with no scaling
    - trim ticks and the trim guide
    - tiny 6 pt grey text in the gutter, 2 mm from the trim line inside each half: `#<order> · <name> · <finish> · <half i/n>`
    - a header line in the free margin, outside the keep-outs, like SCM's: `sheet: N · template: chels-pencil-v1`
  - Use landscape pages (792 × 612 pt) with **`/Rotate 270`**, exactly like SCM.
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

Starting points only. Each finish gets a **Test de découpe** first, saved as a custom material per finish (for example `Chels – vinyle + lam. holo`).

- Kiss cut: the blade goes through the laminate and the vinyl but not the liner.
- Start with AutoLame Profondeur 2, Force 12, Vitesse 4, Passages 1.
- Holographic laminate usually needs more Force; raise it 2 at a time.
- Notes carried over from my proxy work:
  - Use a fresh premium blade.
  - The mat needs good tack; tape the sheet edges if the mat is tired.
  - If the left edge under-cuts, check the mat tack and the pinch-roller position before raising Force.
- Optional, off by default: a through-cut on the trim line, on its own layer `TRIM`, with its own settings ("Découper par couleur de ligne"). Document that it scores the mat.

## Proofs

- **Page proof (per sheet)**: the layout at 150 dpi. Show the keep-out squares hatched, the laminate notch outlines, the trim line, each half's order labels, and any bonus half tinted.
- **Customer proof**: unchanged. It shows the buyer's labels, not the sheet.
- **Layout gallery** (`/layouts` page in the app): one preview per layout with its counts per half. This is how I check a layout before making its Studio template.

## Tests (pytest)

- The counts per half match or beat the size table above.
- The bottom half of every layout is the exact mirror of its top half: same count and same arrangement, with printed y_bottom = 279.4 − y_top − h (Studio: mirror about X = 139.7), ±0.01 mm.
- No cell's bleed box intersects any corner keep-out or the trim zone, and none extends past the edge margin. Check this for every layout, both halves, and 3-mark and 4-mark modes.
- No two cells' cut boxes are closer than `gap` (circles: centre distance ≥ diameter + gap).
- The DXF has only closed POLYLINE entities on the cut layer, the cell count equals the layout's, and a round-trip parse gives positions within 0.01 mm.
- The PDF page MediaBox is exactly 792 × 612 pt with `/Rotate 270`, and the marks rasterize at the expected pixel positions at 600 dpi. Compare against the SCM fixture as described in "Orientation".
- `to_studio()` and its inverse round-trip, and the printed-view square lands at bottom-left, L at top-left and L at bottom-right.
- Changing `sheet.json` without bumping the layout version fails a test (geometry-hash check).
- Batching: two `starter` orders produce exactly one pencil sheet and one small sheet; a half never mixes sizes or finishes; "Imprimer seul" makes a bonus copy of the same order.

## Phases. Stop after each phase and show me the output.

1. `sheet.json`, the optimizer, `layouts/*.json`, the layout gallery PNGs, and the counts table. **Stop.** I review the layouts.
2. Mark rendering (ported from SCM), the print PDF, the calibration PDF, the DXF with anchors, and the French setup doc. **Stop.** I build one template and cut the calibration sheet.
3. `packs.json` seeded from the packs table, plus `packs-report` with the envelope weight estimate. **Stop.** I check the pack weights against real envelopes.
4. Batching into halves and sheets, bonus fill, the batch screen, page proofs, and the laminate notch DXF.
5. Tests green, README section "Imprimer et découper une planche".

## Do not

- Do not hand-place labels per order. Orders only fill pre-defined cells.
- Do not mix sizes or orientations inside a layout, never mix finishes on one sheet, and never let the bottom half differ from the top half.
- Do not draw anything (art, text, guides) inside a corner keep-out.
- Do not edit a published layout in place.
- Do not change pack quantities or prices.
- Do not reuse SCM's template **names**. Our templates are named `chels-<size>-v<N>`, and their README credits SCM.
