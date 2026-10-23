"""Where the engine gets artwork and fonts from.

The engine never touches storage directly; it asks an `Assets` object. The CLI
uses `LocalAssets` (a folder on disk); the web app supplies its own.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

from PIL import Image

from .art import ArtError, trim_white_bands
from .config import FontSpec, Source

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


class Assets(Protocol):
    def art(self, design_id: str, source: Source) -> Image.Image:
        """The artwork ready to crop (the wide image already trimmed)."""

    def art_version(self, design_id: str, source: Source) -> str:
        """A short hash that changes when the artwork changes (for render caching)."""

    def art_sources(self, design_id: str) -> dict[str, tuple[int, int]]:
        """{source: (w, h)} of the available (trimmed) artwork."""

    def font_path(self, spec: FontSpec) -> Path:
        ...


def font_dir_name(spec: FontSpec) -> str:
    return spec.repo_dir.split("/")[-1]


class LocalAssets:
    """Folder layout::

        <root>/designs/<id>/<id>_wide.jpg      original upload
        <root>/designs/<id>/<id>_wide_trimmed.png   created on first use
        <root>/designs/<id>/<id>_square.jpg
        <root>/fonts/<repo dir name>/<file> + licence
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._img_cache: dict[tuple[str, str], Image.Image] = {}
        self._ver_cache: dict[tuple[str, str], str] = {}

    def design_dir(self, design_id: str) -> Path:
        return self.root / "designs" / design_id

    def original_path(self, design_id: str, source: Source) -> Path | None:
        d = self.design_dir(design_id)
        for ext in IMAGE_EXTS:
            p = d / f"{design_id}_{source}{ext}"
            if p.exists():
                return p
        return None

    def _prepared_path(self, design_id: str, source: Source) -> Path:
        orig = self.original_path(design_id, source)
        if orig is None:
            raise ArtError(f"Design '{design_id}' is missing its {source} artwork "
                           f"({design_id}_{source}.jpg).")
        if source != "wide":
            return orig
        trimmed = orig.with_name(f"{design_id}_wide_trimmed.png")
        if not trimmed.exists() or trimmed.stat().st_mtime < orig.stat().st_mtime:
            with Image.open(orig) as im:
                trim_white_bands(im.convert("RGB")).save(trimmed)
        return trimmed

    def art(self, design_id: str, source: Source) -> Image.Image:
        key = (design_id, source)
        p = self._prepared_path(design_id, source)
        ver = self.art_version(design_id, source)
        cached = self._img_cache.get(key)
        if cached is not None and cached.info.get("_ver") == ver:
            return cached
        with Image.open(p) as im:
            img = im.convert("RGB")
        img.info["_ver"] = ver
        self._img_cache[key] = img
        return img

    def art_version(self, design_id: str, source: Source) -> str:
        p = self._prepared_path(design_id, source)
        st = p.stat()
        key = (design_id, source)
        tag = f"{p}:{st.st_mtime_ns}:{st.st_size}"
        cached = self._ver_cache.get(key)
        if cached and cached.startswith(tag + "|"):
            return cached.split("|", 1)[1]
        h = hashlib.sha1(p.read_bytes()).hexdigest()[:12]
        self._ver_cache[key] = f"{tag}|{h}"
        return h

    def art_sources(self, design_id: str) -> dict[str, tuple[int, int]]:
        out = {}
        for src in ("wide", "square"):
            if self.original_path(design_id, src) is not None:  # type: ignore[arg-type]
                # the size is in the file's header: no need to decode (and keep) the whole image
                with Image.open(self._prepared_path(design_id, src)) as im:  # type: ignore[arg-type]
                    out[src] = im.size
        return out

    def font_path(self, spec: FontSpec) -> Path:
        return self.root / "fonts" / font_dir_name(spec) / spec.file
