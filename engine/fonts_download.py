"""Download the Google Fonts TTFs and their licence files."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

from .assets import font_dir_name
from .config import FontSpec

RAW = "https://raw.githubusercontent.com/google/fonts/main/{dir}/{file}"
API = "https://api.github.com/repos/google/fonts/contents/{dir}"
LICENCE_FILES = ("OFL.txt", "LICENSE.txt", "LICENSE")


def _get(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "label-pipeline"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _raw(repo_dir: str, file: str) -> str:
    return RAW.format(dir=repo_dir, file=urllib.parse.quote(file))


def _pick_from_listing(repo_dir: str, wanted: str) -> str | None:
    """The file name changed upstream: list the folder and pick the non-italic TTF."""
    listing = json.loads(_get(API.format(dir=repo_dir)))
    ttfs = [x["name"] for x in listing if x.get("name", "").lower().endswith(".ttf")]
    upright = [n for n in ttfs if "italic" not in n.lower()]
    if not upright:
        return None
    stem = wanted.split("[")[0].split("-")[0].lower()
    upright.sort(key=lambda n: (not n.lower().startswith(stem), "[" not in n, n))
    return upright[0]


def download_font(spec: FontSpec, fonts_root: Path, force: bool = False) -> tuple[Path, str]:
    """Returns (path, message). Does not raise on network errors for the licence."""
    d = fonts_root / font_dir_name(spec)
    d.mkdir(parents=True, exist_ok=True)
    target = d / spec.file
    if target.exists() and not force:
        return target, "already present"
    try:
        data = _get(_raw(spec.repo_dir, spec.file))
        msg = "downloaded"
    except Exception:
        alt = _pick_from_listing(spec.repo_dir, spec.file)
        if alt is None:
            raise
        data = _get(_raw(spec.repo_dir, alt))
        msg = f"upstream file renamed to {alt}; saved as {spec.file}"
    target.write_bytes(data)
    for lic in LICENCE_FILES:
        try:
            (d / lic).write_bytes(_get(_raw(spec.repo_dir, lic)))
            break
        except Exception:
            continue
    else:
        msg += " (licence file not found!)"
    return target, msg


def download_all(fonts: dict[int, FontSpec], fonts_root: Path, force: bool = False) -> list[str]:
    report = []
    for spec in fonts.values():
        try:
            _, msg = download_font(spec, fonts_root, force)
            report.append(f"{spec.id:>2} {spec.name}: {msg}")
        except Exception as e:  # keep going; report the failure plainly
            report.append(f"{spec.id:>2} {spec.name}: FAILED ({e})")
    return report
