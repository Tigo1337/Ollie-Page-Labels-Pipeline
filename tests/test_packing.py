"""Half-sheet batching and the bundle every pack produces."""
import zipfile

import pypdfium2 as pdfium
import pytest

from engine.config import Pack, load_catalog
from engine.orders import Order, OrderError, OrderLine
from engine.packing import PackError, pack_halves, pack_sheets
from engine.workspace import REPO

CAT = load_catalog(REPO / "config")
LAYOUTS = REPO / "layouts"


def plan(ws, orders, unpaired="bonus"):
    return ws.producer.plan(orders, unpaired)[1]


def test_every_pack_is_whole_halves():
    want = {"pencil60": {"pencil": 2}, "small62": {"small": 2}, "medium30": {"medium": 2}, "large22": {"large": 2},
            "tag110": {"tag": 2}, "round40": {"round": 2}, "shoe8": {"shoe": 1},
            "starter": {"pencil": 1, "small": 1}, "daycare": {"small": 1, "tag": 1},
            "school": {"pencil": 1, "small": 1, "medium": 1, "round": 1, "shoe": 1}}
    assert {pid: pack_halves(p, CAT, LAYOUTS) for pid, p in CAT.packs.items()} == want
    assert pack_sheets(CAT.packs["school"], CAT, LAYOUTS) == {"halves": 5, "batched": 2.5, "alone": 5}
    with pytest.raises(PackError, match="whole number of halves"):
        pack_halves(Pack("odd", "odd", {"pencil": 31}), CAT, LAYOUTS)


def test_two_starter_orders_make_one_pencil_and_one_small_sheet(ws):
    orders = [Order("A", [OrderLine("dino", "starter", "matte", "Anna")]),
              Order("B", [OrderLine("fox", "starter", "matte", "Ben")])]
    p = plan(ws, orders)
    assert [(s.size, s.top.order_id, s.bottom.order_id) for s in p.sheets] == [("pencil", "A", "B"),
                                                                              ("small", "A", "B")]
    assert p.waiting == [] and not any(h.bonus for s in p.sheets for h in s.halves)


def test_halves_pair_oldest_first_and_never_mix_sizes_or_finishes(ws):
    orders = [Order("A", [OrderLine("dino", "starter", "matte", "Anna")]),
              Order("B", [OrderLine("dino", "pencil60", "matte", "Ben")]),
              Order("C", [OrderLine("dino", "school", "matte", "Cleo"), OrderLine("dino", "starter", "gloss", "Dan")]),
              Order("D", [OrderLine("dino", "daycare", "matte", "Eve")])]
    p = plan(ws, orders, unpaired="wait")
    pencil = [(s.top.order_id, s.top.index, s.bottom.order_id, s.bottom.index) for s in p.sheets if s.size == "pencil"
              and s.finish == "matte"]
    assert pencil == [("A", 1, "B", 1), ("B", 2, "C", 1)]
    for s in p.sheets:
        for h in s.halves:
            assert h.size == s.size and h.finish == s.finish and h.layout_id == s.layout_id
    assert [s.n for s in p.sheets] == list(range(1, len(p.sheets) + 1))
    small = [(s.top.order_id, s.bottom.order_id) for s in p.sheets if s.size == "small"]
    assert small == [("A", "C")]
    # everything without a partner waits: D's small, the rest of C's school, C's gloss starter, D's tag
    assert sorted((h.order_id, h.size, h.finish) for h in p.waiting) == [
        ("C", "medium", "matte"), ("C", "pencil", "gloss"), ("C", "round", "matte"), ("C", "shoe", "matte"),
        ("C", "small", "gloss"), ("D", "small", "matte"), ("D", "tag", "matte")]
    total = sum(len(s.halves) for s in p.sheets) + len(p.waiting)
    assert total == len(ws.producer.expand(orders).halves)


def test_imprimer_seul_bonus_copy_or_blank(ws):
    order = [Order("A", [OrderLine("dino", "shoe8", "matte", "Anna")])]
    bonus = plan(ws, order, "bonus").sheets[0]
    assert bonus.bottom.bonus and bonus.bottom.key == bonus.top.key and bonus.bottom.order_id == "A"
    blank = plan(ws, order, "blank").sheets[0]
    assert blank.bottom is None
    waiting = plan(ws, order, "wait")
    assert waiting.sheets == [] and [h.size for h in waiting.waiting] == ["shoe"]


@pytest.mark.parametrize("pack", list(CAT.packs))
def test_every_pack_produces_a_working_bundle(ws, tmp_path, pack):
    res = ws.producer.run([Order(f"s-{pack}", [OrderLine("dino", pack, "matte", "Léo", "", 1)])], tmp_path,
                          customer_proofs=False)
    pdfs = [f for f in res.files if f.name.endswith("_print.pdf")]
    assert pdfs
    with zipfile.ZipFile(res.zip_path) as z:
        names = set(z.namelist())
    for sh in res.summary["sheets"]:
        assert {f"templates/{sh['layout_id']}.svg", f"templates/{sh['layout_id']}.dxf"} <= names
        assert sh["pdf"] in names and sh["proof"] in names
    assert {"laminate_notches.dxf", f"s-{pack}_info_sheet.txt", f"s-{pack}_packing_slip.txt"} <= names
    # labels per size = the pack's contents (bonus copies aside)
    got: dict[str, int] = {}
    for sh in res.plan.sheets:
        lay = ws.producer.layouts([sh.size])[sh.size]
        for h in sh.halves:
            assert h.size == sh.size and h.finish == sh.finish
            if not h.bonus:
                got[h.size] = got.get(h.size, 0) + lay.per_half
    assert got == CAT.packs[pack].contents
    pages = sum(len(pdfium.PdfDocument(str(f))) for f in pdfs)
    assert pages == len(res.plan.sheets)


def test_unknown_pack_size_is_a_plain_error(ws, tmp_path):
    import dataclasses
    cat = ws.catalog
    bad = dataclasses.replace(cat.packs["starter"], contents={"pencil": 31})
    cat.packs["bad"] = bad
    try:
        with pytest.raises(OrderError, match="whole number of halves"):
            ws.producer.run([Order("x", [OrderLine("dino", "bad", "matte", "A")])], tmp_path)
    finally:
        del cat.packs["bad"]
