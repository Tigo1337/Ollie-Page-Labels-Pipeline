"""Startup migrations: the old free-packing geometry -> fixed half-sheet layouts (v2) -> thirds, one finish
and the fixed name position (v3)."""
import json
import sqlite3

from sqlalchemy import select

from app.db import ArchivedPresetRow, DesignRow, PresetRow, Setting, make_session_factory
from app.migrate import FIXED_NAME_NOTE, REVIEW_NOTE, geometry_version, migrate
from app.repo import Repo
from app.settings import REPO
from app.storage import LocalBlobStore

OLD_SIZES = [
    {"id": "mini", "label": "Mini (pencils)", "shape": "rrect", "w": 35, "h": 9, "r": 2},
    {"id": "small", "label": "Small", "shape": "rrect", "w": 45, "h": 13, "r": 3},
    {"id": "medium", "label": "Medium (bottles)", "shape": "rrect", "w": 60, "h": 16, "r": 4},
    {"id": "large", "label": "Large (lunch boxes)", "shape": "rrect", "w": 90, "h": 25, "r": 5},
    {"id": "round", "label": "Round (shoes, caps)", "shape": "circle", "w": 30, "h": 30, "r": 15},
    {"id": "square", "label": "Square (books, boxes)", "shape": "rrect", "w": 38, "h": 38, "r": 4},
]
OLD_PACKS = [{"id": "mini60", "label": "60 Mini labels", "contents": {"mini": 60}}]
OLD_PRODUCTION = {"page_w": 215.9, "page_h": 279.4, "margin": 12.0, "keepout": 36.0, "mark_length": 20.0,
                  "bleed": 1.25, "gap": 3.0, "safe": 1.0, "dpi": 600, "proof_dpi": 150, "min_cap_mm": 1.7,
                  "notch": 34.0}
PRESET = {"source": "wide", "center": [0.3, 0.5], "height": 1.0, "text": [0.35, 0.1, 0.96, 0.9]}


