"""Wire the engine together from a config folder and a data folder (used by the CLI and tests)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .assets import Assets, LocalAssets
from .config import Catalog, load_catalog
from .production import Producer
from .render import Renderer
from .text import FontLibrary
from .uifont import UI_FONT_ID, UIFonts, ui_font_paths

REPO = Path(__file__).resolve().parent.parent


@dataclass
class Workspace:
    catalog: Catalog
    assets: Assets
    fonts: FontLibrary
    renderer: Renderer
    ui: UIFonts
    texts: dict
    producer: Producer


def open_workspace(config_dir: str | Path = REPO / "config", data_dir: str | Path = REPO / "data",
                   catalog: Catalog | None = None, assets: Assets | None = None,
                   strategy: str | None = None, layouts_dir: str | Path = REPO / "layouts") -> Workspace:
    config_dir, data_dir = Path(config_dir), Path(data_dir)
    cat = catalog or load_catalog(config_dir)
    assets = assets or LocalAssets(data_dir)
    fonts = FontLibrary(cat.fonts, assets.font_path)
    renderer = Renderer(cat, assets, fonts)
    ui = UIFonts(ui_font_paths(assets.font_path(cat.fonts[UI_FONT_ID]), data_dir / "fonts" / "_ui"))
    texts = json.loads((config_dir / "texts.json").read_text(encoding="utf-8"))
    producer = Producer(renderer, ui, texts, config_dir / "templates", strategy, layouts_dir=Path(layouts_dir),
                        config_dir=config_dir)
    return Workspace(cat, assets, fonts, renderer, ui, texts, producer)
