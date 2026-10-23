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
2. **Shop fields:** the shop name (used in the description), the shipping time (on the
   How-to-order image), the shipping profile, return
   policy and processing profile IDs from this shop's Etsy settings, optionally the shop section
   and the taxonomy ID. Read the description template too: its U.S. duties notice and shipping
   wording are a starting point, check they match how this shop ships.
3. **Listings:** check the groups. Move a design with its "Move…" menu; new designs that are in
   no listing are shown at the bottom with an "Add to…" menu. Each listing has up to 13 tags:
   its own first, then the shop's.
4. **Images:** set up image hosting (below), then **Make all listing images** (about
   10 seconds per listing). Each listing gets 7 images, 2400 × 2400 PNG, in the Mazie Page Creations
   brand (`engine/listing_images.py`, logo and icons from `brand/`), in gallery order:
   `Hero` (a close-up of a sheet of the listing's labels, the listing name, 4 chips and an "up to N
   labels" badge, inside the band Etsy keeps for its 4:3 search thumbnails), `Designs` (every design
   of the listing, numbered), `Bundles` (the bundles from `packs.json`: cards for the bundles with
   several sizes, the largest marked "Most complete", pills for the single sizes), `Sizes` (the 7 sizes
   at the same scale, no ruler on purpose), `Fonts` (the font chart, shared by every listing),
   `Durable` (a close-up and the 4 "made to last" features) and `HowToOrder` (the 3 steps, with the
   shipping time from the Listings page).
5. **Download the Etsy CSV** and import it with the Etsy Connector.

The page lists everything still missing; the CSV button stays off until the list is empty.

## Image hosting (Cloudflare R2)

The images need a public web address for Etsy to fetch them. This shop has its own: give it its
own R2 bucket (in your Cloudflare account, or a separate account for the business) with a public
address, either a custom domain (e.g. `images.yourshop.com`) or the bucket's `r2.dev` URL.
Then add these Replit Secrets and restart the app:

| Secret | |
|---|---|
| `R2_ACCOUNT_ID` | the Cloudflare account ID |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | an R2 API token with Object Read & Write on the bucket |
| `R2_BUCKET` | the bucket's name |
| `R2_PUBLIC_BASE_URL` | the bucket's public address, e.g. `https://images.yourshop.com` |
| `R2_ENDPOINT` | optional (default `https://<account>.r2.cloudflarestorage.com`) |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ZONE_ID` | optional, custom domain only: purge the CDN after each run |

Images are uploaded as they are made, as flat file names (`Labels_Puppy_Kitten_Pet_Hero.png`),
so a new run replaces the old photos at the same URL.

Without R2 the images stay in the app: **Download images (ZIP)**, host them anywhere public and
put that address in "Where the images are hosted"; the CSV's image links start with it.

## Command line

```bash
python -m engine listings --out out/listings                       # every listing
python -m engine listings --out out/listings --group pets-cuddly   # one listing
```

It reads `config/listings.json` (the seed: the app keeps its own editable copy), writes
`images/` and, once the prices are set, `etsy_import_labels.csv`.
