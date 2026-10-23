"""Orders: Etsy CSV parsing, the Orders API (import, edit, review, status) and batches made in the app."""
import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import REPO, Settings
from engine.assets import font_dir_name
from engine.config import load_catalog
from engine.etsy_orders import OrdersCsvError, parse_orders_csv, parse_personalization, split_variations
from engine.listings import load_listings

from .test_app import art_zip, import_and_wait

CAT = load_catalog(REPO / "config")
CFG = load_listings(REPO / "config")
HEADER = ("Sale Date,Item Name,Buyer,Quantity,Price,Coupon Code,Coupon Details,Discount Amount,Shipping Discount,"
          "Order Shipping,Order Sales Tax,Item Total,Currency,Transaction ID,Listing ID,Date Paid,Date Shipped,"
          "Ship Name,Ship Address1,Ship Address2,Ship City,Ship State,Ship Zipcode,Ship Country,Order ID,Variations,"
          "Order Type,Listings Type,Payment Type,InPerson Discount,InPerson Location,VAT Paid by Buyer,SKU")


def etsy_row(order, tx, variations, sku, qty=1, name="Julie Tremblay", state="QC", country="Canada",
             item="Dinosaur & Fantasy Name Labels"):
    cells = ["10/20/2026", item, "julie", str(qty), "24.00", "", "", "0", "0", "4.00", "0", "24.00", "CAD", tx,
             "111", "10/20/2026", "", name, "1 rue X", "", "Québec", state, "G1A 1A1", country, order, variations,
             "online", "listing", "online_cc", "", "", "0", sku]
    return ",".join('"' + c.replace('"', '""') + '"' for c in cells)


def etsy_csv(*rows):
    return "﻿" + HEADER + "\n" + "\n".join(rows) + "\n"


# ---------------------------------------------------------------- parsing
@pytest.mark.parametrize("text,want,flags", [
    ("Emma Tremblay - font 3", ("Emma Tremblay", "", 3), 0),
    ("Léo, font 12", ("Léo", "", 12), 0),
    ("Zoé\nGagnon\nfont 4", ("Zoé", "Gagnon", 4), 0),
    ("Olivia / Roy - Font #2", ("Olivia", "Roy", 2), 0),
    ("font 3: Charlotte-Anne", ("Charlotte-Anne", "", 3), 0),
    ("Ava (police 5)", ("Ava", "", 5), 0),
    ("Liam - fonte 6", ("Liam", "", 6), 0),
    ("Maximilien 7", ("Maximilien", "", 7), 0),
    ("Noah", ("Noah", "", 1), 1),                       # no font: assumed 1, flagged
    ("Emma - 25", ("Emma", "", 25), 1),                 # no such font: flagged
    ("", ("", "", 1), 2),
    ("A\nB\nC\nfont 2", ("A", "B", 2), 1),              # three lines: flagged
])
def test_personalization(text, want, flags):
    got, problems = parse_personalization(text, CAT)
    assert (got["name"], got["line2"], got["font"]) == want
    assert len(problems) == flags, problems


def test_variations_keep_commas_inside_values():
    v = split_variations("Bundle:Starter (73),Design:Dino Stomp,Personalization:Léo, Tremblay, font 3",
                         ["Bundle", "Design", "Personalization"])
    assert v == {"bundle": "Starter (73)", "design": "Dino Stomp", "personalization": "Léo, Tremblay, font 3"}
    assert split_variations("", ["Bundle"]) == {}
    assert split_variations("Design:Moon &amp; Stars", ["Design"]) == {"design": "Moon & Stars"}


def test_etsy_csv_is_read_into_orders():
    text = etsy_csv(
        etsy_row("3301", "9001", "Bundle:Starter (73),Design:Dino Stomp,Personalization:Léo Tremblay, font 3",
                 "LBL-DINO-START"),
        etsy_row("3301", "9002", "Bundle:51 Skinny,Design:Little Dragon,Personalization:Zoé - 4", "LBL-DINO-PEN51",
                 qty=2),
        etsy_row("3302", "9003", "", "", item="Gift card"),
        etsy_row("3303", "9004", "Bundle:Back to School,Design:Unknown Thing,Personalization:Amy", "LBL-DINO-SCHL",
                 name="Amy Lee", state="CA", country="United States"),
        etsy_row("3304", "9005", "Personalization:Noé font 2", "fox-round30-gloss"),     # an old SKU
    )
    res = parse_orders_csv(text, CFG, CAT)
    assert res.rows == 5 and [o["id"] for o in res.orders] == ["3301", "3303", "3304"]
    assert len(res.skipped) == 1 and "Gift card" in res.skipped[0]
    o1 = res.orders[0]
    assert o1["customer"] == "Julie Tremblay" and o1["lang"] == "fr" and o1["transactions"] == ["9001", "9002"]
    assert [(ln["design"], ln["pack"], ln["name"], ln["font"], ln["review"]) for ln in o1["lines"]] == [
        ("dino", "starter", "Léo Tremblay", 3, []), ("dragon", "pencil51", "Zoé", 4, []),
        ("dragon", "pencil51", "Zoé", 4, [])]                                       # quantity 2 = two lines
    o3 = res.orders[1]
    assert o3["lang"] == "en" and o3["lines"][0]["design"] == ""
    assert any("unknown design" in r for r in o3["lines"][0]["review"])
    o4 = res.orders[2]
    assert (o4["lines"][0]["design"], o4["lines"][0]["pack"], o4["lines"][0]["finish"]) == ("fox", "round30", "matte")
    assert any("'gloss'" in r for r in o4["lines"][0]["review"])


