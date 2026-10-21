# Etsy listings

The **Etsy listings** page turns the design library into a handful of Etsy listings, makes their
photos and writes the import CSV for the Etsy Connector (the same CSV format as the binder
pipeline's `etsy_import_proxies_*.csv`).

## How a listing works

One listing per **group of designs** (10 groups for the first 100 designs: dinosaurs, vehicles,
ocean, woodland, safari, farm, sports, sweets, patterns, pets). Buyers choose:

| What | Where on Etsy | CSV columns |
|---|---|---|
| Bundle (60 Skinny, 30 Medium, Back to School…) | variation 1, with a price and a SKU per bundle | `variation_name`, `variation_values`, `variation_prices`, `variation_quantities`, `variation_skus` |
| Design (Puppy Park, Dalmatian Pup…) | variation 2 | `variation2_name`, `variation2_values` |
| Name, optional second line, font number | personalization box | `is_personalizable`, `personalization_is_required`, `personalization_char_count_max`, `personalization_instructions` |

Etsy allows two variations only, so the font goes in the personalization box ("Emma Tremblay -
font 3"). The listing price is the cheapest bundle. SKUs: `LBL-PETS` for the listing,
`LBL-PETS-MED30` for one bundle.

The first 36 columns are the binder pipeline's, in the same order, with the same encoding
(UTF-8 with a BOM, LF line ends, fields quoted only when they contain `"`, `,` or a line break,
`|` between variation values and between image alts, `,` between tags and image URLs). The four
personalization columns come after them. **Check that the Etsy Connector reads them**; if it
does not, untick "Add the personalization columns" (Shop fields) and turn on personalization in Etsy.

## Before the first export

1. **Bundles:** a price for every bundle (the option names and SKU codes are already filled in).
2. **Shop fields:** shipping profile, return policy and processing profile IDs (from Etsy, the
   same ones as the binder listings), optionally the shop section and the taxonomy ID.
3. **Listings:** check the groups. Move a design with its "Move…" menu; new designs that are in
   no listing are shown at the bottom with an "Add to…" menu. Each listing has up to 13 tags:
   its own first, then the shop's.
4. **Images:** add the R2 secrets in Replit (below), then **Make all listing images** (about
   20 seconds per listing). Each listing gets 7 images, 2400 × 2400 PNG:
   `Hero` (medium labels on a sheet), `Designs` (every design of the listing, numbered),
   `Fonts` (the font chart, shared by every listing), `Bundles`, `Sizes` (to scale),
   `Closeup_Small` (skinny, small, clothing tags) and `Closeup_Round` (round, shoe pairs).
5. **Download the Etsy CSV** and import it with the Etsy Connector.

The page lists everything still missing; the CSV button stays off until the list is empty.

## Image hosting (Cloudflare R2)

Same secrets as the binder pipeline: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
`R2_BUCKET`, `R2_PUBLIC_BASE_URL` (https://assets.olliepagecreations.com), optional `R2_ENDPOINT`;
`CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ZONE_ID` to purge the CDN after each run. Images are
uploaded as they are made, as flat file names (`Labels_Puppy_Kitten_Pet_Hero.png`), so a new run
replaces the old photos at the same URL.

Without R2 the images stay in the app: **Download images (ZIP)** and host them at the address
in "Where the images are hosted"; the CSV's image links start with that address.

## Command line

```bash
python -m engine listings --out out/listings                       # every listing
python -m engine listings --out out/listings --group pets-cuddly   # one listing
```

It reads `config/listings.json` (the seed: the app keeps its own editable copy), writes
`images/` and, once the prices are set, `etsy_import_labels.csv`.
