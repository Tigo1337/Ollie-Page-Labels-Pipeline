"""Etsy listings: groups, CSV format (the binder pipeline's), images, R2 signing, API."""
import copy
import csv
import datetime as dt
import io
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.listings_service import validate
from app.main import create_app
from app.r2 import R2Config, sign_v4
from app.settings import REPO, Settings
from engine.config import load_catalog
from engine.listing_images import ListingImages
from engine.listings import (CSV_HEADER, ETSY_MAX_OPTION, ETSY_MAX_SKU, ETSY_MAX_TAG_LENGTH, ETSY_MAX_TAGS,
                             ETSY_MAX_TITLE, IMAGE_VARIANTS, PERSONALIZATION_HEADER, ListingError, build_csv,
                             escape_field, groups_of, image_files, listing_sku, load_listings, problems,
                             render_title, sanitize_tag, tags_for, variation_sku)


@pytest.fixture(scope="module")
def cat():
    return load_catalog(REPO / "config")


@pytest.fixture()
def cfg(cat):
    c = load_listings(REPO / "config")
    c["prices"] = {pid: f"{10 + i}.50" for i, pid in enumerate(cat.packs)}
    c["shop_name"] = "Test Shop"
    return c


def rows_of(text):
    assert text.startswith("﻿") and "\r" not in text
    return list(csv.reader(io.StringIO(text[1:], newline="")))


def test_seed_groups_cover_every_design_once(cat):
    cfg = load_listings(REPO / "config")
    seen = [d for g in groups_of(cfg) for d in g.designs]
    assert sorted(seen) == sorted(cat.designs) and len(seen) == len(set(seen))
    assert 6 <= len(cfg["groups"]) <= 15
    # only the prices and the image address are left for the shop to fill in
    msgs = problems(cfg, cat, cfg["asset_base_url"])
    assert all(m.startswith(("Set the price", "Set where the listing images")) for m in msgs)
    assert len(msgs) == len(cat.packs) + 1
    assert "Ollie" not in str(cfg) and cfg["asset_base_url"] == ""
    assert cfg["shop_name"] == "Mazie Page Creations" and cfg["ship_time"] == "[X] business days"
    assert list(cfg["pack_short"]) == list(cat.packs) == list(cfg["pack_code"]) == list(cfg["prices"])
    assert cfg["pack_short"]["daycare"] == "Daycare (121)" and cfg["pack_code"]["tag102"] == "TAG102"
    text = json.dumps(cfg, ensure_ascii=False).lower()
    assert "half sheet" not in text and "letter envelope" not in text and "#10 envelope" in text


def test_problems(cfg, cat):
    assert problems(cfg, cat) == []
    bad = copy.deepcopy(cfg)
    bad["groups"][0]["designs"].append(bad["groups"][1]["designs"][0])
    bad["groups"][1]["designs"].pop()
    bad["groups"][2]["designs"].append("nope")
    bad["prices"][next(iter(cat.packs))] = "12,50"
    msgs = " ".join(problems(bad, cat))
    assert "is in two listings" in msgs and "unknown design 'nope'" in msgs and "must look like 12.50" in msgs
    assert "are in no listing" in msgs
    with pytest.raises(ListingError):
        build_csv(bad, cat, "https://x")
    with pytest.raises(ListingError, match="hosted"):
        build_csv(cfg, cat, "")
    with pytest.raises(ListingError, match="shop name"):
        build_csv({**cfg, "shop_name": ""}, cat, "https://x")


def test_csv_matches_the_binder_format(cfg, cat):
    text = build_csv(cfg, cat, "https://assets.example.com/")
    rows = rows_of(text)
    assert rows[0] == CSV_HEADER + PERSONALIZATION_HEADER and len(rows[0]) == 40
    assert len(rows) == 1 + len(cfg["groups"])
    packs = list(cat.packs)
    for g, row in zip(groups_of(cfg), rows[1:]):
        r = dict(zip(rows[0], row))
        assert len(row) == 40
        assert r["sku"] == listing_sku(cfg, g) and len(r["title"]) <= ETSY_MAX_TITLE
        assert r["price"] == min((cfg["prices"][p] for p in packs), key=float)
        assert r["variation_name"] == "Bundle" and r["variation2_name"] == "Design"
        assert r["variation_values"].split("|") == [cfg["pack_short"][p] for p in packs]
        assert r["variation_prices"].split("|") == [cfg["prices"][p] for p in packs]
        assert r["variation_skus"].split("|") == [variation_sku(cfg, g, p) for p in packs]
        assert len(r["variation_quantities"].split("|")) == len(packs)
        assert r["variation2_values"].split("|") == [cat.designs[d].name for d in g.designs]
        assert all(len(v) <= ETSY_MAX_OPTION for v in r["variation_values"].split("|") + r["variation2_values"].split("|"))
        urls = r["image_urls"].split(",")
        assert urls[0].startswith("https://assets.example.com/Labels_") and len(urls) == len(IMAGE_VARIANTS)
        assert len(r["image_alts"].split("|")) == len(urls)
        assert all(n in r["description"] for n in (cat.designs[d].name for d in g.designs))
        assert "Test Shop © " in r["description"]
        assert r["is_personalizable"] == "TRUE" and "font" in r["personalization_instructions"]
        assert r["who_made"] == "i_did" and r["when_made"] == "made_to_order" and r["item_weight_unit"] == "kg"
    # the shared font chart is the same file in every listing
    fonts = {u for row in rows[1:] for u in dict(zip(rows[0], row))["image_urls"].split(",") if "Fonts" in u}
    assert fonts == {"https://assets.example.com/Labels_Fonts.png"}


