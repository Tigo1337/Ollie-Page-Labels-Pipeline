import os
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


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory, fonts_dir):
    d = tmp_path_factory.mktemp("data")
    os.symlink(fonts_dir, d / "fonts")
    cat = load_catalog(REPO / "config")
    for design in cat.designs.values():
        write_design_art(design, d)
    write_solid_art("solid", d)
    return d


@pytest.fixture(scope="session")
def ws(data_dir):
    cat = load_catalog(REPO / "config")
    cat.designs["solid"] = Design(id="solid", name="Solid test", fill="#FFFFFF", stroke="#000000", char_end=0.2)
    return open_workspace(REPO / "config", data_dir, catalog=cat)


def fresh_ws(ws, **kw):
    """Same data, new renderer (empty cache)."""
    return open_workspace(REPO / "config", Path(ws.assets.root), catalog=ws.catalog, **kw)
