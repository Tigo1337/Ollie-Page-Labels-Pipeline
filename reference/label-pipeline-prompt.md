# Build the Label Pipeline App

You're building a web app, starting from this empty repository. It turns Etsy orders for personalised kids' name labels into print-and-cut production files. It will be hosted on **Replit**. I'm a one-person shop. I print on an **Epson EcoTank ET-2980** (US Letter, one sheet at a time) and kiss-cut on a **Silhouette Cameo 5** using print-and-cut registration marks. The app must be simple to use and reliable. A misspelled name or a cut line that misses the print costs me a sheet of vinyl and a refund.

Work in phases (listed at the end). Commit after each phase. Show me the app running before moving on. Ask before making a decision this prompt doesn't cover. Don't guess on anything that changes the printed or cut output.

---

## 1. What the app does

1. **Design library.** I upload artwork for each design (100 designs to start; see section 6). For each design and each label size, I set **once** how the artwork is cropped and where the name goes. That setting is saved with the design and reused for every order.
2. **Orders.** I enter or import orders. Each order line = design + pack (size & quantity) + finish + name (+ optional second line) + font.
3. **Customer proof.** The app renders a proof image of every label design in the order, exactly as it will print. I send it to the buyer for a spelling check before I print.
4. **Production files.** For each order, the app generates:
   - a print PDF (one per finish)
   - a DXF and an SVG cut file per page
   - a page proof PNG per page, showing cut lines over the print
   - an info sheet with the cut-file placement for Silhouette Studio
   - a ZIP of everything
5. **Status tracking.** Each order goes through: New → Proof sent → Approved → Printed → Cut → Shipped.

## 2. Reference implementation (if present)

If the repository contains `reference/label-shop-code.zip`, unzip it to `reference/` and read it first. It is a working Python prototype of the rendering engine:
- `label_sheet.py`: rendering, packing, PDF, DXF/SVG, proofs, crop presets
- `design_review.py`: renders every size with test names
- `config/*.json`
- `get_fonts.py`

Port its behaviour into the app's engine, keeping the numbers and file formats below. Where the prototype and this prompt disagree, this prompt wins. If the reference isn't there, build from this spec alone.

## 3. Stack

- **Backend:** Python 3.11+ and FastAPI. Rendering uses Pillow, NumPy, ReportLab and fontTools; this engine is the heart of the app.
- **Frontend:** React + Vite + TypeScript, built and served by FastAPI as static files. One Replit app, one run command.
- **Storage:** Replit Object Storage for artwork, fonts and generated files. SQLite through SQLAlchemy for designs, crop presets, orders and settings, behind a storage interface so it can move to Postgres later.
- **Engine isolation:** keep the engine as a pure Python package (`engine/`) with no web dependencies, so it can be tested and run from the command line.
- No login for now (single user), but put the API behind one shared secret set in Replit Secrets.

## 4. Fixed production numbers (do not change without asking)

All measurements are in millimetres.

| Setting | Value |
|---|---|
| Page | US Letter, 215.9 × 279.4 mm, portrait |
| Print margin | 12 mm, no ink closer to any edge |
| Registration-mark keep-out | 36 × 36 mm squares at top-left, top-right and bottom-left. Nothing printed there; Silhouette Studio places its Type 1 marks there (inset 10 mm, length 20 mm, thickness 1 mm) |
| Bleed | 1.25 mm of artwork past every cut line |
| Gap | 3 mm between neighbouring cut lines |
| Safe zone | text at least 1 mm inside the cut line |
| Render resolution | 600 dpi for label art |
| Readability warning | flag any label where the name's capital-letter height is below 1.7 mm |
| Laminate notch | for gloss and holographic finishes, a 22 × 22 mm square is cut off the laminate at the three mark corners (see sheet-layout-plan.md) so the Cameo can read the marks. Generate a `laminate_notches.dxf` for this |

