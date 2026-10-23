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
    assert (school["pieces"], school["alone"]) == (14, 7)
    assert school["pieces_by_size"] == {"pencil": 3, "small": 3, "medium": 2, "large": 1, "round": 1, "tag": 2,
                                        "shoe": 2}
    assert school["envelope"]["weight_g"] == 89.0 and "5 mm" in school["envelope"]["warning"]
    tag = next(s for s in cat["sizes"] if s["id"] == "tag")
    assert (tag["layout_id"], tag["per_piece"], tag["per_sheet"]) == ("chels-tag-v2", 34, 102)
    assert [f["id"] for f in cat["finishes"]] == ["matte"] and cat["finishes"][0]["label"] == "Matte laminate"
    designs = client.get("/api/designs").json()
    assert len(designs) == 100
    # the reference crops of config/designs.json were made for the old name position: archived, not used
    assert [d["id"] for d in designs if d["presets"]] == []
    from sqlalchemy import select

    from app.db import ArchivedPresetRow
    with client.app.state.repo.Session() as s:
        archived = {(a.design_id, a.size_id): a.reason for a in s.scalars(select(ArchivedPresetRow))}
    assert len(archived) == 19 and ("dino", "pencil") in archived and ("tractor", "large") in archived
    assert set(archived.values()) == {"fixed name position (geometry v3)"}
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
    r = client.post("/api/make", json={"design": "axolotl", "pack": "starter",
                                       "name": "Émilie-Rose", "font": 3, "order_id": "1234"})
    assert r.status_code == 200, r.text
    run = r.json()
    kinds = {f["kind"] for f in run["files"]}
    assert {"print", "template", "page-proof", "customer-proof", "notch", "info", "slip", "zip"} <= kinds
    assert [sh["layout_id"] for sh in run["summary"]["sheets"]] == [
        "chels-pencil-v2", "chels-small-v2", "chels-medium-v2", "chels-round-v2"]
    assert all(len(sh["pieces"]) == 3 and sh["pieces"][2]["bonus"] for sh in run["summary"]["sheets"])
    assert set(run["summary"]["finishes"]) == {"matte"}
    z = next(f["name"] for f in run["files"] if f["kind"] == "zip")
    got = client.get(f"/api/runs/{run['id']}/files/{z}")
    assert got.status_code == 200 and zipfile.ZipFile(io.BytesIO(got.content)).namelist()
    assert client.get("/api/runs").json()[0]["id"] == run["id"]
    r = client.post("/api/make", json={"design": "axolotl", "pack": "daycare",
                                       "name": "Émilie", "font": 1, "unpaired": "blank"})
    assert r.status_code == 200
    shoe = next(sh for sh in r.json()["summary"]["sheets"] if sh["size"] == "shoe")
    assert shoe["pieces"][0] is not None and shoe["pieces"][1:] == [None, None]
    names = [f["name"] for f in r.json()["files"]]
    assert all(n.isascii() for n in names)


def test_crop_presets_are_saved_and_used_by_orders(client):
    data = art_zip(["shark"], client.app.state.svc.catalog)
    import_and_wait(client, data)
    r = client.get("/api/designs/shark/presets").json()
    large = next(s for s in r["sizes"] if s["size"] == "large")
    assert large["is_auto"] and large["preset"] == large["auto"] and r["art"]["wide"] == [2752, 680]
    fixed = large["fixed_text"]
    assert fixed[0] == 0.42 and large["auto"]["text"] == fixed
    assert next(s for s in r["sizes"] if s["size"] == "tag")["fixed_text"] is None

    before = client.post("/api/preview", json={"design": "shark", "size": "large", "name": "Léo"}).json()
    preset = {"source": "wide", "center": [0.6, 0.5], "height": 0.6, "text": [0.35, 0.15, 0.95, 0.85]}
    saved = client.put("/api/designs/shark/presets/large", json=preset).json()["preset"]
    assert saved == {**preset, "text": fixed}            # the art is saved, the name box stays the fixed one
    preset = saved
    after = client.post("/api/preview", json={"design": "shark", "size": "large", "name": "Léo"}).json()
    assert after["preset"] == preset and not after["preset_is_auto"] and after["image"] != before["image"]
    # an editor preview with another box still prints the fixed one
    moved = client.post("/api/preview", json={"design": "shark", "size": "large", "name": "Léo",
                                              "preset": {**preset, "text": [0.1, 0.1, 0.5, 0.9]}}).json()
    assert moved["preset"]["text"] == fixed

    # the saved crop is what an order prints
    run = client.post("/api/make", json={"design": "shark", "pack": "large18", "name": "Léo", "font": 1}).json()
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


def test_one_finish_and_old_finishes_are_made_in_matte(client):
    assert client.get("/api/shop").json() == {"default_finish": "matte"}
    assert client.patch("/api/shop", json={"default_finish": "gloss"}).status_code == 400   # no such finish now
    data = art_zip(["bee"], client.app.state.svc.catalog)
    import_and_wait(client, data)
    run = client.post("/api/make", json={"design": "bee", "pack": "pencil51", "name": "Zoë", "font": 1}).json()
    assert set(run["summary"]["finishes"]) == {"matte"} and run["request"]["finish"] == "matte"
    assert any(f["kind"] == "notch" for f in run["files"])
    old = client.post("/api/make", json={"design": "bee", "pack": "pencil51", "finish": "holographic",
                                         "name": "Zoë", "font": 1}).json()
    assert set(old["summary"]["finishes"]) == {"matte"}
    assert any("'holographic' finish, produced in matte laminate" in w for w in old["warnings"])
    assert client.post("/api/make", json={"design": "bee", "pack": "pencil51", "finish": "shiny",
                                          "name": "Zoë"}).status_code == 400


