"""API tests: auth, design library, bulk import, previews, quick make, plain errors."""
import io
import json
import shutil
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import REPO, Settings
from app.templates_store import Templates
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


def import_and_wait(client, data: bytes, timeout: float = 60) -> dict:
    """Start a background ZIP import and wait for its report."""
    import time
    r = client.post("/api/designs/import-zip", files={"file": ("a.zip", data, "application/zip")})
    assert r.status_code == 202, r.text
    job = r.json()
    end = time.time() + timeout
    while job["status"] == "running" and time.time() < end:
        time.sleep(0.05)
        job = client.get(f"/api/designs/import-zip/{job['id']}").json()
    assert job["status"] == "done", job
    assert job["done"] == job["total"] == len(job["report"]["imported"]) + sum(
        1 for x in job["report"]["skipped"] if "no design matches" not in x["reason"]
        and "does not end" not in x["reason"] and "too large" not in x["reason"])
    return job["report"]


def test_import_job_errors_are_plain(client):
    import time
    r = client.post("/api/designs/import-zip", files={"file": ("x.zip", b"not a zip", "application/zip")})
    job = r.json()
    for _ in range(100):
        if job["status"] != "running":
            break
        time.sleep(0.05)
        job = client.get(f"/api/designs/import-zip/{job['id']}").json()
    assert job["status"] == "error" and job["error"] == "That file is not a ZIP archive."
    assert client.get("/api/designs/import-zip/latest").json()["id"] == job["id"]
    assert client.get("/api/designs/import-zip/nope").status_code == 404


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
    assert [s["id"] for s in cat["sizes"]] == ["pencil", "small", "medium", "large", "tag", "round", "shoe"]
    school = next(p for p in cat["packs"] if p["id"] == "school")
    assert (school["halves"], school["batched"], school["alone"]) == (5, 2.5, 5)
    assert school["halves_by_size"] == {"pencil": 1, "small": 1, "medium": 1, "round": 1, "shoe": 1}
    tag = next(s for s in cat["sizes"] if s["id"] == "tag")
    assert (tag["layout_id"], tag["per_half"], tag["per_sheet"]) == ("chels-tag-v1", 55, 110)
    designs = client.get("/api/designs").json()
    assert len(designs) == 100
    assert sorted(d["id"] for d in designs if d["presets"]) == ["airplane", "dino", "fire-truck", "moon-stars",
                                                                "mushrooms", "sakura", "tractor"]
    dino = next(d for d in designs if d["id"] == "dino")
    assert dino["mini_start"] == 0.24 and dino["no_character_sizes"] == ["tag"]


def test_bulk_import_and_trim(client):
    cat = client.app.state.svc.catalog
    data = art_zip(["axolotl", "dino"], cat, extra=[("Label Designs/zebra-x/zebra-x_wide.jpg", b"x"),
                                                    ("Label Designs/dino/notes.png", b"x"),
                                                    ("Label Designs\\dino\\test-labels\\dino_wide.png", b"x"),
                                                    ("Label Designs/dino/test-labels/sheet_pencil.png", b"x"),
                                                    ("Label Designs/dino/test-labels/old/dino_square.jpg", b"x")])
    rep = import_and_wait(client, data)
    assert len(rep["imported"]) == 4
    assert rep["unknown_folders"] == ["zebra-x"]
    assert rep["ignored"] == 3                     # everything under dino/test-labels/, quietly
    assert not any("test-labels" in x["file"] for x in rep["skipped"] + rep["imported"])
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
    r = client.post("/api/preview", json={"design": "bee", "size": "pencil", "name": "Léo"})
    assert r.status_code == 400 and "no wide artwork" in r.json()["detail"]
    r = client.post("/api/make", json={"design": "dino", "pack": "nope", "finish": "matte", "name": "A"})
    assert r.status_code == 400 and "Unknown pack" in r.json()["detail"]
    r = client.get("/api/check-name", params={"name": "Nguyễn", "font": 1}).json()
    assert not r["ok"] and 2 in [f["id"] for f in r["alternatives"]]
    assert client.get("/api/designs/nope").status_code == 404


def test_make_labels_end_to_end(client):
    data = art_zip(["axolotl"], client.app.state.svc.catalog)
    import_and_wait(client, data)
    r = client.post("/api/make", json={"design": "axolotl", "pack": "starter", "finish": "gloss",
                                       "name": "Émilie-Rose", "font": 3, "order_id": "1234"})
    assert r.status_code == 200, r.text
    run = r.json()
    kinds = {f["kind"] for f in run["files"]}
    assert {"print", "template", "page-proof", "customer-proof", "notch", "info", "slip", "zip"} <= kinds
    assert [sh["layout_id"] for sh in run["summary"]["sheets"]] == ["chels-pencil-v1", "chels-small-v1"]
    assert all(sh["bottom"]["bonus"] for sh in run["summary"]["sheets"])
    z = next(f["name"] for f in run["files"] if f["kind"] == "zip")
    got = client.get(f"/api/runs/{run['id']}/files/{z}")
    assert got.status_code == 200 and zipfile.ZipFile(io.BytesIO(got.content)).namelist()
    assert client.get("/api/runs").json()[0]["id"] == run["id"]
    r = client.post("/api/make", json={"design": "axolotl", "pack": "shoe8", "finish": "matte",
                                       "name": "Émilie", "font": 1, "unpaired": "blank"})
    assert r.status_code == 200
    assert r.json()["summary"]["sheets"][0]["bottom"] is None
    names = [f["name"] for f in r.json()["files"]]
    assert all(n.isascii() for n in names)