def test_csv_quotes_only_when_needed():
    assert escape_field("plain text") == "plain text"
    assert escape_field("a,b") == '"a,b"'
    assert escape_field('say "hi"') == '"say ""hi"""'
    assert escape_field("two\nlines") == '"two\nlines"'


def test_tags_titles_and_skus(cfg, cat):
    assert sanitize_tag("Kids' name labels!!") == "Kids' name labels"
    assert sanitize_tag("waterproof dishwasher safe labels") == "waterproof"     # cut at a word boundary
    for g in groups_of(cfg):
        tags = tags_for(cfg, g)
        assert 1 <= len(tags) <= ETSY_MAX_TAGS and all(len(t) <= ETSY_MAX_TAG_LENGTH for t in tags)
        assert len({t.lower() for t in tags}) == len(tags)
        assert len(render_title(cfg, g)) <= ETSY_MAX_TITLE
        assert all(len(variation_sku(cfg, g, p)) <= ETSY_MAX_SKU for p in cat.packs)


def test_validate_refuses_bad_edits(cfg, cat):
    ok = validate(cfg, {"prices": {"pencil-60": 9}}, cat)
    assert ok["prices"]["pencil-60"] == "9"
    for body, msg in (
        ({"groups": [{**cfg["groups"][0], "code": "bad code"}]}, "SKU code"),
        ({"groups": [cfg["groups"][0], cfg["groups"][0]]}, "Two listings"),
        ({"title_template": "{nope} labels"}, "unknown placeholder {nope}"),
        ({"description_template": "100% {"}, "could not be filled in"),
        ({"asset_base_url": "ftp://x"}, "https://"),
    ):
        with pytest.raises(ValueError, match=msg):
            validate(cfg, body, cat)


def test_listing_images_smoke(ws):
    cfg = load_listings(REPO / "config")
    cfg["image_size"] = 600
    g = groups_of(cfg)[-1]
    li = ListingImages(ws.renderer, ws.ui, cfg, ws.texts)
    for variant, _, _ in IMAGE_VARIANTS:
        img = li.image(variant, g)
        assert img.size == (600, 600) and img.mode == "RGB"
        assert len(img.resize((40, 40)).getcolors(1600)) > 20, variant     # not a blank page
    with pytest.raises(ValueError):
        li.image("Nope", g)


def test_sigv4_matches_the_aws_example():
    # AWS Signature V4 docs, "GET Object" example (S3, us-east-1)
    h = sign_v4("GET", "examplebucket.s3.amazonaws.com", "/test.txt", {"range": "bytes=0-9"},
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "us-east-1",
                dt.datetime(2013, 5, 24, tzinfo=dt.timezone.utc))
    assert h["authorization"].endswith("Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")


def test_r2_config_from_env():
    assert R2Config.from_env({}) is None
    env = {"R2_ACCOUNT_ID": "acc", "R2_ACCESS_KEY_ID": "k", "R2_SECRET_ACCESS_KEY": "s", "R2_BUCKET": "b",
           "R2_PUBLIC_BASE_URL": "https://assets.example.com/"}
    c = R2Config.from_env(env)
    assert c.endpoint == "https://acc.r2.cloudflarestorage.com" and c.public_url("A B.png") == "https://assets.example.com/A%20B.png"


# ------------------------------------------------------------------ API
@pytest.fixture(scope="module")
def client(tmp_path_factory):
    d = tmp_path_factory.mktemp("listings-app")
    st = Settings(data_dir=d, database_url=f"sqlite:///{d}/app.db", storage="local", api_secret=None,
                  config_dir=REPO / "config", frontend_dist=d / "no-dist")
    return TestClient(create_app(st, start_font_download=False))


def wait(client, timeout=30):
    end = time.time() + timeout
    job = client.get("/api/listings/job").json()
    while job["status"] == "running" and time.time() < end:
        time.sleep(0.05)
        job = client.get("/api/listings/job").json()
    return job