def old_database(tmp_path):
    """A database as the app made it before the fixed layouts (old schema, old settings, 20 designs)."""
    db = tmp_path / "app.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE settings (key VARCHAR(64) PRIMARY KEY, value JSON);
        CREATE TABLE designs (id VARCHAR(64) PRIMARY KEY, name VARCHAR(200), fill VARCHAR(9), stroke VARCHAR(9),
            char_end FLOAT, stroke_ratio FLOAT, cap_frac FLOAT, position INTEGER, wide_version VARCHAR(40),
            wide_w INTEGER, wide_h INTEGER, wide_orig_ext VARCHAR(8), square_version VARCHAR(40), square_w INTEGER,
            square_h INTEGER, square_ext VARCHAR(8), updated_at DATETIME);
        CREATE TABLE presets (design_id VARCHAR(64) REFERENCES designs(id) ON DELETE CASCADE,
            size_id VARCHAR(32), data JSON, PRIMARY KEY (design_id, size_id));
    """)
    old_texts = json.loads((REPO / "config" / "texts.json").read_text())
    for lang in old_texts.values():
        lang["sizes"] = {"mini": "Mini", "square": "Square"}
    finishes = [{"id": "matte", "label": "Matte", "media": "white inkjet printable vinyl",
                 "laminate": "matte clear overlaminate", "notch": False, "cost_per_sheet": 1.25},
                {"id": "gloss", "label": "Glossy", "media": "white inkjet printable vinyl",
                 "laminate": "gloss clear overlaminate", "notch": False, "cost_per_sheet": None}]
    for key, val in (("production", OLD_PRODUCTION), ("sizes", OLD_SIZES), ("packs", OLD_PACKS),
                     ("finishes", finishes), ("texts", old_texts),
                     ("fonts", json.loads((REPO / "config" / "fonts.json").read_text()))):
        con.execute("INSERT INTO settings VALUES (?, ?)", (key, json.dumps(val)))
    for i, d in enumerate(json.loads((REPO / "config" / "designs.json").read_text())[:20]):
        con.execute("INSERT INTO designs (id, name, fill, stroke, char_end, cap_frac, position) VALUES (?,?,?,?,?,?,?)",
                    (d["id"], d["name"] + (" (edited)" if d["id"] == "fox" else ""), d["fill"], d["stroke"],
                     d["char_end"], 0.52, i))
    for design, size in (("dino", "mini"), ("dino", "square"), ("dino", "small"), ("fox", "round"),
                         ("fox", "large")):
        con.execute("INSERT INTO presets VALUES (?, ?, ?)", (design, size, json.dumps(PRESET)))
    con.commit()
    con.close()
    return db


def test_old_database_is_migrated_once(tmp_path):
    db = old_database(tmp_path)
    url = f"sqlite:///{db}"
    repo = Repo(make_session_factory(url), LocalBlobStore(tmp_path / "blobs"))   # adds the new columns
    assert geometry_version(repo) == 1
    changes = migrate(repo, REPO / "config", url, tmp_path)
    assert any("backed up the database" in c for c in changes)
    assert list((tmp_path / "backups").glob("app-before-geometry-v3-*.db"))
    assert repo.store.list("backups/")
    with repo.Session() as s:
        settings = {r.key: r.value for r in s.scalars(select(Setting))}
        presets = {(p.design_id, p.size_id): p for p in s.scalars(select(PresetRow))}
        archived = {(a.design_id, a.size_id) for a in s.scalars(select(ArchivedPresetRow))}
        designs = {d.id: d for d in s.scalars(select(DesignRow))}
    assert [x["id"] for x in settings["sizes"]] == ["pencil", "small", "medium", "large", "tag", "round", "shoe"]
    assert [x["id"] for x in settings["packs"]][:2] == ["pencil51", "small57"]
    assert "margin" not in settings["production"] and settings["production"]["piece_weight_g"] == 6.0
    assert [f["id"] for f in settings["finishes"]] == ["matte"] and settings["finishes"][0]["notch"]
    assert settings["shop"]["default_finish"] == "matte"
    assert settings["texts"]["fr"]["sizes"]["shoe"] == "Souliers"
    assert "holographic" not in settings["texts"]["en"]["proof_footer"]
    assert settings["geometry_version"] == {"version": 3} and settings["migration_log"]["changes"] == changes
    assert settings["migration_log"]["from"] == 1
    # round kept and flagged à revoir; gone sizes and the strip sizes archived, never deleted
    assert presets[("fox", "round")].review == REVIEW_NOTE
    assert archived == {("dino", "mini"), ("dino", "square"), ("dino", "small"), ("fox", "large")} | {
        (d, s) for d, s in archived if s in ("pencil", "small", "medium", "large")}
    assert not any(s in ("pencil", "small", "medium", "large") for _, s in presets)
    assert ("dino", "mini") not in presets
    # designs: all 100, scene settings filled, user edits kept, reference crops imported
    assert len(designs) == 100 and designs["fox"].name.endswith("(edited)")
    assert designs["dino"].mini_start == 0.24 and designs["dino"].no_character_sizes == ["tag"]
    assert designs["moon-stars"].square_text is not None
    # the catalogue now builds and only once
    cat = repo.catalog()
    assert cat.production.min_cap_mm == 1.7 and "shoe" in cat.sizes and list(cat.finishes) == ["matte"]
    assert migrate(repo, REPO / "config", url, tmp_path) == []


def test_saving_a_preset_clears_the_review_flag(tmp_path):
    from engine.config import Preset
    db = old_database(tmp_path)
    url = f"sqlite:///{db}"
    repo = Repo(make_session_factory(url), LocalBlobStore(tmp_path / "blobs"))
    migrate(repo, REPO / "config", url, tmp_path)
    with repo.Session() as s:
        assert s.get(PresetRow, ("fox", "round")).review == REVIEW_NOTE
    repo.set_preset("fox", "round", Preset.from_dict({**PRESET, "source": "square"}))
    with repo.Session() as s:
        assert s.get(PresetRow, ("fox", "round")).review is None


def test_fresh_database_needs_no_migration(tmp_path):
    url = f"sqlite:///{tmp_path / 'new.db'}"
    repo = Repo(make_session_factory(url), LocalBlobStore(tmp_path / "blobs"))
    assert repo.seed(REPO / "config")
    assert geometry_version(repo) == 3
    assert migrate(repo, REPO / "config", url, tmp_path) == []


def v2_database(tmp_path):
    """A database as the half-sheet app (geometry v2) left it: v2 packs, three finishes, saved presets for
    every kind of size, Listings settings with prices, a run made before v3."""
    url = f"sqlite:///{tmp_path / 'v2.db'}"
    repo = Repo(make_session_factory(url), LocalBlobStore(tmp_path / "blobs"))
    repo.seed(REPO / "config")
    old_packs = [{"id": "pencil60", "label": "60 Skinny pencil labels", "contents": {"pencil": 60}},
                 {"id": "starter", "label": "Starter pack (61)", "contents": {"pencil": 30, "small": 31}},
                 {"id": "school", "label": "Back-to-school pack", "contents": {"pencil": 30}}]
    finishes = [{"id": f, "label": f.title(), "media": "white inkjet printable vinyl", "laminate": f"{f} laminate",
                 "notch": True, "cost_per_sheet": None} for f in ("matte", "gloss", "holographic")]
    listings = json.loads((REPO / "config" / "listings.json").read_text())
    listings = {k: v for k, v in listings.items() if not k.startswith("_") and k != "ship_time"}
    listings.update(shop_name="", pack_short={"pencil60": "60 Skinny", "starter": "Starter (61)"},
                    pack_code={"pencil60": "PEN60", "starter": "START"},
                    prices={"pencil60": "9.50", "starter": "14.00", "school": "29.99"})
    from app.db import RunRow
    with repo.Session() as s:
        for key, val in (("packs", old_packs), ("finishes", finishes), ("listings", listings),
                         ("shop", {"default_finish": "holographic"}), ("geometry_version", {"version": 2})):
            row = s.get(Setting, key)
            if row is None:
                s.add(Setting(key=key, value=val))
            else:
                row.value = val
        s.query(PresetRow).delete()
        for design, size in (("dino", "pencil"), ("dino", "small"), ("dino", "medium"), ("fox", "large"),
                             ("fox", "tag"), ("fox", "round"), ("dino", "shoe")):
            s.add(PresetRow(design_id=design, size_id=size,
                            data={**PRESET, "source": "square" if size in ("round", "shoe") else "wide"}))
        s.add(RunRow(id="old-run", title="old", prefix="old", request={"finish": "gloss"}, files=[],
                     summary={"finishes": {"gloss": {"sheets": 1, "labels": 60}},
                              "sheets": [{"n": 1, "finish": "gloss", "top": {"tag": "a"}, "bottom": None}]},
                     warnings=[]))
        s.commit()
    return repo, url


def test_v2_database_is_migrated_to_v3(tmp_path):
    repo, url = v2_database(tmp_path)
    assert geometry_version(repo) == 2
    changes = migrate(repo, REPO / "config", url, tmp_path)
    assert any("backed up the database" in c for c in changes)
    assert list((tmp_path / "backups").glob("v2-before-geometry-v3-*.db"))
    assert any(k.startswith("backups/before-geometry-v3-") for k in repo.store.list("backups/"))
    from app.db import RunRow
    with repo.Session() as s:
        settings = {r.key: r.value for r in s.scalars(select(Setting))}
        presets = {(p.design_id, p.size_id) for p in s.scalars(select(PresetRow))}
        archived = {(a.design_id, a.size_id): a.reason for a in s.scalars(select(ArchivedPresetRow))}
        run = s.get(RunRow, "old-run")
    cfg = {x["id"]: x for x in json.loads((REPO / "config" / "packs.json").read_text())}
    assert [x["id"] for x in settings["packs"]] == list(cfg)
    assert [x["id"] for x in settings["sizes"]] == ["pencil", "small", "medium", "large", "tag", "round", "shoe"]
    assert settings["finishes"] == json.loads((REPO / "config" / "finishes.json").read_text())
    assert settings["shop"]["default_finish"] == "matte"
    # Listings: new pack ids, prices kept where the pack still exists, shop name, ship_time
    lst = settings["listings"]
    assert list(lst["pack_short"]) == list(cfg) and lst["pack_short"]["starter"] == "Starter (73)"
    assert lst["pack_code"]["pencil51"] == "PEN51" and lst["pack_code"]["shoe12"] == "SHOE12"
    assert lst["prices"] == {**{pid: "" for pid in cfg}, "starter": "14.00", "school": "29.99"}
    assert lst["shop_name"] == "Mazie Page Creations" and lst["ship_time"] == "[X] business days"
    # presets: strip sizes archived with the note, tag / round / shoe kept
    assert presets == {("fox", "tag"), ("fox", "round"), ("dino", "shoe")}
    want = (("dino", "pencil"), ("dino", "small"), ("dino", "medium"), ("fox", "large"))
    assert set(want) <= set(archived) and set(archived.values()) == {FIXED_NAME_NOTE}
    # (the rest are the old reference crops from config/designs.json, archived when the database was seeded)
    assert all(s in ("pencil", "small", "medium", "large") for _, s in archived)
    # history untouched; the catalogue builds; only once
    assert run.summary["finishes"] == {"gloss": {"sheets": 1, "labels": 60}} and run.request["finish"] == "gloss"
    assert settings["geometry_version"] == {"version": 3} and settings["migration_log"]["from"] == 2
    assert repo.catalog().packs["school"].total == 216
    assert migrate(repo, REPO / "config", url, tmp_path) == []


def test_v3_migration_keeps_a_shop_name_that_was_set(tmp_path):
    repo, url = v2_database(tmp_path)
    with repo.Session() as s:
        row = s.get(Setting, "listings")
        row.value = {**row.value, "shop_name": "My Shop"}
        s.commit()
    migrate(repo, REPO / "config", url, tmp_path)
    assert repo.setting("listings")["shop_name"] == "My Shop"
