"""Golden test: one order that renders every size with a short, a long and a two-line
name. Snapshots output dimensions and label counts (not pixels).

To refresh after an intended change: UPDATE_GOLDEN=1 pytest tests/test_golden.py
"""
import json
import os
import time
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from engine.orders import Order, OrderLine

from .conftest import fresh_ws

GOLDEN = Path(__file__).parent / "golden" / "every_size.json"


def golden_order():
    lines = []
    for name, l2, font in (("Léo", "", 1), ("Maximilien-Alexandre", "", 3), ("Alexandre", "Tremblay-Gagnon", 7)):
        lines.append(OrderLine("dino", "school", "gloss", name, l2, font))
        lines.append(OrderLine("dino", "large22", "gloss", name, l2, font))
        lines.append(OrderLine("dino", "daycare", "gloss", name, l2, font))
    lines.append(OrderLine("space-cat", "starter", "matte", "Zoë", "", 4))
    return Order("golden", lines)


def snapshot(res, out: Path) -> dict:
    snap = {"finishes": res.summary["finishes"], "pages": [], "labels": {}, "pdf_pages": {}, "files": []}
    for sh in res.summary["sheets"]:
        snap["pages"].append({"n": sh["n"], "finish": sh["finish"], "layout_id": sh["layout_id"],
                              "pdf": sh["pdf"], "page": sh["page"],
                              "top": [sh["top"]["name"], sh["top"]["index"], sh["top"]["bonus"]],
                              "bottom": [sh["bottom"]["name"], sh["bottom"]["index"], sh["bottom"]["bonus"]]
                              if sh["bottom"] else None,
                              "proof_px": list(Image.open(out / sh["proof"]).size)})
    for key, lab in sorted(res.labels.items()):
        snap["labels"][key] = {"px": list(lab.image.size), "cap_mm": [round(c, 2) for c in lab.cap_mm]}
    for f in sorted(res.files):
        if f.suffix == ".pdf" and f.name.endswith("_print.pdf"):
            doc = pdfium.PdfDocument(str(f))
            snap["pdf_pages"][f.name] = [[round(v, 2) for v in doc[i].get_mediabox()] + [doc[i].get_rotation()]
                                         for i in range(len(doc))]
    snap["files"] = sorted(f.name for f in res.files)
    return snap


def test_golden_every_size(ws, tmp_path):
    res = ws.producer.run([golden_order()], tmp_path)
    snap = snapshot(res, tmp_path)
    if os.environ.get("UPDATE_GOLDEN") or not GOLDEN.exists():
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(snap, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert snap["finishes"] == expected["finishes"]
    assert snap["pages"] == expected["pages"]
    assert snap["pdf_pages"] == expected["pdf_pages"]
    assert snap["files"] == expected["files"]
    assert set(snap["labels"]) == set(expected["labels"])
    for k, v in expected["labels"].items():
        assert snap["labels"][k]["px"] == v["px"]
        # cap heights may drift by a hair between FreeType builds
        for a, b in zip(snap["labels"][k]["cap_mm"], v["cap_mm"]):
            assert abs(a - b) <= 0.05, (k, a, b)


def test_school_pack_under_10_seconds(ws, tmp_path):
    """The 132-label budget of the spec, on today's biggest pack (96 labels + 8 shoe pairs)."""
    w = fresh_ws(ws)  # empty render cache
    order = Order("speed", [OrderLine("fox", "school", "holographic", "Maximilien", "", 2)])
    t = time.perf_counter()
    res = w.producer.run([order], tmp_path)
    dt = time.perf_counter() - t
    # printed alone: each half gets a bonus copy, so 2 × (96 labels + 16 shoe labels)
    assert res.summary["finishes"]["holographic"] == {"sheets": 5, "labels": 2 * (96 + 16)}
    assert dt < 10, f"took {dt:.1f} s"


def test_render_cache_hits(ws):
    from engine.render import LabelSpec
    a = ws.renderer.render(LabelSpec("bee", "small", "Léo", "", 1))
    b = ws.renderer.render(LabelSpec("bee", "small", " Léo ", "", 1))
    assert a is b