The print PDF must place art at true size (no scaling). The DXF must line up with the PDF exactly when imported into Silhouette Studio at the X/Y given in the info sheet. **Write a test that proves it**: rasterise the PDF, draw the cut paths, and assert the cut lines fall inside the bleed of every label.

## 5. Configuration (editable in the app, seeded from these values)

### Sizes (cut size; bleed is added automatically)

These are the standard Etsy sizes, in inch-based dimensions, as used by the top-selling Etsy label shops. Sheet layouts and counts follow `sheet-layout-plan.md`.

| id | label | shape | w × h (mm) | inches | corner r | per half | per sheet |
|---|---|---|---|---|---|---|---|
| pencil | Skinny (pencils, markers) | rounded rect | 57 × 9.5 | 2.25 × 0.375 | 3 | 30 | 60 |
| small | Small (supplies, containers) | rounded rect | 44.5 × 12.7 | 1.75 × 0.5 | 3 | 31 | 62 |
| medium | Medium (bottles, lunch boxes) | rounded rect | 63.5 × 19 | 2.5 × 0.75 | 4 | 15 | 30 |
| large | Large (books, bins, lunch bags) | rounded rect | 63.5 × 25.4 | 2.5 × 1 | 5 | 11 | 22 |
| tag | Clothing tag (care-tag sticker) | rounded rect | 25.4 × 12.7 | 1 × 0.5 | 2 | 55 | 110 |
| round | Round (bottle caps, toys, shoe dots) | circle | 32 Ø | 1.25 Ø | – | 20 | 40 |
| shoe | Shoe pair (left + right, one design split across both) | 2 rounded rects | 2 × (30 × 38), 2.5 gap | – | 4 | 8 pairs | 16 pairs |

Round labels use a **2.0 mm** gap between circles (`round_gap`) instead of 2.5 mm, so 4 staggered rows of 5 fit per half: the top row is centred between the two mark corners, the next row is shifted about 14 mm to the left so it sits in the dips, and so on. Corner clearance for circles is checked against the **real circle** (centre distance to the keep-out square minus the radius, plus bleed for the ink zone), not its bounding box. See `sheet-layout-plan.md` and `reference/sheet_opt.py`.

`shape: "pair"` (shoe) is one cell holding two cut labels. The design's crop is split down the middle so the two labels form one picture when the shoes sit side by side. Print a small "G" / "D" (gauche/droite) marker inside each label's safe area.

### Packs (Etsy variation 1, "Size & quantity")

A pack is a whole number of **half-sheets**. Each half is a single-size block from that size's fixed layout. Combos are built from single-size halves, not from mixed rows, because mixed rows lose too many labels to the mark corners.

| id | label | contents | halves |
|---|---|---|---|
| pencil60 | 60 Skinny pencil labels | pencil × 60 | 2 |
| small62 | 62 Small labels | small × 62 | 2 |
| medium30 | 30 Medium labels | medium × 30 | 2 |
| large22 | 22 Large labels | large × 22 | 2 |
| tag110 | 110 Clothing tag labels | tag × 110 | 2 |
| round40 | 40 Round labels | round × 40 | 2 |
| shoe8 | 8 pairs of shoe labels | shoe × 8 | 1 |
| starter | Starter pack (61) | pencil 30, small 31 | 2 |
| daycare | Daycare pack (86) | small 31, tag 55 | 2 |
| school | Back-to-school pack (96 + 8 shoe pairs) | pencil 30, small 31, medium 15, round 20, shoe 8 pairs | 5 |

### Finishes (Etsy variation 2)

| id | label | media | laminate | notch laminate |
|---|---|---|---|---|
| matte | Matte | white inkjet printable vinyl | matte clear overlaminate | no |
| gloss | Glossy | white inkjet printable vinyl | gloss clear overlaminate | yes |
| holographic | Holographic | white inkjet printable vinyl | holographic clear overlaminate | yes |

Each finish also has a `cost_per_sheet` that I fill in. Add a pricing helper showing sheets used and material cost per pack × finish. Export it as CSV for Etsy, and warn if packs × finishes exceeds Etsy's 70 combinations.

