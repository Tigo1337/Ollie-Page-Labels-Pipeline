import hashlib
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from engine.config import Design, load_catalog
from engine.fonts_download import download_all
from engine.testart import write_design_art, write_solid_art
from engine.workspace import REPO, open_workspace

FONTS = REPO / "data" / "fonts"


@pytest.fixture(scope="session")
def fonts_dir():
    cat = load_catalog(REPO / "config")
    missing = [f for f in cat.fonts.values() if not (FONTS / f.repo_dir.split("/")[-1] / f.file).exists()]
    if missing:
        report = download_all(cat.fonts, FONTS)
        assert not any("FAILED" in r for r in report), "\n".join(report)
    return FONTS


def _write_test_art(root: Path) -> None:
    for design in load_catalog(REPO / "config").designs.values():
        write_design_art(design, root)
    write_solid_art("solid", root)


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory, fonts_dir, request):
    """Placeholder art for every design. Making it takes ~10 s, so it is kept in pytest's cache between
    runs, under a key that changes with the art generator and the designs (each run gets its own copy)."""
    d = tmp_path_factory.mktemp("data")
    os.symlink(fonts_dir, d / "fonts")
    cache = getattr(request.config, "cache", None)
    if cache is None:                                    # -p no:cacheprovider
        _write_test_art(d)
        return d
    key = hashlib.sha1(b"".join(p.read_bytes() for p in (REPO / "engine" / "testart.py",
                                                         REPO / "config" / "designs.json"))).hexdigest()[:12]
    stored = cache.mkdir("test-art") / key
    if not stored.is_dir():
        tmp = Path(tempfile.mkdtemp(dir=stored.parent))
        _write_test_art(tmp)
        try:
            tmp.rename(stored)
        except OSError:                                  # another run stored it first
            shutil.rmtree(tmp, ignore_errors=True)
        for old in stored.parent.iterdir():              # drop art for older keys
            if old.name != key and not old.name.startswith("tmp"):
                shutil.rmtree(old, ignore_errors=True)
    shutil.copytree(stored / "designs", d / "designs")
    return d


@pytest.fixture(scope="session")
def ws(data_dir):
    cat = load_catalog(REPO / "config")
    cat.designs["solid"] = Design(id="solid", name="Solid test", fill="#FFFFFF", stroke="#000000", char_end=0.2)
    return open_workspace(REPO / "config", data_dir, catalog=cat)


def fresh_ws(ws, **kw):
    """Same data, new renderer (empty cache)."""
    return open_workspace(REPO / "config", Path(ws.assets.root), catalog=ws.catalog, **kw)