def test_crop_presets_are_saved_and_used_by_orders(client):
    data = art_zip(["shark"], client.app.state.svc.catalog)
    import_and_wait(client, data)
    r = client.get("/api/designs/shark/presets").json()
    large = next(s for s in r["sizes"] if s["size"] == "large")
    assert large["is_auto"] and large["preset"] == large["auto"] and r["art"]["wide"] == [2752, 680]

    before = client.post("/api/preview", json={"design": "shark", "size": "large", "name": "Léo"}).json()
    preset = {"source": "wide", "center": [0.6, 0.5], "height": 0.6, "text": [0.35, 0.15, 0.95, 0.85]}
    assert client.put("/api/designs/shark/presets/large", json=preset).status_code == 200
    after = client.post("/api/preview", json={"design": "shark", "size": "large", "name": "Léo"}).json()
    assert after["preset"] == preset and not after["preset_is_auto"] and after["image"] != before["image"]

    # the saved crop is what an order prints
    run = client.post("/api/make", json={"design": "shark", "pack": "large22", "name": "Léo", "font": 1}).json()
    assert run["request"]["finish"] == "matte"  # shop default
    lab = client.app.state.svc.renderer.render(LabelSpec("shark", "large", "Léo", "", 1, "matte"))
    assert lab.preset.to_dict() == preset

    # copy to every rectangular size; round/square untouched
    assert client.post("/api/designs/shark/presets/large/copy-to-rect").json()["copied_to"] == ["pencil", "small", "medium", "tag"]
    sizes = {s["size"]: s for s in client.get("/api/designs/shark/presets").json()["sizes"]}
    assert all(not sizes[s]["is_auto"] for s in ("pencil", "small", "medium", "large", "tag"))
    assert sizes["round"]["is_auto"] and sizes["shoe"]["is_auto"]

    # reset goes back to automatic
    assert client.delete("/api/designs/shark/presets/pencil").status_code == 200
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
    import_and_wait(client, data)
    run = client.post("/api/make", json={"design": "bee", "pack": "pencil60", "name": "Zoë", "font": 1}).json()
    assert "gloss" in run["summary"]["finishes"]
    assert any(f["kind"] == "notch" for f in run["files"])
    assert client.patch("/api/shop", json={"default_finish": "shiny"}).status_code == 400
    client.patch("/api/shop", json={"default_finish": "matte"})


# ---------------------------------------------------------------- templates
def test_templates_page_files_and_studio3(client, tmp_path):
    data = client.get("/api/templates").json()
    ids = [row["layout_id"] for row in data["layouts"]]
    assert ids == [f"chels-{s}-v1" for s in ("pencil", "small", "medium", "large", "tag", "round", "shoe")]
    assert data["outdated"] == [] and all(row["studio3"] is None for row in data["layouts"])
    assert client.get("/api/templates/chels-round-v1/preview.png").headers["content-type"] == "image/png"
    svg = client.get("/api/templates/chels-round-v1/files/svg")
    assert svg.status_code == 200 and svg.text.count("<circle") == 40
    assert (REPO / "templates" / "chels-round-v1.svg").read_text() == svg.text
    dxf = client.get("/api/templates/chels-shoe-v1/files/dxf")
    assert "attachment" in dxf.headers["content-disposition"] and "ANCHOR" in dxf.text
    assert client.get("/api/templates/chels-tag-v1/files/calibration.pdf").content.startswith(b"%PDF")
    assert client.get("/api/templates/chels-mini-v1/files/svg").status_code == 404
    assert client.get("/api/templates/chels-tag-v1/files/exe").status_code == 404

    # .studio3 upload: stored with the geometry hash, current until the geometry changes
    r = client.post("/api/templates/chels-small-v1/studio3", files={"file": ("x.png", b"nope")})
    assert r.status_code == 400 and ".studio3" in r.json()["detail"]
    r = client.post("/api/templates/chels-small-v1/studio3", files={"file": ("chels-small-v1.studio3", b"STUDIO")})
    assert r.status_code == 200 and r.json()["current"] is True
    row = next(x for x in client.get("/api/templates").json()["layouts"] if x["layout_id"] == "chels-small-v1")
    assert row["studio3"]["current"] and row["studio3"]["geometry_hash"] == row["geometry_hash"]
    assert client.get("/api/templates/chels-small-v1/studio3").content == b"STUDIO"
    t: Templates = client.app.state.templates
    assert t.current_studio3_bytes("chels-small-v1") == b"STUDIO"

    # sheet.json changes (no new layout yet): the upload is outdated and never bundled
    cfg = tmp_path / "config"
    shutil.copytree(REPO / "config", cfg)
    sheet = json.loads((cfg / "sheet.json").read_text())
    sheet["edge_margin"] = 10.5
    (cfg / "sheet.json").write_text(json.dumps(sheet))
    changed = Templates(t.store, cfg, t.layouts_dir)
    st = changed.studio3("chels-small-v1")
    assert st is not None and st.current is False
    assert changed.current_studio3_bytes("chels-small-v1") is None
    listing = changed.listing()
    assert all("error" in row for row in listing["layouts"])
    assert [o["layout_id"] for o in listing["outdated"]] == ["chels-small-v1"]
    with pytest.raises(ValueError, match="not the current layout"):
        changed.save_studio3("chels-small-v1", "a.studio3", b"x")
    assert client.delete("/api/templates/chels-small-v1/studio3").json() == {"ok": True}
    assert t.studio3("chels-small-v1") is None