def test_envelope_settings(client):
    prod = client.get("/api/production").json()
    assert (prod["piece_weight_g"], prod["envelope_weight_g"], prod["piece_thickness_mm"]) == (6.0, 5.0, 0.35)
    assert client.patch("/api/production", json={"piece_weight_g": 7.5}).json()["piece_weight_g"] == 7.5
    starter = next(p for p in client.get("/api/catalog").json()["packs"] if p["id"] == "starter")
    assert starter["envelope"]["weight_g"] == 5 * 7.5 + 5
    assert client.patch("/api/production", json={"piece_weight_g": -1}).status_code == 400
    assert client.patch("/api/production", json={"min_cap_mm": 1}).status_code == 400
    client.patch("/api/production", json={"piece_weight_g": 6.0})


# ---------------------------------------------------------------- templates
def test_templates_page_files_and_studio3(client, tmp_path):
    data = client.get("/api/templates").json()
    ids = [row["layout_id"] for row in data["layouts"]]
    assert ids == [f"chels-{s}-v2" for s in ("pencil", "small", "medium", "large", "tag", "round", "shoe")]
    assert data["outdated"] == [] and all(row["studio3"] is None for row in data["layouts"])
    assert all(row["per_sheet"] == 3 * row["per_piece"] for row in data["layouts"])
    assert client.get("/api/templates/chels-round-v2/preview.png").headers["content-type"] == "image/png"
    svg = client.get("/api/templates/chels-round-v2/files/svg")
    assert svg.status_code == 200 and svg.text.count("<circle") == 30
    assert (REPO / "templates" / "chels-round-v2.svg").read_text() == svg.text
    dxf = client.get("/api/templates/chels-shoe-v2/files/dxf")
    assert "attachment" in dxf.headers["content-disposition"] and "ANCHOR" in dxf.text
    assert client.get("/api/templates/chels-tag-v2/files/calibration.pdf").content.startswith(b"%PDF")
    assert client.get("/api/templates/chels-mini-v1/files/svg").status_code == 404
    assert client.get("/api/templates/chels-tag-v2/files/exe").status_code == 404

    # a .studio3 uploaded for a half-sheet (v1) layout is shown as outdated and never bundled
    t: Templates = client.app.state.templates
    v1 = t.layout("chels-medium-v1")
    t.store.put("templates/chels-medium-v1.studio3", b"OLD")
    t.store.put("templates/chels-medium-v1.studio3.json", json.dumps(
        {"geometry_hash": v1.geometry_hash, "filename": "chels-medium-v1.studio3", "bytes": 3,
         "uploaded_at": "2026-01-01T00:00:00+00:00"}).encode())
    outdated = client.get("/api/templates").json()["outdated"]
    assert [(o["layout_id"], o["current"]) for o in outdated] == [("chels-medium-v1", False)]
    assert t.current_studio3_bytes("chels-medium-v1") is None
    client.delete("/api/templates/chels-medium-v1/studio3")

    # .studio3 upload: stored with the geometry hash, current until the geometry changes
    r = client.post("/api/templates/chels-small-v2/studio3", files={"file": ("x.png", b"nope")})
    assert r.status_code == 400 and ".studio3" in r.json()["detail"]
    r = client.post("/api/templates/chels-small-v2/studio3", files={"file": ("chels-small-v2.studio3", b"STUDIO")})
    assert r.status_code == 200 and r.json()["current"] is True
    row = next(x for x in client.get("/api/templates").json()["layouts"] if x["layout_id"] == "chels-small-v2")
    assert row["studio3"]["current"] and row["studio3"]["geometry_hash"] == row["geometry_hash"]
    assert client.get("/api/templates/chels-small-v2/studio3").content == b"STUDIO"
    assert t.current_studio3_bytes("chels-small-v2") == b"STUDIO"

    # sheet.json changes (no new layout yet): the upload is outdated and never bundled
    cfg = tmp_path / "config"
    shutil.copytree(REPO / "config", cfg)
    sheet = json.loads((cfg / "sheet.json").read_text())
    sheet["edge_margin"] = 10.5
    (cfg / "sheet.json").write_text(json.dumps(sheet))
    changed = Templates(t.store, cfg, t.layouts_dir)
    st = changed.studio3("chels-small-v2")
    assert st is not None and st.current is False
    assert changed.current_studio3_bytes("chels-small-v2") is None
    listing = changed.listing()
    assert all("error" in row for row in listing["layouts"])
    assert [o["layout_id"] for o in listing["outdated"]] == ["chels-small-v2"]
    with pytest.raises(ValueError, match="not the current layout"):
        changed.save_studio3("chels-small-v2", "a.studio3", b"x")
    assert client.delete("/api/templates/chels-small-v2/studio3").json() == {"ok": True}
    assert t.studio3("chels-small-v2") is None