### Fonts

Use free Google Fonts only (SIL OFL or Apache 2.0). Download the TTF files and their licence files from `https://raw.githubusercontent.com/google/fonts/main/<repo_dir>/<file>`, and store the licences next to the fonts. `weight` sets the variable-font weight axis. `mini_ok: false` means warn when this font is used on the skinny pencil or clothing tag sizes.

| id | name | repo_dir / file | weight | mini_ok |
|---|---|---|---|---|
| 1 | Fredoka | ofl/fredoka / Fredoka[wdth,wght].ttf | 600 | ✓ |
| 2 | Baloo 2 | ofl/baloo2 / Baloo2[wght].ttf | 700 | ✓ |
| 3 | Nunito | ofl/nunito / Nunito[wght].ttf | 800 | ✓ |
| 4 | Quicksand | ofl/quicksand / Quicksand[wght].ttf | 700 | ✓ |
| 5 | Comfortaa | ofl/comfortaa / Comfortaa[wght].ttf | 700 | ✓ |
| 6 | Andika | ofl/andika / Andika-Bold.ttf | – | ✓ |
| 7 | Lilita One | ofl/lilitaone / LilitaOne-Regular.ttf | – | ✓ |
| 8 | Luckiest Guy | apache/luckiestguy / LuckiestGuy-Regular.ttf | – | ✓ |
| 9 | Chewy | apache/chewy / Chewy-Regular.ttf | – | ✓ |
| 10 | Bubblegum Sans | ofl/bubblegumsans / BubblegumSans-Regular.ttf | – | ✓ |
| 11 | Sniglet | ofl/sniglet / Sniglet-ExtraBold.ttf | – | ✓ |
| 12 | Grandstander | ofl/grandstander / Grandstander[wght].ttf | 800 | ✓ |
| 13 | Patrick Hand | ofl/patrickhand / PatrickHand-Regular.ttf | – | ✓ |
| 14 | Gochi Hand | ofl/gochihand / GochiHand-Regular.ttf | – | ✗ |
| 15 | Schoolbell | apache/schoolbell / Schoolbell-Regular.ttf | – | ✗ |
| 16 | Caveat Brush | ofl/caveatbrush / CaveatBrush-Regular.ttf | – | ✗ |
| 17 | Pacifico | ofl/pacifico / Pacifico-Regular.ttf | – | ✗ |

If a file name has changed upstream, list the folder through the GitHub contents API and pick the non-italic TTF. Add a **font chart** page that renders "Émilie-Rose" in every font with its number, as a PNG for my Etsy listing.

## 6. Designs: artwork and the per-design crop step (most important feature)

### Artwork

Each design has two images made in Google Flow (Nano Banana), about 2K resolution:
- **`wide`** (2752 × 1536): a 4:1 illustrated strip centred on a **plain white letterbox**. The character stands at the left end of the strip, the scenery runs to the right, and the middle is calm sky for the name. On upload, the engine trims the white bands robustly (reference: `tools/clean_strip.py`): an ink pixel is `min(R,G,B) < 232` or `max−min > 25`; keep the rows and columns that are more than 50 % ink; then shave edge rows/columns that are still more than 35 % white (up to 8 % of the height / 3 % of the width); then remove any near-white edge (> 247) up to 40 px, plus an 8 px safety shave. Some Flow images have a thin frame, a grey background or a character that overflows the strip, and this handles them. Store both the original and the trimmed version, and show the trimmed one.
- **`square`** (2048 × 2048): the same character in the same scene, for round labels and shoe pairs. The name area is the upper middle. Some squares come back with a white letterbox band at the top; on upload, crop it off (reference: `tools/clean_square.py`): find the top band of rows that are more than 85 % near-white (at most 45 % of the height), add 1 % of the height, then keep the square `(0, band, H−band, H)` (it can be resized back to 2048 afterwards).

