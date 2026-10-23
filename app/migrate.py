"""Startup migrations of the geometry (`geometry_version`), run once each, oldest first.

Sizes, packs and production values are seeded into the database only once, so an older database
still holds the old geometry. Each migration first backs up the database (a copy of the SQLite file,
and a JSON dump of the settings, designs and presets in blob storage under backups/), then records
the new `geometry_version` and its change log (setting `migration_log`).

To 2, the fixed half-sheet layouts:
1. replaces the `production`, `sizes` and `packs` settings with config/*.json, turns the laminate
   notch on for every finish and updates the size names in the proof wording,
2. keeps the presets of sizes that still exist (small, medium, large, round) flagged "à revoir",
   and archives (never deletes) the presets of sizes that are gone (mini, square),
3. adds the designs from config/designs.json that are missing, fills in their scene settings
   (mini_start, square_text, no_character_sizes) and their saved crop presets.

To 3, thirds, one finish and the fixed name position:
1. replaces the `sizes`, `packs` and `finishes` settings with config/*.json, sets the shop's finish
   to matte, adds the new production numbers (envelope estimate) and drops the holographic note
   from the proof wording,
2. updates the Listings settings: the new pack ids in pack_short / pack_code / prices (a price is
   kept when its pack id still exists), the shop name when empty, ship_time,
3. archives (never deletes) every saved crop preset of the strip sizes with a fixed name position
   (pencil, small, medium, large); tag, round and shoe presets stay.
Runs and files made before stay downloadable as they are (their finish text is not touched).
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
from .repo import FIXED_NAME_NOTE, GEOMETRY_VERSION, Repo, design_row_from

log = logging.getLogger(__name__)
REVIEW_SIZES = ("small", "medium", "large", "round")
REVIEW_NOTE = "à revoir : la taille a changé avec les mises en page fixes (géométrie v2)"
FIXED_NAME_SIZES = ("pencil", "small", "medium", "large")
OLD_PROOF_FOOTERS = {
    "en": "Colours can look slightly different on screen. The holographic shimmer is a simulation of the real finish.",
    "fr": "Les couleurs peuvent paraître légèrement différentes à l'écran. L'effet holographique est une simulation "
          "du fini réel.",
}


def geometry_version(repo: Repo) -> int:
    with repo.Session() as s:
        row = s.get(Setting, "geometry_version")
        return int(row.value.get("version", 1)) if row is not None else 1


def migrate(repo: Repo, config_dir: Path, database_url: str, data_dir: Path) -> list[str]:
    """Run the pending migrations. Returns the change log (empty when nothing was to do)."""
    if geometry_version(repo) >= GEOMETRY_VERSION:
        return []
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    start = geometry_version(repo)
    changes = backup(repo, database_url, data_dir, stamp, GEOMETRY_VERSION)
    if start < 2:
        changes += _to_v2(repo, config_dir)
    if start < 3:
        changes += _to_v3(repo, config_dir)
    with repo.Session() as s:
        for key, value in (("geometry_version", {"version": GEOMETRY_VERSION}),
                           ("migration_log", {"at": stamp, "from": start, "to": GEOMETRY_VERSION,
                                              "changes": changes})):
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


def backup(repo: Repo, database_url: str, data_dir: Path, stamp: str, to: int = GEOMETRY_VERSION) -> list[str]:
    out = []
    if database_url.startswith("sqlite:///"):
        db = Path(database_url[len("sqlite:///"):])
        if db.exists():
            dest = data_dir / "backups" / f"{db.stem}-before-geometry-v{to}-{stamp}{db.suffix}"
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
    key = f"backups/before-geometry-v{to}-{stamp}.json"
    repo.store.put(key, json.dumps(dump, indent=1, ensure_ascii=False, default=str).encode())
    out.append(f"saved settings, designs and presets to storage: {key}")
    return out


def _cfg(config_dir: Path, name: str):
    v = json.loads((config_dir / name).read_text(encoding="utf-8"))
    return {k: x for k, x in v.items() if not k.startswith("_")} if isinstance(v, dict) else v


def _to_v2(repo: Repo, config_dir: Path) -> list[str]:
    cat = load_catalog(config_dir)
    changes: list[str] = []

    def cfg(name: str):
        return _cfg(config_dir, name)

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


def _to_v3(repo: Repo, config_dir: Path) -> list[str]:
    changes: list[str] = []
    with repo.Session() as s:
        settings = {r.key: r for r in s.scalars(select(Setting))}

        def put(key: str, value) -> None:
            if key in settings:
                settings[key].value = value
            else:
                settings[key] = Setting(key=key, value=value)
                s.add(settings[key])

        for key in ("sizes", "packs", "finishes"):
            new = _cfg(config_dir, f"{key}.json")
            before = [x["id"] for x in settings[key].value or []] if key in settings else []
            put(key, new)
            changes.append(f"{key}: {', '.join(before) or '-'} -> {', '.join(x['id'] for x in new)}")
        shop = dict(settings["shop"].value) if "shop" in settings else {}
        if shop.get("default_finish") != "matte":
            changes.append(f"shop: finish {shop.get('default_finish', '-')} -> matte (the only finish)")
        put("shop", {**shop, "default_finish": "matte"})
        if "production" in settings:
            prod = dict(settings["production"].value)
            added = {k: v for k, v in _cfg(config_dir, "production.json").items() if k not in prod}
            if added:
                put("production", {**prod, **added})
                changes.append("production: added " + ", ".join(f"{k} = {v}" for k, v in added.items()))
        if "texts" in settings:
            texts = json.loads(json.dumps(settings["texts"].value))
            new_texts = _cfg(config_dir, "texts.json")
            for lang, t in texts.items():
                if lang in new_texts and t.get("proof_footer") == OLD_PROOF_FOOTERS.get(lang):
                    t["proof_footer"] = new_texts[lang]["proof_footer"]
                    changes.append(f"texts ({lang}): holographic note removed from the proof footer")
                if lang in new_texts and isinstance(t.get("finishes"), dict):
                    t["finishes"] = {**t["finishes"], "matte": new_texts[lang]["finishes"]["matte"]}
            put("texts", texts)

        # Listings: new pack ids, kept prices, shop name, shipping time
        if "listings" in settings:
            new = _cfg(config_dir, "listings.json")
            cur = dict(settings["listings"].value)
            old_prices = cur.get("prices") or {}
            cur["pack_short"] = dict(new["pack_short"])
            cur["pack_code"] = dict(new["pack_code"])
            cur["prices"] = {pid: str(old_prices.get(pid, "")) for pid in new["prices"]}
            kept = [pid for pid in new["prices"] if str(old_prices.get(pid, "")).strip()]
            changes.append("listings: bundles " + ", ".join(new["prices"])
                           + (f" (prices kept: {', '.join(kept)})" if kept else " (no prices to keep)"))
            if not str(cur.get("shop_name", "")).strip():
                cur["shop_name"] = new["shop_name"]
                changes.append(f"listings: shop name set to {new['shop_name']}")
            if "ship_time" not in cur:
                cur["ship_time"] = new["ship_time"]
                changes.append(f"listings: shipping time added ({new['ship_time']})")
            put("listings", cur)

        # presets: the strip sizes now have a fixed name position, so their saved crops are archived
        for p in list(s.scalars(select(PresetRow))):
            if p.size_id in FIXED_NAME_SIZES:
                s.add(ArchivedPresetRow(design_id=p.design_id, size_id=p.size_id, data=p.data,
                                        reason=FIXED_NAME_NOTE))
                s.delete(p)
                changes.append(f"preset {p.design_id}/{p.size_id}: archived ({FIXED_NAME_NOTE})")
        s.commit()
    return changes
