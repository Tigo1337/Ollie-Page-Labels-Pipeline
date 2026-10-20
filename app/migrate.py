"""Startup migration to the fixed half-sheet geometry (geometry_version 2).

Sizes, packs and production values are seeded into the database only once, so a database made
before the fixed layouts still holds the old geometry (mini / square sizes, 12 mm margin...).
When `geometry_version` is below 2 this, once:

1. backs up the database (a copy of the SQLite file, and a JSON dump of the settings, designs and
   presets in blob storage under backups/),
2. replaces the `production`, `sizes` and `packs` settings with config/*.json, turns the laminate
   notch on for every finish and updates the size names in the proof wording,
3. keeps the presets of sizes that still exist (small, medium, large, round) flagged "à revoir",
   and archives (never deletes) the presets of sizes that are gone (mini, square),
4. adds the designs from config/designs.json that are missing, fills in their scene settings
   (mini_start, square_text, no_character_sizes) and their saved crop presets,
5. records geometry_version = 2 and the change log (setting `migration_log`).
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import shutil
from pathlib import Path

from sqlalchemy import select

from engine.config import load_catalog

from .db import ArchivedPresetRow, DesignRow, PresetRow, Setting
from .repo import GEOMETRY_VERSION, Repo, design_row_from

log = logging.getLogger(__name__)
REVIEW_SIZES = ("small", "medium", "large", "round")
REVIEW_NOTE = "à revoir : la taille a changé avec les mises en page fixes (géométrie v2)"


def geometry_version(repo: Repo) -> int:
    with repo.Session() as s:
        row = s.get(Setting, "geometry_version")
        return int(row.value.get("version", 1)) if row is not None else 1


def migrate(repo: Repo, config_dir: Path, database_url: str, data_dir: Path) -> list[str]:
    """Run the pending migrations. Returns the change log (empty when nothing was to do)."""
    if geometry_version(repo) >= GEOMETRY_VERSION:
        return []
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    changes = backup(repo, database_url, data_dir, stamp)
    changes += _to_v2(repo, config_dir)
    with repo.Session() as s:
        for key, value in (("geometry_version", {"version": GEOMETRY_VERSION}),
                           ("migration_log", {"at": stamp, "to": GEOMETRY_VERSION, "changes": changes})):
            row = s.get(Setting, key)
            if row is None:
                s.add(Setting(key=key, value=value))
            else:
                row.value = value
        s.commit()
    repo._bump()
    for line in changes:
        log.info("migration: %s", line)
    return changes


def backup(repo: Repo, database_url: str, data_dir: Path, stamp: str) -> list[str]:
    out = []
    if database_url.startswith("sqlite:///"):
        db = Path(database_url[len("sqlite:///"):])
        if db.exists():
            dest = data_dir / "backups" / f"{db.stem}-before-geometry-v2-{stamp}{db.suffix}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(db, dest)
            out.append(f"backed up the database to {dest}")
    with repo.Session() as s:
        dump = {
            "settings": {r.key: r.value for r in s.scalars(select(Setting))},
            "designs": [{c.name: getattr(r, c.name) for c in DesignRow.__table__.columns if c.name != "updated_at"}
                        for r in s.scalars(select(DesignRow))],
            "presets": [{"design_id": r.design_id, "size_id": r.size_id, "data": r.data}
                        for r in s.scalars(select(PresetRow))],
        }
    key = f"backups/before-geometry-v2-{stamp}.json"
    repo.store.put(key, json.dumps(dump, indent=1, ensure_ascii=False, default=str).encode())
    out.append(f"saved settings, designs and presets to storage: {key}")
    return out


def _to_v2(repo: Repo, config_dir: Path) -> list[str]:
    cat = load_catalog(config_dir)
    changes: list[str] = []

    def cfg(name: str):
        v = json.loads((config_dir / name).read_text(encoding="utf-8"))
        return {k: x for k, x in v.items() if not k.startswith("_")} if isinstance(v, dict) else v

    with repo.Session() as s:
        settings = {r.key: r for r in s.scalars(select(Setting))}
        for key, fname in (("production", "production.json"), ("sizes", "sizes.json"), ("packs", "packs.json")):
            new = cfg(fname)
            old = settings[key].value if key in settings else None
            if key in settings:
                settings[key].value = new
            else:
                s.add(Setting(key=key, value=new))
            if key in ("sizes", "packs"):
                before = [x["id"] for x in old or []]
                changes.append(f"{key}: {', '.join(before) or '-'} -> {', '.join(x['id'] for x in new)}")
            else:
                changes.append("production: replaced (page, marks and keep-outs now come from sheet.json)")
        if "finishes" in settings:
            fins = [dict(f, notch=True) for f in settings["finishes"].value]
            settings["finishes"].value = fins
            changes.append("finishes: laminate notch on for every finish (prices kept)")
        if "texts" in settings:
            new_texts = cfg("texts.json")
            texts = dict(settings["texts"].value)
            for lang, t in texts.items():
                if lang in new_texts:
                    t = dict(t)
                    for k in ("sizes", "size_labels"):
                        if k in new_texts[lang]:
                            t[k] = new_texts[lang][k]
                    texts[lang] = t
            settings["texts"].value = texts
            changes.append("texts: size names updated for the new sizes")

        # presets: keep the sizes that still exist (to review), archive the others
        for p in list(s.scalars(select(PresetRow))):
            if p.size_id not in cat.sizes:
                s.add(ArchivedPresetRow(design_id=p.design_id, size_id=p.size_id, data=p.data,
                                        reason=f"size '{p.size_id}' removed in geometry v2"))
                s.delete(p)
                changes.append(f"preset {p.design_id}/{p.size_id}: archived (size removed)")
            elif p.size_id in REVIEW_SIZES:
                p.review = REVIEW_NOTE
                changes.append(f"preset {p.design_id}/{p.size_id}: kept, flagged à revoir")
        s.flush()

        # designs: add the missing ones, fill in scene settings and saved presets
        rows = {r.id: r for r in s.scalars(select(DesignRow))}
        have_presets = {(p.design_id, p.size_id) for p in s.scalars(select(PresetRow))}
        pos = max((r.position for r in rows.values()), default=-1) + 1
        added = []
        for d in cat.designs.values():
            row = rows.get(d.id)
            if row is None:
                s.add(design_row_from(d, pos))
                pos += 1
                added.append(d.id)
            else:
                if row.mini_start is None:
                    row.mini_start = d.mini_start
                if row.square_text is None:
                    row.square_text = list(d.square_text)
                if row.no_character_sizes is None:
                    row.no_character_sizes = list(d.no_character_sizes)
        s.flush()
        if added:
            changes.append(f"designs: added {len(added)} ({', '.join(added)})")
        for d in cat.designs.values():
            for sid, pr in d.presets.items():
                if (d.id, sid) not in have_presets:
                    s.add(PresetRow(design_id=d.id, size_id=sid, data=pr.to_dict()))
                    changes.append(f"preset {d.id}/{sid}: imported from the reference crops")
        s.commit()
    return changes