The library has **100 designs**. The full settings (scene, text colours, `mini_start`, `square_text`) are in `config/themes.json`, and the 7 designs marked *presets* have saved crop presets in `themes/<id>/crops.json`; both are in `label-shop-code.zip`. Seed the app from those files rather than from this table.

| # | id | name | name fill | name stroke | char_end | presets |
|---|---|---|---|---|---|---|
| 1 | dino | Dino Stomp | #1F5C38 | #FFFFFF | 0.20 | yes |
| 2 | unicorn | Unicorn Dreams | #7A3E9D | #FFFFFF | 0.23 |  |
| 3 | fox | Forest Fox | #8A3B12 | #FFFFFF | 0.25 |  |
| 4 | panda | Bamboo Panda | #2F4F2F | #FFFFFF | 0.25 |  |
| 5 | axolotl | Axolotl Pond | #1F5F7A | #FFFFFF | 0.30 |  |
| 6 | bunny | Carrot Bunny | #B03A64 | #FFFFFF | 0.17 |  |
| 7 | space-cat | Space Cat | #FFFFFF | #1B1F4F | 0.23 |  |
| 8 | shark | Shark Splash | #1D4E89 | #FFFFFF | 0.27 |  |
| 9 | dragon | Little Dragon | #5B2C83 | #FFFFFF | 0.21 |  |
| 10 | penguin | Snowy Penguin | #1F3B63 | #FFFFFF | 0.21 |  |
| 11 | frog | Lily Pad Frog | #2E6B2E | #FFFFFF | 0.23 |  |
| 12 | octopus | Ocean Octopus | #1F6E70 | #FFFFFF | 0.22 |  |
| 13 | bee | Busy Bee | #6B4A00 | #FFFFFF | 0.26 |  |
| 14 | rocket | Rocket Launch | #FFFFFF | #141C3D | 0.24 |  |
| 15 | excavator | Little Digger | #7A4A00 | #FFFFFF | 0.32 |  |
| 16 | strawberry | Strawberry Picnic | #B0243C | #FFFFFF | 0.20 |  |
| 17 | ice-cream | Ice Cream Party | #C2376B | #FFFFFF | 0.20 |  |
| 18 | soccer | Soccer Star | #1E5C2A | #FFFFFF | 0.26 |  |
| 19 | rainbow-clouds | Rainbow Sky | #4A5BB0 | #FFFFFF | 0.31 |  |
| 20 | daisy-checker | Daisy Checker | #6A3E9E | #FFFFFF | 0.29 |  |
| 21 | confetti | Confetti Pop | #6D28D9 | #FFFFFF | 0.32 |  |
| 22 | llama | Llama Mountains | #8A4B2A | #FFFFFF | 0.20 |  |
| 23 | raccoon | Campfire Raccoon | #FFFFFF | #123B3C | 0.27 |  |
| 24 | koala | Cozy Koala | #3E6B4F | #FFFFFF | 0.18 |  |
| 25 | hedgehog | Apple Hedgehog | #8A3B12 | #FFFFFF | 0.21 |  |
| 26 | owl | Night Owl | #FFFFFF | #1B1F4F | 0.21 |  |
| 27 | teacup-kitten | Teacup Kitten | #B03A64 | #FFFFFF | 0.26 |  |
| 28 | corgi | Puppy Park | #B4521B | #FFFFFF | 0.19 |  |
| 29 | ladybug | Ladybug Garden | #B3202A | #FFFFFF | 0.29 |  |
| 30 | mer-kitty | Mer-Kitty Lagoon | #2A7F8F | #FFFFFF | 0.24 |  |
| 31 | robot | Robot Workshop | #2C5C8A | #FFFFFF | 0.24 |  |
| 32 | monster | Fuzzy Monster | #6A3EA1 | #FFFFFF | 0.23 |  |
| 33 | ghost | Little Boo | #FFFFFF | #3D2E63 | 0.15 |  |
| 34 | train | Choo-Choo Train | #C0392B | #FFFFFF | 0.22 |  |
| 35 | parrot | Pirate Parrot | #1D6FA3 | #FFFFFF | 0.18 |  |
| 36 | balloon-bear | Balloon Bear | #6A4A2A | #FFFFFF | 0.21 |  |
| 37 | sushi | Sushi Buddies | #FFFFFF | #9E2F2A | 0.31 |  |
| 38 | pizza | Pizza Party | #B3202A | #FFFFFF | 0.19 |  |
| 39 | hockey | Hockey Puck | #B3202A | #FFFFFF | 0.24 |  |
| 40 | groovy-flowers | Groovy Flowers | #8A4A00 | #FFFFFF | 0.35 |  |
| 41 | sweet-hearts | Sweet Hearts | #C2185B | #FFFFFF | 0.36 |  |
| 42 | red-panda | Red Panda Treetop | #7A2E14 | #FFFFFF | 0.28 |  |
| 43 | hippo | Bubble Hippo | #1D4E89 | #FFFFFF | 0.30 |  |
| 44 | giraffe | Tall Giraffe | #8A4B08 | #FFFFFF | 0.25 |  |
| 45 | elephant | Splash Elephant | #1F4E79 | #FFFFFF | 0.22 |  |
| 46 | tiger | Tiger Cub | #14532D | #FFFFFF | 0.27 |  |
| 47 | capybara | Chill Capybara | #5B3A1E | #FFFFFF | 0.29 |  |
| 48 | hamster | Hamster Snack | #7C4A03 | #FFFFFF | 0.25 |  |
| 49 | turtle | Beach Turtle | #0E5E6F | #FFFFFF | 0.30 |  |
| 50 | seal | Snowy Seal | #1E3A5F | #FFFFFF | 0.30 |  |
| 51 | flamingo | Flamingo Lagoon | #B0215F | #FFFFFF | 0.20 |  |
| 52 | beaver | Busy Beaver | #5A3311 | #FFFFFF | 0.24 |  |
| 53 | dalmatian | Dalmatian Pup | #B91C1C | #FFFFFF | 0.25 |  |
| 54 | moose | Maple Moose | #7F1D1D | #FFFFFF | 0.25 |  |
| 55 | polar-bear | Northern Lights Bear | #FFFFFF | #1E1B4B | 0.23 |  |
| 56 | kangaroo | Hoppy Kangaroo | #7C2D12 | #FFFFFF | 0.28 |  |
| 57 | narwhal | Narwhal Sea | #1E3A8A | #FFFFFF | 0.30 |  |
| 58 | chick | Spring Chick | #9A3412 | #FFFFFF | 0.25 |  |
| 59 | piglet | Muddy Piglet | #9D174D | #FFFFFF | 0.27 |  |
| 60 | cow | Happy Cow | #14532D | #FFFFFF | 0.32 |  |
| 61 | lamb | Little Lamb | #6D28D9 | #FFFFFF | 0.26 |  |
| 62 | snail | Rainy Snail | #065F46 | #FFFFFF | 0.32 |  |
| 63 | butterfly | Butterfly Garden | #7E22CE | #FFFFFF | 0.32 |  |
| 64 | crab | Crabby Beach | #B91C1C | #FFFFFF | 0.28 |  |
| 65 | otter | River Otter | #1E40AF | #FFFFFF | 0.36 |  |
| 66 | squirrel | Acorn Squirrel | #9A3412 | #FFFFFF | 0.35 |  |
| 67 | chameleon | Rainbow Chameleon | #065F46 | #FFFFFF | 0.33 |  |
| 68 | gnome | Garden Gnome | #991B1B | #FFFFFF | 0.24 |  |
| 69 | pirate | Pirate Ship | #7C2D12 | #FFFFFF | 0.35 |  |
| 70 | knight | Brave Knight | #1E3A8A | #FFFFFF | 0.22 |  |
| 71 | alien | Friendly Alien | #FFFFFF | #3B0764 | 0.33 |  |
| 72 | fire-truck | Fire Truck | #B91C1C | #FFFFFF | 0.30 | yes |
| 73 | tractor | Farm Tractor | #365314 | #FFFFFF | 0.33 | yes |
| 74 | race-car | Race Car | #1F2937 | #FFFFFF | 0.25 |  |
| 75 | airplane | Little Airplane | #1E40AF | #FFFFFF | 0.30 | yes |
| 76 | sailboat | Sailboat | #0C4A6E | #FFFFFF | 0.18 |  |
| 77 | submarine | Yellow Submarine | #FFFFFF | #0C4A6E | 0.30 |  |
| 78 | ballet-mouse | Ballet Mouse | #9D174D | #FFFFFF | 0.24 |  |
| 79 | basketball | Basketball Star | #9A3412 | #FFFFFF | 0.32 |  |
| 80 | skateboard | Skate Cat | #4C1D95 | #FFFFFF | 0.22 |  |
| 81 | guitar | Rock Guitar | #FFFFFF | #3B0764 | 0.25 |  |
| 82 | paint-palette | Little Artist | #1E3A8A | #FFFFFF | 0.30 |  |
| 83 | camping | Camp Out | #FFFFFF | #1C1917 | 0.20 |  |
| 84 | snowman | Snow Buddy | #1E3A8A | #FFFFFF | 0.22 |  |
| 85 | cupcake | Cupcake Shop | #9D174D | #FFFFFF | 0.25 |  |
| 86 | donut | Sprinkle Donut | #BE185D | #FFFFFF | 0.28 |  |
| 87 | watermelon | Watermelon Fun | #BE123C | #FFFFFF | 0.30 |  |
| 88 | avocado | Happy Avocado | #365314 | #FFFFFF | 0.24 |  |
| 89 | cactus | Desert Cactus | #7C2D12 | #FFFFFF | 0.27 |  |
| 90 | polka-dots | Polka Party | #BE185D | #FFFFFF | 0.33 |  |
| 91 | gingham | Picnic Gingham | #991B1B | #FFFFFF | 0.33 |  |
| 92 | moon-stars | Moon and Stars | #FFFFFF | #1E1B4B | 0.42 | yes |
| 93 | tie-dye | Tie-Dye Swirl | #5B21B6 | #FFFFFF | 0.30 |  |
| 94 | leopard | Pastel Leopard | #6B21A8 | #FFFFFF | 0.27 |  |
| 95 | smiley-check | Smiley Check | #9A3412 | #FFFFFF | 0.33 |  |
| 96 | sakura | Cherry Blossom | #BE185D | #FFFFFF | 0.37 | yes |
| 97 | mushrooms | Mushroom Meadow | #7F1D1D | #FFFFFF | 0.36 | yes |
| 98 | seashells | Seashell Shore | #0E7490 | #FFFFFF | 0.35 |  |
| 99 | camo | Jungle Camo | #FFFFFF | #14532D | 0.36 |  |
| 100 | terrazzo | Rainbow Terrazzo | #1E3A8A | #FFFFFF | 0.33 |  |