def test_wrong_files_are_refused_plainly():
    with pytest.raises(OrdersCsvError, match="Sold Orders file"):
        parse_orders_csv("Sale Date,Order ID,Number of Items\n1,2,3\n", CFG, CAT)
    with pytest.raises(OrdersCsvError, match="does not look like"):
        parse_orders_csv("a,b\n1,2\n", CFG, CAT)
    with pytest.raises(OrdersCsvError, match="empty"):
        parse_orders_csv("", CFG, CAT)


# ---------------------------------------------------------------- the app
@pytest.fixture(scope="module")
def client(tmp_path_factory, fonts_dir):
    d = tmp_path_factory.mktemp("orders-app")
    st = Settings(data_dir=d, database_url=f"sqlite:///{d}/app.db", storage="local", api_secret=None,
                  config_dir=REPO / "config", frontend_dist=d / "no-dist")
    app = create_app(st, start_font_download=False)
    for f in app.state.svc.catalog.fonts.values():
        for x in (fonts_dir / font_dir_name(f)).iterdir():
            app.state.store.put(f"fonts/{font_dir_name(f)}/{x.name}", x.read_bytes())
    c = TestClient(app)
    import_and_wait(c, art_zip(["dino", "dragon", "fox", "narwhal"], app.state.svc.catalog))
    return c


def wait_job(client, job, timeout=120):
    end = time.time() + timeout
    while job["status"] == "running" and time.time() < end:
        time.sleep(0.1)
        job = client.get(f"/api/orders/batch/{job['id']}").json()
    return job


