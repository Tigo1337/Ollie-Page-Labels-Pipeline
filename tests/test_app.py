"""API tests: auth, design library, bulk import, previews, quick make, plain errors."""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import REPO, Settings
from engine.assets import font_dir_name
from engine.render import LabelSpec
from engine.testart import make_square, make_wide


@pytest.fixture(scope="module")
def client(tmp_path_factory, fonts_dir):
    d = tmp_path_factory.mktemp("app")
    st = Settings(data_dir=d, database_url=f"sqlite:///{d}/app.db", storage="local", api_secret="s3cret",
                  config_dir=REPO / "config", frontend_dist=d / "no-dist")
    app = create_app(st, start_font_download=False)
    for f in app.state.svc.catalog.fonts.values():  # install fonts without the network
        for x in (fonts_dir / font_dir_name(f)).iterdir():
            app.state.store.put(f"fonts/{font_dir_name(f)}/{x.name}", x.read_bytes())
    c = TestClient(app)
    assert c.post("/api/login", json={"secret": "s3cret"}).json() == {"ok": True}
    return c


def art_zip(designs, cat, extra=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for did in designs:
            for src, fn in (("wide", make_wide), ("square", make_square)):
                b = io.BytesIO()
                fn(cat.designs[did]).save(b, "JPEG", quality=90)
                z.writestr(f"Label Designs\\{did}\\{did}_{src}.jpg", b.getvalue())
        for name, data in extra:
            z.writestr(name, data)
    return buf.getvalue()


def test_requires_secret(tmp_path):
    st = Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path}/a.db", storage="local",
                  api_secret="x", config_dir=REPO / "config", frontend_dist=tmp_path)
    c = TestClient(create_app(st, start_font_download=False))
    assert c.get("/api/designs").status_code == 401
    assert c.get("/api/health").status_code == 200
    assert c.post("/api/login", json={"secret": "nope"}).status_code == 401
    assert c.get("/api/designs", headers={"x-api-key": "x"}).status_code == 200


def test_seeded_catalog(client):
    cat = client.get("/api/catalog").json()
    assert [s["id"] for s in cat["sizes"]] == ["mini", "small", "medium", "large", "round", "square"]
    school = next(p for p in cat["packs"] if p["id"] == "school")
    assert school["total"] == 132 and school["sheets"] == 3
    assert len(client.get("/api/designs").json()) == 20


def test_bulk_import_and_trim(client):
    cat = client.app.state.svc.catalog
    data = art_zip(["axolotl", "dino"], cat, extra=[("Label Designs/turtle/turtle_wide.jpg", b"x"),
                                                    ("Label Designs/dino/notes.png", b"x")])
    rep = client.post("/api/designs/import-zip", files={"file": ("a.zip", data, "application/zip")}).json()
    assert len(rep["imported"]) == 4
    assert rep["unknown_folders"] == ["turtle"]
    d = client.get("/api/designs/axolotl").json()
    assert d["art"]["wide_size"] == [2752, 688 - 8] and d["art"]["square_size"] == [2048, 2048]
    orig = client.get("/api/designs/axolotl/art/wide?variant=original")
    assert orig.status_code == 200 and orig.headers["content-type"] == "image/jpeg"


