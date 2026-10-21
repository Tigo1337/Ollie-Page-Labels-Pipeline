"""Bulk artwork import from a ZIP of the `Label Designs` folder.

Expected layout (any depth, Windows or Unix separators):
    Label Designs\\<id>\\<id>_wide.jpg
    Label Designs\\<id>\\<id>_square.jpg
Files are matched to designs by their folder name. Anything inside a sub-folder of a design
folder (e.g. Label Designs\\alien\\test-labels\\...) is ignored: it is only counted, not listed.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import BinaryIO

from engine.art import ArtError

from .repo import NotFound, Repo

IMG = re.compile(r"\.(jpe?g|png|webp)$", re.I)
MAX_ZIP_ENTRY = 60 * 1024 * 1024


@dataclass
class ImportReport:
    imported: list[dict] = field(default_factory=list)   # {design, source, file}
    skipped: list[dict] = field(default_factory=list)    # {file, reason}
    unknown_folders: list[str] = field(default_factory=list)
    ignored: int = 0          # files in sub-folders of a design folder (e.g. test-labels/)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def classify(name: str) -> tuple[str, str] | None:
    """('folder', 'wide'|'square') from a path inside the ZIP, or None."""
    parts = [p for p in re.split(r"[\\/]", name) if p]
    if len(parts) < 2 or not IMG.search(parts[-1]) or parts[-1].startswith("._") or "__MACOSX" in parts:
        return None
    stem = IMG.sub("", parts[-1]).lower()
    if stem.endswith("_wide") or stem.endswith("-wide") or stem == "wide":
        return parts[-2], "wide"
    if stem.endswith("_square") or stem.endswith("-square") or stem == "square":
        return parts[-2], "square"
    return None


def import_zip(repo: Repo, data: bytes | BinaryIO) -> ImportReport:
    """`data`: the ZIP's bytes, or a seekable binary file (read one entry at a time)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else data)
    except zipfile.BadZipFile as e:
        raise ValueError("That file is not a ZIP archive.") from e
    designs = {r.id: r for r in repo.design_rows()}
    by_slug = {slug(r.id): r.id for r in designs.values()} | {slug(r.name): r.id for r in designs.values()}
    rep = ImportReport()
    unknown: set[str] = set()
    for info in zf.infolist():
        if info.is_dir():
            continue
        parts = [p for p in re.split(r"[\\/]", info.filename) if p]
        if any(slug(folder) in by_slug for folder in parts[:-2]):
            rep.ignored += 1            # inside a sub-folder of a design folder
            continue
        c = classify(info.filename)
        if c is None:
            if IMG.search(info.filename) and "__MACOSX" not in info.filename:
                rep.skipped.append({"file": info.filename,
                                    "reason": "name does not end in _wide or _square"})
            continue
        folder, source = c
        did = by_slug.get(slug(folder))
        if did is None:
            unknown.add(folder)
            rep.skipped.append({"file": info.filename, "reason": f"no design matches folder '{folder}'"})
            continue
        if info.file_size > MAX_ZIP_ENTRY:
            rep.skipped.append({"file": info.filename, "reason": "file is too large"})
            continue
        try:
            repo.set_art(did, source, zf.read(info), info.filename)
            rep.imported.append({"design": did, "source": source, "file": info.filename})
        except (ArtError, NotFound, ValueError) as e:
            rep.skipped.append({"file": info.filename, "reason": str(e)})
    rep.unknown_folders = sorted(unknown)
    return rep