def test_import_review_edit_and_status(client):
    text = etsy_csv(
        etsy_row("5001", "1", "Bundle:Starter (73),Design:Dino Stomp,Personalization:Léo, font 3", "LBL-DINO-START"),
        etsy_row("5002", "2", "Bundle:Starter (73),Design:Little Dragon,Personalization:Noah", "LBL-DINO-START"),
        etsy_row("5003", "3", "", "", item="Gift card"))
    r = client.post("/api/orders/import", files={"file": ("EtsySoldOrderItems.csv", text.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["added"] == ["5001", "5002"] and rep["to_check"] == 1 and len(rep["skipped"]) == 1
    again = client.post("/api/orders/import", files={"file": ("x.csv", text.encode(), "text/csv")}).json()
    assert again["added"] == [] and again["already_imported"] == ["5001", "5002"]          # never twice
    bad = client.post("/api/orders/import", files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")})
    assert bad.status_code == 400 and "does not look like" in bad.json()["detail"]

    orders = {o["id"]: o for o in client.get("/api/orders?status=new").json()["orders"]}
    assert orders["5001"]["ready"] and not orders["5002"]["ready"]
    assert orders["5002"]["lines"][0]["review"] and orders["5002"]["lines"][0]["font"] == 1
    # an order with a line to check cannot be made
    r = client.post("/api/orders/plan", json={"orders": ["5001", "5002"]})
    assert r.status_code == 400 and "Order 5002, line 1: to check" in r.json()["detail"]
    # fix it in the app: font 2, checked
    line = {**orders["5002"]["lines"][0], "font": 2, "review": []}
    fixed = client.patch("/api/orders/5002", json={"lines": [line], "notes": "font asked by message"}).json()
    assert fixed["ready"] and fixed["lines"][0]["font"] == 2 and fixed["notes"] == "font asked by message"
    # a character the font does not have is a problem, not a crash
    bad_line = {**line, "name": "Nguyễn", "font": 1}
    r = client.patch("/api/orders/5002", json={"lines": [bad_line]}).json()
    assert not r["ready"] and any("glyph" in p for p in r["lines"][0]["problems"])
    client.patch("/api/orders/5002", json={"lines": [line]})
    assert client.patch("/api/orders/5002", json={"lines": []}).status_code == 400
    assert client.patch("/api/orders/5002", json={"status": "lost"}).status_code == 400
    assert client.patch("/api/orders/nope", json={"notes": ""}).status_code == 404

    # manual orders
    m = client.post("/api/orders", json={"id": "M-1", "customer": "Ann", "lang": "fr", "lines": [
        {"design": "fox", "pack": "round30", "name": "Zoé", "font": 3}]}).json()
    assert m["ready"] and m["lang"] == "fr" and m["source"] == "manual"
    assert client.post("/api/orders", json={"id": "M-1", "lines": [{"design": "fox"}]}).status_code == 400
    assert client.post("/api/orders", json={"id": "bad id!", "lines": [{"design": "fox"}]}).status_code == 400
    assert client.post("/api/orders", json={"lines": []}).status_code == 400
    unknown = client.post("/api/orders", json={"lines": [{"design": "nope", "pack": "x", "name": "A"}]}).json()
    assert not unknown["ready"] and any("Unknown design" in p for p in unknown["lines"][0]["problems"])
    assert client.delete(f"/api/orders/{unknown['id']}").json() == {"ok": True}


def test_batch_plan_and_make(client):
    for oid, design, name in (("6001", "dino", "Anna"), ("6002", "narwhal", "Ben"), ("6003", "dino", "Cleo")):
        client.post("/api/orders", json={"id": oid, "customer": f"C{oid}", "lines": [
            {"design": design, "pack": "starter", "name": name, "font": 1}]})
    plan = client.post("/api/orders/plan", json={"orders": ["6003", "6001", "6002"]}).json()
    # three starter orders: 5 sheets batched (pencil 1, small 2, medium 1, round 1), 12 printed one by one
    assert plan["sheets"] == 5 and plan["sheets_alone"] == 12 and plan["bonus"] == 0
    assert plan["sheets_by_size"] == {"pencil": 1, "small": 2, "medium": 1, "round": 1}
    assert plan["orders"] == ["6001", "6002", "6003"]                                      # oldest first
    assert all(e["lettermail"] == "Lettermail, 30–50 g" for e in plan["envelopes"])
    alone = client.post("/api/orders/plan", json={"orders": ["6001"], "unpaired": "blank"}).json()
    assert alone["sheets"] == 4 and alone["bonus"] == 0 and alone["blank"] == 7

    r = client.post("/api/orders/batch", json={"orders": ["6001", "6002", "6003"]})
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json())
    assert job["status"] == "done", job
    run = job["run"]
    assert len(run["summary"]["sheets"]) == 5 and run["summary"]["orders"] == ["6001", "6002", "6003"]
    kinds = {f["kind"] for f in run["files"]}
    assert {"print", "guide", "slip", "info", "customer-proof", "zip"} <= kinds
    assert sum(1 for f in run["files"] if f["kind"] == "customer-proof") == 3
    z = next(f["name"] for f in run["files"] if f["kind"] == "zip")
    got = client.get(f"/api/runs/{run['id']}/files/{z}")
    assert any(n.endswith("_packing_guide.pdf") for n in zipfile.ZipFile(io.BytesIO(got.content)).namelist())
    orders = {o["id"]: o for o in client.get("/api/orders").json()["orders"]}
    assert all(orders[i]["status"] == "made" and orders[i]["runs"] == [run["id"]] for i in ("6001", "6002", "6003"))
    assert client.get("/api/runs").json()[0]["id"] == run["id"]           # it is a normal run (Make page)
    # status
    assert client.post("/api/orders/status", json={"orders": ["6001", "6002"], "status": "shipped"}).json() == {
        "changed": 2}
    assert {o["id"] for o in client.get("/api/orders?status=shipped").json()["orders"]} >= {"6001", "6002"}
    # a cancelled order cannot be made; a reprint of a made order can
    client.post("/api/orders/status", json={"orders": ["6003"], "status": "cancelled"})
    r = client.post("/api/orders/batch", json={"orders": ["6003"]})
    assert r.status_code == 400 and "cancelled" in r.json()["detail"]
    reprint = wait_job(client, client.post("/api/orders/batch", json={"orders": ["6002"]}).json())
    assert reprint["status"] == "done"
    o2 = next(o for o in client.get("/api/orders").json()["orders"] if o["id"] == "6002")
    assert o2["runs"] == [run["id"], reprint["run"]["id"]] and o2["status"] == "shipped"   # status kept
    assert client.post("/api/orders/batch", json={"orders": []}).status_code == 400
    assert client.get("/api/orders/batch/nope").status_code == 404


def test_the_make_page_still_works_on_its_own(client):
    """The quick Make page is unchanged: one order, no order row."""
    r = client.post("/api/make", json={"design": "fox", "pack": "round30", "name": "Zoé", "font": 3})
    assert r.status_code == 200, r.text
    assert not any(o["id"].startswith("quick") for o in client.get("/api/orders").json()["orders"])
