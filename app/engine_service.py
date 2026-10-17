"""The engine, wired to the database and blob storage.

One `EngineService` per process. It keeps a renderer (and its label cache) alive
across requests and rebuilds its catalogue snapshot whenever the repo changes.
Rendering is serialised with a lock: this is a single-user app and the engine's
caches are not thread-safe.
"""
from __future__ import annotations

import io
import logging
import threading
from collections import OrderedDict
from pathlib import Path

from PIL import Image

from engine.art import ArtError
from engine.assets import font_dir_name
from engine.config import Catalog, FontSpec
from engine.fonts_download import download_font
from engine.production import Producer
from engine.render import Renderer
from engine.text import FontError, FontLibrary
from engine.uifont import UI_FONT_ID, UIFonts, ui_font_paths

from .repo import Repo
from .storage import BlobStore

log = logging.getLogger(__name__)


class AppAssets:
    """engine.assets.Assets on top of the repo / blob store, with small in-memory caches."""

    def __init__(self, repo: Repo, store: BlobStore, cache_dir: Path):
        self.repo = repo
        self.store = store
        self.cache_dir = cache_dir
        self.index: dict[str, dict[str, tuple[str, int, int]]] = {}
        self._imgs: OrderedDict[tuple[str, str, str], Image.Image] = OrderedDict()

    def refresh(self) -> None:
        self.index = self.repo.art_index()

    def _entry(self, design_id: str, source: str) -> tuple[str, int, int]:
        e = self.index.get(design_id, {}).get(source)
        if e is None:
            raise ArtError(f"Design '{design_id}' has no {source} artwork yet. Upload it in the design library.")
        return e

    def art(self, design_id, source):
        ver = self._entry(design_id, source)[0]
        key = (design_id, source, ver)
        im = self._imgs.get(key)
        if im is None:
            data = self.repo.art_bytes(design_id, source, "prepared")
            im = Image.open(io.BytesIO(data)).convert("RGB")
            self._imgs[key] = im
            while len(self._imgs) > 24:
                self._imgs.popitem(last=False)
        else:
            self._imgs.move_to_end(key)
        return im

    def art_version(self, design_id, source) -> str:
        return self._entry(design_id, source)[0]

    def art_sources(self, design_id):
        return {src: (w, h) for src, (_, w, h) in self.index.get(design_id, {}).items()}

    # fonts: blob storage is the source of truth; a local copy is kept for FreeType
    def font_key(self, spec: FontSpec, name: str | None = None) -> str:
        return f"fonts/{font_dir_name(spec)}/{name or spec.file}"

    def font_path(self, spec: FontSpec) -> Path:
        local = self.cache_dir / "fonts" / font_dir_name(spec) / spec.file
        if not local.exists():
            key = self.font_key(spec)
            if not self.store.exists(key):
                raise FontError(f"Font {spec.id} ({spec.name}) is not installed. Open the Fonts page and "
                                "download the fonts.")
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(self.store.get(key))
        return local


class EngineService:
    def __init__(self, repo: Repo, store: BlobStore, cache_dir: Path, config_dir: Path):
        self.repo = repo
        self.store = store
        self.cache_dir = cache_dir
        self.config_dir = config_dir
        self.lock = threading.RLock()
        self.assets = AppAssets(repo, store, cache_dir)
        self._version = -1
        self._renderer: Renderer | None = None
        self._ui: UIFonts | None = None

    def _sync(self) -> None:
        if self._version == self.repo.version and self._renderer is not None:
            return
        cat = self.repo.catalog()
        self.assets.refresh()
        if self._renderer is None:
            self._renderer = Renderer(cat, self.assets, FontLibrary(cat.fonts, self.assets.font_path))
        else:
            # keep the label cache: its keys include everything that affects a render
            self._renderer.cat = cat
            if self._renderer.fonts.specs != cat.fonts:
                self._renderer.fonts = FontLibrary(cat.fonts, self.assets.font_path)
        self._version = self.repo.version

    @property
    def catalog(self) -> Catalog:
        with self.lock:
            self._sync()
            assert self._renderer is not None
            return self._renderer.cat

    @property
    def renderer(self) -> Renderer:
        self._sync()
        assert self._renderer is not None
        return self._renderer

    @property
    def ui(self) -> UIFonts:
        if self._ui is None:
            cat = self.catalog
            nunito = self.assets.font_path(cat.fonts[UI_FONT_ID])
            self._ui = UIFonts(ui_font_paths(nunito, self.cache_dir / "ui-fonts"))
        return self._ui

    def texts(self) -> dict:
        return self.repo.setting("texts")

    def producer(self) -> Producer:
        return Producer(self.renderer, self.ui, self.texts(), self.config_dir / "templates")

    # -- fonts -------------------------------------------------------------
    def font_status(self) -> list[dict]:
        cat = self.catalog
        present = set(self.store.list("fonts/"))
        out = []
        for spec in cat.fonts.values():
            d = font_dir_name(spec)
            lic = [k.split("/")[-1] for k in present if k.startswith(f"fonts/{d}/") and not k.endswith(".ttf")]
            out.append({"id": spec.id, "name": spec.name, "file": spec.file, "weight": spec.weight,
                        "mini_ok": spec.mini_ok, "installed": self.assets.font_key(spec) in present,
                        "licence": lic[0] if lic else None, "repo_dir": spec.repo_dir})
        return out

    def download_fonts(self, force: bool = False) -> list[str]:
        """Download missing fonts (+ licences) and copy them into blob storage."""
        report = []
        tmp = self.cache_dir / "font-download"
        for spec in self.catalog.fonts.values():
            if not force and self.store.exists(self.assets.font_key(spec)):
                report.append(f"{spec.id} {spec.name}: already installed")
                continue
            try:
                path, msg = download_font(spec, tmp, force=True)
                for f in path.parent.iterdir():
                    self.store.put(self.assets.font_key(spec, f.name), f.read_bytes())
                local = self.cache_dir / "fonts" / font_dir_name(spec) / spec.file
                if local.exists():
                    local.unlink()
                report.append(f"{spec.id} {spec.name}: {msg}")
            except Exception as e:
                log.exception("font download failed")
                report.append(f"{spec.id} {spec.name}: FAILED ({e})")
        with self.lock:
            if self._renderer is not None:
                self._renderer.fonts = FontLibrary(self.catalog.fonts, self.assets.font_path)
            self._ui = None
        return report
