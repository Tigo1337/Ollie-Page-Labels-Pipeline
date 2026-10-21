"""Startup migration from the old free-packing geometry to the fixed half-sheet layouts."""
import json
import sqlite3

from sqlalchemy import select

from app.db import ArchivedPresetRow, DesignRow, PresetRow, Setting, make_session_factory
from app.migrate import REVIEW_NOTE, geometry_version, migrate
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
    finishes = json.loads((REPO / "config" / "finishes.json").read_text())
    finishes[0].update(notch=False, cost_per_sheet=1.25)
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
    assert list((tmp_path / "backups").glob("app-before-geometry-v2-*.db"))
    assert repo.store.list("backups/")
    with repo.Session() as s:
        settings = {r.key: r.value for r in s.scalars(select(Setting))}
        presets = {(p.design_id, p.size_id): p for p in s.scalars(select(PresetRow))}
        archived = {(a.design_id, a.size_id) for a in s.scalars(select(ArchivedPresetRow))}
        designs = {d.id: d for d in s.scalars(select(DesignRow))}
    assert [x["id"] for x in settings["sizes"]] == ["pencil", "small", "medium", "large", "tag", "round", "shoe"]
    assert "starter" in [x["id"] for x in settings["packs"]] and "margin" not in settings["production"]
    assert all(f["notch"] for f in settings["finishes"]) and settings["finishes"][0]["cost_per_sheet"] == 1.25
    assert settings["texts"]["fr"]["sizes"]["shoe"] == "Souliers"
    assert settings["geometry_version"] == {"version": 2} and settings["migration_log"]["changes"] == changes
    # kept and flagged à revoir / archived, never deleted
    assert presets[("dino", "small")].review == REVIEW_NOTE and presets[("fox", "round")].review == REVIEW_NOTE
    assert presets[("fox", "large")].review == REVIEW_NOTE
    assert archived == {("dino", "mini"), ("dino", "square")}
    assert ("dino", "mini") not in presets
    # designs: all 100, scene settings filled, user edits kept, reference crops imported
    assert len(designs) == 100 and designs["fox"].name.endswith("(edited)")
    assert designs["dino"].mini_start == 0.24 and designs["dino"].no_character_sizes == ["tag"]
    assert designs["moon-stars"].square_text is not None
    assert ("dino", "pencil") in presets and ("sakura", "small") in presets
    # the catalogue now builds and only once
    cat = repo.catalog()
    assert cat.production.min_cap_mm == 1.7 and "shoe" in cat.sizes
    assert migrate(repo, REPO / "config", url, tmp_path) == []


def test_saving_a_preset_clears_the_review_flag(tmp_path):
    from engine.config import Preset
    db = old_database(tmp_path)
    url = f"sqlite:///{db}"
    repo = Repo(make_session_factory(url), LocalBlobStore(tmp_path / "blobs"))
    migrate(repo, REPO / "config", url, tmp_path)
    repo.set_preset("dino", "small", Preset.from_dict(PRESET))
    with repo.Session() as s:
        assert s.get(PresetRow, ("dino", "small")).review is None


def test_fresh_database_needs_no_migration(tmp_path):
    url = f"sqlite:///{tmp_path / 'new.db'}"
    repo = Repo(make_session_factory(url), LocalBlobStore(tmp_path / "blobs"))
    assert repo.seed(REPO / "config")
    assert geometry_version(repo) == 2
    assert migrate(repo, REPO / "config", url, tmp_path) == []