- The **name stroke** is a white (or dark) outline around the letters. Its width is 20 % of the cap height for a white stroke and 14 % for a dark one.
- **`char_end`** is where the character ends across the trimmed wide strip (0–1). It's only the starting value for the automatic layout.

On my computer the art is organised as `Label Designs\<id>\<id>_wide.jpg` and `<id>_square.jpg`. Add a **bulk import**: I upload a ZIP of that folder, and the app matches files to designs by folder name.

### Automatic layout (the fallback when a size has no saved preset)

- **Rectangular sizes:**
  - Scale the trimmed strip to the label height plus bleed and anchor it to the left, so the character stays visible.
  - The text box runs from `char_end × scaled strip width − bleed + 1 mm` to the right edge minus padding.
  - Vertical padding is `max(1 mm, 0.45 × corner radius) × 0.7`.
- **Round sizes and tall sizes** (height ≥ 0.8 × width, which includes each half of a shoe pair):
  - Scale the square image to cover, centred.
  - The text box is x 0.14–0.86 and y 0.14–0.40 of the label.
- **Clothing tag (`tag`, 25.4 × 12.7) has no character by default.** Use the strip's scenery only: start the crop at `mini_start` (0.24) of the strip width, which is past the character, and let the name fill the label. With the character, long names fell to 1.5 mm caps; without it, they stay above 4 mm. This is a per-size default (`no_character_sizes: ["tag"]`), and a crop preset can still override it for a given design.
- **Shoe pair:** the crop covers the whole pair cell (62.5 × 38 mm plus bleed) from the square image and is then split into the left and right labels, so the picture continues across both. The name goes on both labels. Show the split in the crop editor as a vertical line with the 2.5 mm gap.