def test_api_listings_flow(client, cat, monkeypatch):
    st = client.get("/api/listings").json()
    assert st["unassigned"] == [] and st["r2"]["configured"] is False
    assert st["asset_base"] == "" and st["cfg"]["shop_name"] == "Mazie Page Creations"
    assert any(p.startswith("Set the price") for p in st["problems"])
    assert any("hosted" in p for p in st["problems"])
    r = client.get("/api/listings/csv")
    assert r.status_code == 400 and "not ready" in r.json()["detail"]

    cfg = st["cfg"]
    cfg["prices"] = {pid: "14.95" for pid in cat.packs}
    cfg.update(shop_name="Test Shop", asset_base_url="https://images.example.com", ship_time=" 3-5 business days ")
    st = client.put("/api/listings", json=cfg).json()
    assert st["problems"] == [] and st["asset_base"] == "https://images.example.com"
    assert st["cfg"]["ship_time"] == "3-5 business days"
    assert client.put("/api/listings", json={**cfg, "ship_time": "x" * 41}).status_code == 400
    assert client.put("/api/listings", json={"groups": "x"}).status_code == 400
    r = client.get("/api/listings/csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert len(rows_of(r.content.decode("utf-8"))) == 1 + len(cfg["groups"])
    one = cfg["groups"][0]["id"]
    assert len(rows_of(client.get(f"/api/listings/csv?groups={one}").content.decode())) == 2

    # images job: rendering is stubbed here (test_listing_images_smoke covers it), R2 uploads are recorded
    from app import listings_service as ls
    sent = []
    png = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(png, "PNG")
    monkeypatch.setattr(ls.Listings, "_render", lambda self, cfg, g, v: png.getvalue())
    monkeypatch.setattr(ls, "put_object", lambda c, key, data: sent.append(key) or c.public_url(key))
    monkeypatch.setattr(ls, "purge_cdn", lambda c, urls: True)
    client.app.state.listings.env = {"R2_ACCOUNT_ID": "a", "R2_ACCESS_KEY_ID": "k", "R2_SECRET_ACCESS_KEY": "s",
                                     "R2_BUCKET": "b", "R2_PUBLIC_BASE_URL": "https://cdn.example.com",
                                     "CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ZONE_ID": "z"}
    r = client.post("/api/listings/images", json={"groups": [one]})
    assert r.status_code == 202
    job = wait(client)
    files = [f for f, _ in image_files(cfg, groups_of(cfg)[0])]
    assert job["status"] == "done" and job["errors"] == [] and job["purged"] is True
    assert sorted(sent) == sorted(files) and job["uploaded"] == len(files)
    st = client.get("/api/listings").json()
    imgs = st["groups"][0]["images"]
    assert all(i["generated_at"] and i["url"].startswith("https://cdn.example.com/") for i in imgs)
    assert st["asset_base"] == "https://cdn.example.com"
    assert "https://cdn.example.com/Labels_" in client.get("/api/listings/csv").text
    assert client.get(f"/api/listings/images/{files[0]}").content == png.getvalue()
    assert client.get(f"/api/listings/images/{files[0]}?w=100").headers["content-type"] == "image/jpeg"
    assert client.get("/api/listings/images/..%2Fapp.db").status_code == 404
    z = zipfile.ZipFile(io.BytesIO(client.get("/api/listings/images.zip").content))
    assert set(z.namelist()) == {f"images/{f}" for f in files} | {"etsy_import_labels.csv"}

    # upload again without rendering; listings without images are reported, not fatal
    sent.clear()
    client.post("/api/listings/images", json={"upload_only": True})
    job = wait(client)
    assert job["status"] == "done" and len(sent) == len(files)
    assert any("not generated yet" in e for e in job["errors"])
    client.app.state.listings.env = {}
    assert client.post("/api/listings/images", json={"upload_only": True}).status_code == 400


def test_seeded_listings_lose_the_other_business(tmp_path):
    """A database seeded with the first listings.json gets the other shop's name and image host removed."""
    from app.db import Setting
    st = Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path}/a.db", storage="local", api_secret=None,
                  config_dir=REPO / "config", frontend_dist=tmp_path)
    repo = create_app(st, start_font_download=False).state.repo
    old = dict(repo.setting("listings"))
    old.pop("shop_name")
    old["asset_base_url"] = "https://assets.olliepagecreations.com"
    old["description_template"] = ("At Ollie Page Creations, we prepay all U.S. duties.\n"
                                   "• Labels arrive on half sheets that fit flat in a letter envelope\n"
                                   "Ollie Page Creations © 2026. All rights reserved.")
    with repo.Session() as s:
        s.get(Setting, "listings").value = old
        s.commit()
    repo.ensure_defaults(REPO / "config")
    new = repo.setting("listings")
    assert new["asset_base_url"] == "" and new["shop_name"] == ""
    assert new["description_template"] == "We prepay all U.S. duties.\n{shop_name} © 2026. All rights reserved."
