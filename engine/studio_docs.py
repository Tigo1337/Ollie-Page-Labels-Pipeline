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
    env = _env(config_dir)
    layouts = [info(current_layout(cat.sheet, s, layouts_dir), s, cat.sheet) for s in cat.sizes.values()]
    return env.get_template("studio_template_setup.md.j2").render(
        L=label_fn(labels), labels=labels, sheet=cat.sheet, layouts=layouts)


# ---------------------------------------------------------------------------
# Every generated document: docs/*.md and the generated sections of README.md
# ---------------------------------------------------------------------------
README_BLOCKS = {"layouts": "readme_layouts.md.j2", "print-and-cut": "readme_print_and_cut.md.j2"}
FINISH_SHORT = {"matte": "mat", "gloss": "brillant", "holographic": "holo"}


def _env(config_dir: Path) -> Environment:
    return Environment(loader=FileSystemLoader(str(Path(config_dir) / "templates")), undefined=StrictUndefined,
                       keep_trailing_newline=True)


def render_docs(cat: Catalog, config_dir: Path, layouts_dir: Path) -> dict[str, str]:
    """{"docs/<name>.md" or "README:<block>": text}."""
    labels = studio_labels(config_dir)
    env = _env(config_dir)
    ctx = {"L": label_fn(labels), "labels": labels, "sheet": cat.sheet}
    lays = []
    for s in cat.sizes.values():
        lay = current_layout(cat.sheet, s, layouts_dir)
        lays.append({"layout_id": lay.layout_id, "dims": s.dims_label, "arrangement": lay.arrangement,
                     "per_half": lay.per_half, "per_sheet": lay.per_sheet, "rows": " + ".join(map(str, lay.rows)),
                     "unit": " pairs" if s.shape == "pair" else ""})
    finishes = [{"id": f.id, "label": f.label, "short": FINISH_SHORT.get(f.id, f.id)} for f in cat.finishes.values()]
    out = {
        "docs/studio-template-setup.md": setup_doc(cat, config_dir, layouts_dir),
        "docs/cut-settings.md": env.get_template("cut_settings.md.j2").render(finishes=finishes, **ctx),
    }
    for block, tpl in README_BLOCKS.items():
        out[f"README:{block}"] = env.get_template(tpl).render(layouts=lays, **ctx).strip() + "\n"
    return out


def readme_with_blocks(readme: str, blocks: dict[str, str]) -> str:
    """Replace each generated block between its markers (they must already be in the README)."""
    for name, text in blocks.items():
        begin, end = f"<!-- generated:{name} -->", f"<!-- /generated:{name} -->"
        if begin not in readme or end not in readme:
            raise ValueError(f"README.md has no '{begin}' … '{end}' markers.")
        head, rest = readme.split(begin, 1)
        _, tail = rest.split(end, 1)
        readme = f"{head}{begin}\n{text}{end}{tail}"
    return readme


def write_docs(cat: Catalog, config_dir: Path, layouts_dir: Path, repo_root: Path) -> list[Path]:
    docs = render_docs(cat, config_dir, layouts_dir)
    written = []
    blocks = {k.split(":", 1)[1]: v for k, v in docs.items() if k.startswith("README:")}
    for rel, text in docs.items():
        if rel.startswith("README:"):
            continue
        p = Path(repo_root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        written.append(p)
    readme = Path(repo_root) / "README.md"
    readme.write_text(readme_with_blocks(readme.read_text(encoding="utf-8"), blocks), encoding="utf-8")
    written.append(readme)
    return written