### Crop presets (saved once per design per size, then reused for every order)

Store each preset as:

```json
{ "source": "wide" | "square",
  "center": [cx, cy],      // crop centre as fractions of the (trimmed) source image
  "height": h,             // crop height as a fraction of the source height; width follows the label shape automatically
  "text":   [x0, y0, x1, y1]  // name box as fractions of the cut label
}
```

The crop math:
- crop height = `h × source height`
- crop width = `crop height × (label width + 2·bleed) / (label height + 2·bleed)`
- If the width is larger than the source, clamp it and recompute the height.
- Clamp the window inside the image, crop it, and resize to the label pixels.

### Crop editor (a screen in the design library)

- Pick a design, then a size.
- Show the source image (wide or square, switchable) with a **draggable, zoomable crop window**. The crop window is locked to the label's shape plus bleed.
- Overlay three things on the source image:
  - the cut line (the label's real shape: rounded rect or circle)
  - the bleed edge
  - the name box, which I can drag and resize
- Show a **live label preview** beside it, rendered by the real engine, with a short test name ("Léo") and a long one ("Maximilien"). Show the cap height in mm and a red warning under 1.7 mm.
- Buttons: **Save preset**, **Reset to automatic**, and **Copy preset to all rectangular sizes**. Keep fractions, so presets survive replacing the artwork with a same-shaped image.
- A **design review sheet**: renders all six sizes with short and long names, plus a two-line name (Alexandre / Tremblay-Gagnon), to check a design at a glance. Downloadable as PNG.
- **Per design, also editable:** name colour, stroke colour, stroke ratio, and a max cap-height fraction for the text box (default 0.52). The text also fits the box width.

## 7. Text rendering

1. Normalise the name with NFC and collapse whitespace.
2. **Glyph check:** use fontTools' cmap to check that every character exists in the chosen font. If any are missing, block the order line and list the fonts that do have them. Names come from everywhere: Zoë, Łukasz, Søren, Nguyễn, Müller.
3. **Fit:** binary-search the largest font size where the text, including its stroke, fits the box width and height, and the cap height is at most `cap_frac × box height`. Centre the text in the box using the cap height, and clamp it so ascenders and descenders stay inside the box.
4. **Optional line2:** the box splits 60/40 with a 4 % gap, and each line is fitted separately.
5. **Warnings:** warn when the cap height is under 1.7 mm, or when a `mini_ok: false` font is used on pencil or tag labels.

## 8. Sheet layout and cut files

- **Pack per finish.** Each finish prints on its own sheets, so expand every order line into one job per label and group the jobs by finish.
- **Layout.** My prototype uses shelf packing (tallest labels first, rows of identical sizes, skipping the keep-out squares) and it works, but **I find its layout messy**. Make the layout tidy and predictable:
  - group labels from the same name together
  - fill rows edge to edge, with rows centred or left-aligned consistently
  - never mix sizes within a row
  - minimise the number of sheets
  - when a pack only part-fills a sheet, start it at the top-left
  - isolate the packing algorithm behind an interface so I can change strategies later
- **Show the numbers.** The pricing helper and the order screen show labels per full sheet for each size and sheets per pack.
- **DXF format.** R12 DXF, millimetres, one closed POLYLINE per label on layer `CUT`, with y flipped (page height − y) so it imports the right way up. Use 12 segments per rounded corner and 96 per circle.
- **SVG.** Also export an SVG of the same paths: red stroke, 0.2 mm, `viewBox` in mm.
- **Info sheet.** For each page, list how many labels it holds and the X, Y, W and H (mm) of the cut-path bounding box, so I can type them into Silhouette Studio. **My Silhouette Studio is in French, so all Studio instructions must use the French interface labels.** Put the instruction text in one editable template and ask me to confirm the exact French labels.
- **Production steps.** The info sheet also lists the steps:
  1. print at 100 %, one sheet at a time
  2. let the ink dry, ideally overnight (dye ink)
  3. laminate (notch the laminate first for gloss and holographic)
  4. load the sheet on the mat, import the cut file, and place it at X/Y
  5. kiss cut through the laminate and vinyl, not the backing
- **Page proof (150 dpi).** The printed art with red cut lines, grey hatched keep-out squares and blue laminate-notch lines when relevant.

## 9. Proofs

- **Customer proof.** A friendly PNG headed "Please check the spelling", listing the order number and names. It shows one of each unique label (design × size × name × font × finish) as the buyer will see it: cut to shape, with a soft shadow and a caption giving size and finish.
- **Holographic preview.** For the holographic finish, previews and listing images get a simulated holographic sheen (rainbow soft-light blend plus a diagonal sheen). This is **never printed**.
- **Proof wording.** All proof text is editable, and I'd like English and French versions.

## 10. Orders

- **Manual order form.** Fields: design, pack, finish, name, line2, font (with live preview and the glyph check).
- **CSV import.** An import of my Etsy orders. Map variations through **SKU**: each Etsy variation gets the SKU `<design>-<pack>-<finish>`, for example `dino-school-holographic`. Parse the personalisation answers (Name, Second line, Font number) from the CSV columns, and show a mapping screen the first time so I can match column names.
- **Etsy API.** Leave a clean seam for a future Etsy API sync, but don't build it now.
- **Multiple names.** One order can contain several names (siblings). Each order line is its own name.
- **Batch printing.** Let me select several approved orders with the same finish and print them as one batch, to save vinyl. Each label keeps its order id, and the page proof shows which order each label belongs to.
- **Order detail page.** Shows the status, the customer proof (download plus "mark proof sent"), the generate button, file downloads and any warnings.

## 11. Quality bar and tests

- **Engine tests (pytest):**
  - packing never overlaps labels, the keep-out squares or the margins
  - every label's bleed box stays on the page
  - DXF and PDF alignment (the rasterise test from section 4)
  - crop preset math, including clamping
  - text fitting stays inside its box for very long names (for example "Maximilien-Alexandre")
  - the glyph check catches missing characters
  - white-band trimming
- **Golden test.** One order that renders every size with short, long and two-line names. Snapshot the outputs' dimensions and label counts, not pixels.
- **Clear errors in the UI.** Missing fonts, missing artwork, unknown SKU and similar problems must show a plain message; never a stack trace.
- **Speed.** Rendering a 132-label pack must take under 10 seconds. Cache rendered labels keyed on design + size + preset + name + font + finish.

## 12. Phases

1. **Engine + CLI.** Port the engine with all the rules above, plus the font downloader and a CLI (`order`, `fontchart`, `review`, `packs`). Pass all the tests.
2. **Design library.** Upload, bulk ZIP import, white-band trimming, design settings and the review sheet.
3. **Crop editor.** Per-design, per-size presets with the live preview.
4. **Orders.** Manual entry, CSV import with SKU mapping, the customer proof, production file generation, ZIP download and status tracking.
5. **Batching + polish.** Batch printing across orders, the pricing/variations CSV, the font chart, and editable French/English text.

At the end of each phase, give me a short summary of what to test by hand and anything you assumed.
