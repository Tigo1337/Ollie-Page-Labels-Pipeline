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
    want = {file_name(lay.layout_id, k) for lay in LAYOUTS.values() for k in KINDS}
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
