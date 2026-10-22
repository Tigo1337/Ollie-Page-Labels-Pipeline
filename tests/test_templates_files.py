"""Template files: SVG structure, DXF rules, committed files and docs are up to date."""
import math
import re
import xml.etree.ElementTree as ET

import pytest

from engine.config import load_catalog
from engine.layout import current_layout
from engine.studio_docs import setup_doc, studio_labels
from engine.templates import CHORD_TOL, KINDS, cut_shapes, file_name, flatten
from engine.workspace import REPO

CAT = load_catalog(REPO / "config")
LAYOUTS = {sid: current_layout(CAT.sheet, s, REPO / "layouts") for sid, s in CAT.sizes.items()}


@pytest.mark.parametrize("sid", list(CAT.sizes))
def test_svg_structure(sid):
    lay = LAYOUTS[sid]
    text = (REPO / "templates" / file_name(lay.layout_id, "svg")).read_text()
    root = ET.fromstring(text)
    ns = "{http://www.w3.org/2000/svg}"
    groups = root.findall(f"{ns}g")
    assert [g.get("id") for g in groups] == ["cut", "anchors"]
    assert root.findall(f".//{ns}g/{ns}g") == []
    assert "transform" not in text
    cut = groups[0]
    assert cut.get("fill") == "none" and cut.get("stroke") == "#FF0000" and cut.get("stroke-width") == "0.1"
    tags = {el.tag.replace(ns, "") for el in cut}
    want = {"round": {"circle"}, "shoe": {"path"}}.get(sid, {"rect"})
    assert tags == want
    for num in re.findall(r"\d+\.(\d+)", text.split("-->", 1)[1]):
        assert len(num) <= 3
    assert len(groups[1]) == 2


@pytest.mark.parametrize("sid", list(CAT.sizes))
def test_dxf_flattening_stays_within_tolerance(sid):
    size = CAT.sizes[sid]
    for s in cut_shapes(LAYOUTS[sid], size, CAT.sheet)[:3]:
        pts = flatten(s)
        if s.kind == "circle":
            cx, cy = s.x + s.w / 2, s.y + s.h / 2
            assert all(abs(math.hypot(x - cx, y - cy) - s.r) < 1e-9 for x, y in pts)
            seg = 2 * math.pi / len(pts)
            assert s.r * (1 - math.cos(seg / 2)) <= CHORD_TOL <= 0.1
        else:
            assert len(pts) >= 8


def test_templates_folder_has_exactly_the_current_layouts():
    want = {file_name(lay.layout_id, k) for lay in LAYOUTS.values() for k in KINDS} | {"trim_line.svg",
                                                                                     "trim_line.dxf"}
    have = {p.name for p in (REPO / "templates").iterdir()}
    assert have == want


def test_setup_doc_is_up_to_date_and_flags_unsure_labels():
    doc = setup_doc(CAT, REPO / "config", REPO / "layouts")
    assert (REPO / "docs" / "studio-template-setup.md").read_text(encoding="utf-8") == doc, \
        "docs/studio-template-setup.md is out of date: run python -m engine templates"
    labels = studio_labels(REPO / "config")
    unsure = [k for k, v in labels.items() if v["status"] == "check"]
    assert unsure and all(f"`{k}`" in doc for k in unsure)
    assert "**Fusionner…** (Merge…)" in doc and "--no_center" in doc
    for lay in LAYOUTS.values():
        assert lay.layout_id in doc


def test_all_generated_docs_and_readme_sections_are_up_to_date():
    from engine.studio_docs import readme_with_blocks, render_docs
    docs = render_docs(CAT, REPO / "config", REPO / "layouts")
    for rel, text in docs.items():
        if not rel.startswith("README:"):
            assert (REPO / rel).read_text(encoding="utf-8") == text, f"{rel} is out of date: run python -m engine docs"
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    blocks = {k.split(":", 1)[1]: v for k, v in docs.items() if k.startswith("README:")}
    assert readme_with_blocks(readme, blocks) == readme, "README.md is out of date: run python -m engine docs"
    assert "## Imprimer et découper une planche" in readme and "chels-round-v2" in readme


def test_cut_settings_doc():
    doc = (REPO / "docs" / "cut-settings.md").read_text(encoding="utf-8")
    for want in ("**AutoLame** (AutoBlade)", "**Profondeur** (Depth) | 2", "**Force** | 12",
                 "**Vitesse** (Speed) | 4", "**Passages** (Passes) | 1", "**Test de découpe** (Test Cut)",
                 "Chels – vinyle + lam. holo", "**Découper par couleur de ligne** (Cut by Line Color)",
                 "marque le tapis"):
        assert want in doc, want


def test_trim_lines_are_open_blue_cuts_with_anchors():
    import ezdxf
    from engine.templates import trim_line_svg
    svg = ET.fromstring(trim_line_svg(CAT.sheet))
    ns = "{http://www.w3.org/2000/svg}"
    trim = svg.find(f"{ns}g[@id='trim']")
    assert trim.get("stroke") == "#0000FF" and [el.get("d") for el in trim] == ["M93.133 0 V215.9",
                                                                                "M186.267 0 V215.9"]
    doc = ezdxf.readfile(REPO / "templates" / "trim_line.dxf")
    ents = list(doc.modelspace())
    trim_ents = [e for e in ents if e.dxf.layer == "TRIM"]
    assert len(trim_ents) == 2 and not any(e.is_closed for e in trim_ents)
    xs = [{round(v.dxf.location.x, 3) for v in e.vertices} for e in trim_ents]
    assert xs == [{93.133}, {186.267}] and len([e for e in ents if e.dxf.layer == "ANCHOR"]) == 2
