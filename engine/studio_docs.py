"""Studio instructions in French (with the English UI label in brackets), from one label dictionary.

config/studio_labels.json holds every Silhouette Studio interface label the app writes; labels
not yet confirmed on screen are marked ⚠ wherever they appear.
"""
from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .config import Catalog
from .layout import current_layout
from .templates import info


def studio_labels(config_dir: Path) -> dict[str, dict]:
    return json.loads((Path(config_dir) / "studio_labels.json").read_text(encoding="utf-8"))["labels"]


def label_fn(labels: dict[str, dict], markdown: bool = True):
    """L('key') -> "Français (English)", bold in Markdown, with ⚠ when not yet confirmed."""
    def L(key: str) -> str:
        if key not in labels:
            raise KeyError(f"Studio label '{key}' is missing from config/studio_labels.json.")
        lab = labels[key]
        warn = " ⚠" if lab["status"] == "check" else ""
        fr = f"**{lab['fr']}**" if markdown else lab["fr"]
        return f"{fr}{warn}" if lab["fr"] == lab["en"] else f"{fr} ({lab['en']}){warn}"
    return L


def setup_doc(cat: Catalog, config_dir: Path, layouts_dir: Path) -> str:
    labels = studio_labels(config_dir)
    env = Environment(loader=FileSystemLoader(str(Path(config_dir) / "templates")), undefined=StrictUndefined,
                      keep_trailing_newline=True)
    layouts = [info(current_layout(cat.sheet, s, layouts_dir), s, cat.sheet) for s in cat.sizes.values()]
    return env.get_template("studio_template_setup.md.j2").render(
        L=label_fn(labels), labels=labels, sheet=cat.sheet, layouts=layouts)