def test_upload_rejects_wrong_images(client):
    sq = io.BytesIO()
    make_square(client.app.state.svc.catalog.designs["fox"]).save(sq, "PNG")
    r = client.post("/api/designs/fox/art/wide", files={"file": ("fox_square.png", sq.getvalue(), "image/png")})
    assert r.status_code == 400 and "not a wide strip" in r.json()["detail"]
    r = client.post("/api/designs/fox/art/square", files={"file": ("x.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 400 and "not an image" in r.json()["detail"]


def test_design_settings_change_the_render(client):
    a = client.post("/api/preview", json={"design": "dino", "size": "medium", "name": "Léo"}).json()
    r = client.patch("/api/designs/dino", json={"cap_frac": 0.3})
    assert r.status_code == 200 and r.json()["cap_frac"] == 0.3
    b = client.post("/api/preview", json={"design": "dino", "size": "medium", "name": "Léo"}).json()
    assert b["cap_mm"][0] < a["cap_mm"][0]
    assert client.patch("/api/designs/dino", json={"fill": "blue"}).status_code == 400
    assert client.patch("/api/designs/dino", json={"cap_frac": 0.52}).status_code == 200


def test_review_sheet_png(client):
    r = client.get("/api/designs/axolotl/review.png?font=3")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_plain_errors(client):
    r = client.post("/api/preview", json={"design": "bee", "size": "mini", "name": "Léo"})
    assert r.status_code == 400 and "no wide artwork" in r.json()["detail"]
    r = client.post("/api/make", json={"design": "dino", "pack": "nope", "finish": "matte", "name": "A"})
    assert r.status_code == 400 and "Unknown pack" in r.json()["detail"]
    r = client.get("/api/check-name", params={"name": "Nguyễn", "font": 1}).json()
    assert not r["ok"] and 2 in [f["id"] for f in r["alternatives"]]
    assert client.get("/api/designs/nope").status_code == 404


def test_make_labels_end_to_end(client):
    data = art_zip(["axolotl"], client.app.state.svc.catalog)
    client.post("/api/designs/import-zip", files={"file": ("a.zip", data, "application/zip")})
    r = client.post("/api/make", json={"design": "axolotl", "pack": "starter", "finish": "gloss",
                                       "name": "Émilie-Rose", "font": 3, "order_id": "1234"})
    assert r.status_code == 200, r.text
    run = r.json()
    kinds = {f["kind"] for f in run["files"]}
    assert {"print", "cut", "page-proof", "customer-proof", "notch", "info", "zip"} <= kinds
    z = next(f["name"] for f in run["files"] if f["kind"] == "zip")
    got = client.get(f"/api/runs/{run['id']}/files/{z}")
    assert got.status_code == 200 and zipfile.ZipFile(io.BytesIO(got.content)).namelist()
    assert client.get("/api/runs").json()[0]["id"] == run["id"]
    r = client.post("/api/make", json={"design": "axolotl", "pack": "mini60", "finish": "matte",
                                       "name": "Émilie", "font": 1})
    assert r.status_code == 200
    names = [f["name"] for f in r.json()["files"]]
    assert all(n.isascii() for n in names)


def test_crop_presets_are_saved_and_used_by_orders(client):
    data = art_zip(["shark"], client.app.state.svc.catalog)
    client.post("/api/designs/import-zip", files={"file": ("a.zip", data, "application/zip")})
    r = client.get("/api/designs/shark/presets").json()
    large = next(s for s in r["sizes"] if s["size"] == "large")
    assert large["is_auto"] and large["preset"] == large["auto"] and r["art"]["wide"] == [2752, 680]

    before = client.post("/api/preview", json={"design": "shark", "size": "large", "name": "Léo"}).json()
    preset = {"source": "wide", "center": [0.6, 0.5], "height": 0.6, "text": [0.35, 0.15, 0.95, 0.85]}
    assert client.put("/api/designs/shark/presets/large", json=preset).status_code == 200
    after = client.post("/api/preview", json={"design": "shark", "size": "large", "name": "Léo"}).json()
    assert after["preset"] == preset and not after["preset_is_auto"] and after["image"] != before["image"]

    # the saved crop is what an order prints
    run = client.post("/api/make", json={"design": "shark", "pack": "large14", "name": "Léo", "font": 1}).json()
    assert run["request"]["finish"] == "matte"  # shop default
    lab = client.app.state.svc.renderer.render(LabelSpec("shark", "large", "Léo", "", 1, "matte"))
    assert lab.preset.to_dict() == preset

    # copy to every rectangular size; round/square untouched
    assert client.post("/api/designs/shark/presets/large/copy-to-rect").json()["copied_to"] == ["mini", "small", "medium"]
    sizes = {s["size"]: s for s in client.get("/api/designs/shark/presets").json()["sizes"]}
    assert all(not sizes[s]["is_auto"] for s in ("mini", "small", "medium", "large"))
    assert sizes["round"]["is_auto"] and sizes["square"]["is_auto"]

    # reset goes back to automatic
    assert client.delete("/api/designs/shark/presets/mini").status_code == 200
    assert client.get("/api/designs/shark/presets").json()["sizes"][0]["is_auto"]


def test_bad_presets_are_refused_plainly(client):
    bad = {"source": "wide", "center": [0.5, 0.5], "height": 0.6, "text": [0.9, 0.1, 0.2, 0.9]}
    r = client.put("/api/designs/shark/presets/small", json=bad)
    assert r.status_code == 400 and "name box" in r.json()["detail"]
    r = client.put("/api/designs/bunny/presets/small", json={**bad, "text": [0.3, 0.1, 0.9, 0.9]})
    assert r.status_code == 400 and "no wide artwork" in r.json()["detail"]
    r = client.put("/api/designs/shark/presets/small", json={"source": "wide"})
    assert r.status_code == 400


def test_shop_default_finish(client):
    assert client.get("/api/shop").json() == {"default_finish": "matte"}
    assert client.patch("/api/shop", json={"default_finish": "gloss"}).json()["default_finish"] == "gloss"
    data = art_zip(["bee"], client.app.state.svc.catalog)
    client.post("/api/designs/import-zip", files={"file": ("a.zip", data, "application/zip")})
    run = client.post("/api/make", json={"design": "bee", "pack": "mini60", "name": "Zoë", "font": 1}).json()
    assert "gloss" in run["summary"]["finishes"]
    assert any(f["kind"] == "notch" for f in run["files"])
    assert client.patch("/api/shop", json={"default_finish": "shiny"}).status_code == 400
    client.patch("/api/shop", json={"default_finish": "matte"})
