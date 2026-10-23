"""Etsy listings in the app: the editable setting, the listing images job and the CSV.

Images are rendered in a background thread (about 20 s per listing), kept in blob storage under
listings/<file>, and uploaded to Cloudflare R2 when the R2_* secrets are set, so the CSV's image
URLs work as soon as it is downloaded. Without R2, download the images ZIP and host them yourself
at `asset_base_url`.
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import logging
import re
import secrets
import threading
import zipfile

from engine.config import Catalog
from engine.listing_images import ListingImages
from engine.listings import (ETSY_MAX_TAGS, IMAGE_VARIANTS, Group, asset_name, build_csv, description, groups_of,
                             image_files, problems, render_title)

from .r2 import R2Config, R2Error, purge_cdn, put_object
from .repo import Repo
from .storage import BlobNotFound, BlobStore

log = logging.getLogger(__name__)

PREFIX = "listings/"
INDEX_KEY = PREFIX + "index.json"
FILE_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}\.png$")
GROUP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
GROUP_CODE_RE = re.compile(r"^[A-Z0-9]{1,8}$")
EDITABLE = ("shop_name", "ship_time", "sku_prefix", "asset_prefix", "asset_base_url", "sample_names", "pack_short", "pack_code", "prices",
            "csv", "variation_names", "personalization", "title_template", "tags_base", "description_template",
            "groups")
CSV_NAME = "etsy_import_labels.csv"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def validate(current: dict, body: dict, cat: Catalog) -> dict:
    """The new listings setting: `current` with the editable keys of `body`, checked for shape.
    Missing prices and designs in no listing are allowed (they show up as problems, not errors)."""
    if not isinstance(body, dict):
        raise ValueError("The listings could not be read.")
    cfg = dict(current)
    for k in EDITABLE:
        if k in body:
            cfg[k] = body[k]
    for k in ("pack_short", "pack_code", "prices", "csv", "variation_names", "personalization"):
        if not isinstance(cfg.get(k), dict):
            raise ValueError(f"'{k}' must be a set of fields.")
    cfg["prices"] = {str(k): str(v).strip() for k, v in cfg["prices"].items()}
    cfg["csv"] = {str(k): str(v).strip() for k, v in cfg["csv"].items()}
    for k in ("sku_prefix", "asset_prefix"):
        if not re.fullmatch(r"[A-Za-z0-9]{1,12}", str(cfg.get(k, ""))):
            raise ValueError(f"'{k}' must be 1-12 letters or digits.")
    cfg["shop_name"] = str(cfg.get("shop_name", "")).strip()
    if len(cfg["shop_name"]) > 60:
        raise ValueError("The shop name can be at most 60 characters.")
    cfg["ship_time"] = str(cfg.get("ship_time", "")).strip()
    if len(cfg["ship_time"]) > 40:
        raise ValueError("The shipping time can be at most 40 characters (e.g. 3-5 business days).")
    cfg["asset_base_url"] = str(cfg.get("asset_base_url", "")).strip()
    if cfg["asset_base_url"] and not cfg["asset_base_url"].startswith(("https://", "http://")):
        raise ValueError("Where the images are hosted must be a web address starting with https://.")
    for k in ("sample_names", "tags_base"):
        if not isinstance(cfg.get(k), list) or not all(isinstance(x, str) for x in cfg[k]):
            raise ValueError(f"'{k}' must be a list of words.")
    if not isinstance(cfg.get("groups"), list):
        raise ValueError("The listings could not be read (groups).")
    ids, codes, groups = set(), set(), []
    for g in cfg["groups"]:
        if not isinstance(g, dict):
            raise ValueError("A listing could not be read.")
        name = str(g.get("name", "")).strip()
        gid, code = str(g.get("id", "")), str(g.get("code", "")).strip().upper()
        if not name or len(name) > 60:
            raise ValueError("Every listing needs a name (at most 60 characters).")
        if not GROUP_ID_RE.fullmatch(gid):
            raise ValueError(f"Listing '{name}': the id must be lowercase letters, digits and dashes.")
        if not GROUP_CODE_RE.fullmatch(code):
            raise ValueError(f"Listing '{name}': the SKU code must be 1-8 capital letters or digits.")
        if gid in ids or code in codes:
            raise ValueError(f"Two listings use the id '{gid}' or the SKU code '{code}'.")
        ids.add(gid)
        codes.add(code)
        designs, tags = g.get("designs", []), g.get("tags", [])
        if not isinstance(designs, list) or not all(isinstance(d, str) for d in designs):
            raise ValueError(f"Listing '{name}': the designs could not be read.")
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags) or len(tags) > ETSY_MAX_TAGS:
            raise ValueError(f"Listing '{name}': at most {ETSY_MAX_TAGS} tags.")
        groups.append({"id": gid, "code": code, "name": name, "designs": designs,
                       "tags": [t.strip() for t in tags if t.strip()]})
    cfg["groups"] = groups
    probe = groups_of(cfg)[0] if groups else Group("x", "X", "Example", [], [])
    for label, fn in (("title", lambda: render_title(cfg, probe)), ("description", lambda: description(cfg, cat, probe))):
        try:
            fn()
        except KeyError as e:
            raise ValueError(f"The {label} template has an unknown placeholder {{{e.args[0]}}}.") from e
        except (ValueError, IndexError) as e:
            raise ValueError(f"The {label} template could not be filled in ({e}). Write a literal brace as "
                             "{{ or }}.") from e
    return cfg


class Listings:
    def __init__(self, repo: Repo, svc, store: BlobStore, env=None):
        self.repo = repo
        self.svc = svc
        self.store = store
        self.env = env
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.last_id: str | None = None

    # -- settings ----------------------------------------------------------------
    def cfg(self) -> dict:
        return self.repo.setting("listings")

    def save(self, body: dict) -> dict:
        cfg = validate(self.cfg(), body, self.svc.catalog)
        self.repo.set_setting("listings", cfg)
        return cfg

    def r2(self) -> R2Config | None:
        return R2Config.from_env() if self.env is None else R2Config.from_env(self.env)

    def asset_base(self, cfg: dict) -> str:
        r2 = self.r2()
        return r2.public_base if r2 else cfg.get("asset_base_url", "").rstrip("/")

    # -- image index ---------------------------------------------------------------
    def index(self) -> dict[str, dict]:
        try:
            return json.loads(self.store.get(INDEX_KEY))
        except (BlobNotFound, ValueError):
            return {}

    def _record(self, name: str, **fields) -> None:
        with self._lock:
            idx = self.index()
            idx[name] = {**idx.get(name, {}), **fields}
            self.store.put(INDEX_KEY, json.dumps(idx, indent=1).encode())

    def image_bytes(self, name: str) -> bytes:
        if not FILE_RE.fullmatch(name):
            raise BlobNotFound("No such listing image.")
        return self.store.get(PREFIX + name)

    # -- status ----------------------------------------------------------------------
    def status(self) -> dict:
        cfg = self.cfg()
        cat = self.svc.catalog
        idx = self.index()
        r2 = self.r2()
        groups, notes, without = [], [], []
        for g in groups_of(cfg):
            imgs = [{"file": f, "variant": v, **idx.get(f, {})} for f, v in image_files(cfg, g)]
            groups.append({"id": g.id, "title": render_title(cfg, g), "images": imgs})
            missing = [i["variant"] for i in imgs if "generated_at" not in i]
            if len(missing) >= len(imgs) - 1:              # only the shared font chart, or nothing
                without.append(g.name)
            elif missing:
                notes.append(f"'{g.name}' is missing some images ({', '.join(missing)}).")
            elif r2 and any(i.get("uploaded_at", "") < i["generated_at"] for i in imgs):
                notes.append(f"'{g.name}': some images are not uploaded to R2 yet.")
        if without:
            notes.insert(0, f"No images yet for {len(without)} listing(s): {', '.join(without)}.")
        assigned = {d for g in cfg["groups"] for d in g["designs"]}
        return {
            "cfg": cfg,
            "problems": problems(cfg, cat, self.asset_base(cfg)),
            "image_notes": notes,
            "groups": groups,
            "unassigned": [d for d in cat.designs if d not in assigned],
            "designs": {d.id: d.name for d in cat.designs.values()},
            "asset_base": self.asset_base(cfg),
            "r2": {"configured": r2 is not None, "public_base": r2.public_base if r2 else None,
                   "cdn_purge": bool(r2 and r2.cf_token and r2.cf_zone)},
            "job": self.latest(),
        }

    # -- CSV and ZIP ------------------------------------------------------------------
    def csv(self, group_ids: list[str] | None = None) -> str:
        cfg = self.cfg()
        return build_csv(cfg, self.svc.catalog, self.asset_base(cfg), group_ids)

    def zip_bytes(self) -> bytes:
        """Every generated listing image, plus the CSV when the listings are ready."""
        cfg = self.cfg()
        buf = io.BytesIO()
        names = sorted({f for g in groups_of(cfg) for f, _ in image_files(cfg, g)})
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:     # PNGs do not compress further
            for n in names:
                if self.store.exists(PREFIX + n):
                    z.writestr(f"images/{n}", self.store.get(PREFIX + n))
            if not problems(cfg, self.svc.catalog, self.asset_base(cfg)):
                z.writestr(CSV_NAME, self.csv())
        return buf.getvalue()

    # -- background job -----------------------------------------------------------------
    def start(self, group_ids: list[str] | None = None, upload_only: bool = False) -> dict:
        cfg = self.cfg()
        groups = [g for g in groups_of(cfg) if group_ids is None or g.id in group_ids]
        if group_ids is not None and not groups:
            raise ValueError("None of those listings exist.")
        r2 = self.r2()
        if upload_only and r2 is None:
            raise ValueError("R2 is not set up: add the R2_* secrets in Replit, then restart the app.")
        work = [(g, v) for g in groups for v, shared, _ in IMAGE_VARIANTS if not shared] + [(None, "Fonts")]
        with self._lock:
            if any(j["status"] == "running" for j in self._jobs.values()):
                raise ValueError("Listing images are already being made. Wait for them to finish.")
            job_id = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
            job = {"id": job_id, "status": "running", "mode": "upload" if upload_only else "render", "done": 0,
                   "total": len(work), "current": "", "errors": [], "uploaded": 0, "purged": None,
                   "started_at": _now(), "finished_at": None}
            self._jobs[job_id] = job
            self.last_id = job_id
        threading.Thread(target=self._run, args=(job, cfg, work, r2, upload_only), daemon=True).start()
        return dict(job)

    def _run(self, job: dict, cfg: dict, work: list[tuple[Group | None, str]], r2: R2Config | None,
             upload_only: bool) -> None:
        urls: list[str] = []
        purge_with = r2
        try:
            for g, variant in work:
                name = asset_name(cfg, g, variant)
                job["current"] = f"{g.name if g else 'All listings'} · {variant.replace('_', ' ')}"
                try:
                    if upload_only:
                        data = self.store.get(PREFIX + name)
                    else:
                        data = self._render(cfg, g, variant)
                        self.store.put(PREFIX + name, data)
                        self._record(name, generated_at=_now(), bytes=len(data))
                except BlobNotFound:
                    job["errors"].append(f"{name}: not generated yet.")
                    continue
                except Exception as e:  # noqa: BLE001 - one bad design must not stop the other listings
                    log.exception("Listing image %s failed", name)
                    job["errors"].append(f"{name}: {e}")
                    continue
                finally:
                    job["done"] += 1
                if r2 is not None:
                    try:
                        urls.append(put_object(r2, name, data))
                        self._record(name, uploaded_at=_now(), url=urls[-1])
                        job["uploaded"] += 1
                    except R2Error as e:
                        job["errors"].append(f"{e} The other images are kept here; upload them again later.")
                        r2 = None
            if urls and purge_with is not None:
                job["purged"] = purge_cdn(purge_with, urls)
            job["status"] = "done"
        except Exception as e:  # noqa: BLE001
            log.exception("Listing images job failed")
            job.update(status="error", errors=job["errors"] + [f"The job stopped ({type(e).__name__})."])
        finally:
            job["finished_at"] = _now()
            job["current"] = ""

    def _render(self, cfg: dict, g: Group | None, variant: str) -> bytes:
        s = self.svc
        with s.lock:
            img = ListingImages(s.renderer, s.ui, cfg, s.texts(), s.layouts_dir).image(variant, g)
        buf = io.BytesIO()
        img.save(buf, format="PNG", compress_level=6)
        return buf.getvalue()

    def get(self, job_id: str) -> dict | None:
        job = self._jobs.get(job_id)
        return dict(job, errors=list(job["errors"])) if job else None

    def latest(self) -> dict | None:
        return self.get(self.last_id) if self.last_id else None
