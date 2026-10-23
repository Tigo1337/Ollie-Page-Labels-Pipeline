"""Piece batching (three pieces = one sheet), pack math, the envelope estimate, and the bundle every
pack produces."""
import dataclasses
import zipfile

import pypdfium2 as pdfium
import pytest

from engine.config import Pack, load_catalog
from engine.orders import Order, OrderError, OrderLine
from engine.packing import PackError, envelope, pack_pieces, pack_sheets
from engine.workspace import REPO

CAT = load_catalog(REPO / "config")
LAYOUTS = REPO / "layouts"
SIZE_ORDER = list(CAT.sizes)


def plan(ws, orders, unpaired="bonus"):
    return ws.producer.plan(orders, unpaired)[1]


def test_every_pack_is_whole_pieces():
    want = {"pencil51": {"pencil": 3}, "small57": {"small": 3}, "medium24": {"medium": 3}, "large18": {"large": 3},
            "tag102": {"tag": 3}, "round30": {"round": 3}, "shoe12": {"shoe": 3},
            "starter": {"pencil": 1, "small": 2, "medium": 1, "round": 1},
            "daycare": {"tag": 2, "medium": 2, "small": 1, "round": 1, "shoe": 1},
            "school": {"pencil": 3, "small": 3, "medium": 2, "large": 1, "round": 1, "tag": 2, "shoe": 2}}
    assert {pid: pack_pieces(p, CAT, LAYOUTS) for pid, p in CAT.packs.items()} == want
    totals = {pid: sum(v.values()) for pid, v in want.items()}
    assert totals == {"pencil51": 3, "small57": 3, "medium24": 3, "large18": 3, "tag102": 3, "round30": 3,
                      "shoe12": 3, "starter": 5, "daycare": 7, "school": 14}
    school = pack_sheets(CAT.packs["school"], CAT, LAYOUTS)
    assert (school["pieces"], school["batched"], school["alone"]) == (14, round(14 / 3, 3), 7)
    starter = pack_sheets(CAT.packs["starter"], CAT, LAYOUTS)
    assert (starter["pieces"], starter["alone"]) == (5, 4)
    with pytest.raises(PackError, match="whole number of pieces"):
        pack_pieces(Pack("odd", "odd", {"pencil": 18}), CAT, LAYOUTS)


def test_envelope_estimate_and_lettermail_class():
    prod = CAT.production
    assert (prod.piece_weight_g, prod.envelope_weight_g, prod.piece_thickness_mm) == (6.0, 5.0, 0.35)
    assert envelope(3, prod) == {"weight_g": 23.0, "lettermail": "Lettermail, up to 30 g", "thickness_mm": 1.05,
                                 "warning": ""}
    assert envelope(5, prod)["lettermail"] == "Lettermail, up to 50 g"              # starter: 35 g
    assert envelope(7, prod)["weight_g"] == 47.0                                     # daycare
    school = envelope(14, prod)
    assert school["weight_g"] == 89.0 and school["lettermail"] == "Over 50 g (oversized)"
    assert "5 mm" in school["warning"]                                               # above 12 pieces
    assert envelope(12, prod)["warning"] == ""
    heavy = dataclasses.replace(prod, piece_weight_g=10.0)
    assert envelope(3, heavy)["lettermail"] == "Lettermail, up to 50 g"
    assert pack_sheets(CAT.packs["daycare"], CAT, LAYOUTS)["envelope"]["weight_g"] == 47.0


def test_three_starter_orders_fill_only_full_sheets(ws):
    orders = [Order(o, [OrderLine("dino", "starter", "matte", n)]) for o, n in (("A", "Anna"), ("B", "Ben"),
                                                                              ("C", "Cleo"))]
    p = plan(ws, orders)
    sizes = [s.size for s in p.sheets]
    assert {s: sizes.count(s) for s in set(sizes)} == {"pencil": 1, "small": 2, "medium": 1, "round": 1}
    assert p.waiting == []
    for s in p.sheets:
        assert len(s.pieces) == 3 and all(x is not None and not x.bonus for x in s.pieces)
    pencil = next(s for s in p.sheets if s.size == "pencil")
    assert [x.order_id for x in pencil.pieces] == ["A", "B", "C"]
    small = [[(x.order_id, x.index) for x in s.pieces] for s in p.sheets if s.size == "small"]
    assert small == [[("A", 2), ("A", 3), ("B", 2)], [("B", 3), ("C", 2), ("C", 3)]]   # oldest first


def test_one_school_order_printed_alone_is_7_sheets_with_bonus_copies(ws):
    p = plan(ws, [Order("S", [OrderLine("dino", "school", "matte", "Sam")])])
    assert len(p.sheets) == 7 and p.waiting == []
    assert [s.size for s in p.sheets] == [s for s in SIZE_ORDER]          # one sheet per size
    real = {s.size: sum(1 for x in s.pieces if not x.bonus) for s in p.sheets}
    assert real == {"pencil": 3, "small": 3, "medium": 2, "large": 1, "tag": 2, "round": 1, "shoe": 2}
    for s in p.sheets:
        assert all(x is not None for x in s.pieces)
        last_real = [x for x in s.pieces if not x.bonus][-1]
        for x in s.pieces:
            if x.bonus:
                assert x.key == last_real.key and x.index == last_real.index and x.order_id == "S"


def test_pieces_never_mix_sizes_and_fill_oldest_first(ws):
    orders = [Order("A", [OrderLine("dino", "starter", "matte", "Anna")]),
              Order("B", [OrderLine("dino", "pencil51", "matte", "Ben")]),
              Order("C", [OrderLine("dino", "school", "matte", "Cleo")]),
              Order("D", [OrderLine("dino", "daycare", "matte", "Eve")])]
    p = plan(ws, orders, unpaired="wait")
    pencil = [[(x.order_id, x.index) for x in s.pieces] for s in p.sheets if s.size == "pencil"]
    assert pencil == [[("A", 1), ("B", 1), ("B", 2)], [("B", 3), ("C", 1), ("C", 2)]]
    for s in p.sheets:
        for x in s.pieces:
            assert x.size == s.size and x.finish == s.finish and x.layout_id == s.layout_id
    assert [s.n for s in p.sheets] == list(range(1, len(p.sheets) + 1))
    assert sorted((x.order_id, x.size) for x in p.waiting) == [
        ("C", "large"), ("C", "pencil"), ("D", "medium"), ("D", "medium"), ("D", "tag")]
    total = sum(len(s.filled) for s in p.sheets) + len(p.waiting)
    assert total == len(ws.producer.expand(orders).pieces)


def test_bonus_blank_or_wait(ws):
    order = [Order("A", [OrderLine("dino", "daycare", "matte", "Anna")])]
    shoe = next(s for s in plan(ws, order, "bonus").sheets if s.size == "shoe")
    assert not shoe.pieces[0].bonus and shoe.pieces[1].bonus and shoe.pieces[2].bonus
    assert shoe.pieces[1].key == shoe.pieces[0].key
    blank = next(s for s in plan(ws, order, "blank").sheets if s.size == "shoe")
    assert blank.pieces[1:] == [None, None] and blank.filled == [blank.pieces[0]]
    waiting = plan(ws, order, "wait")
    assert waiting.sheets == [] and sorted(x.size for x in waiting.waiting) == [
        "medium", "medium", "round", "shoe", "small", "tag", "tag"]


def test_piece_tag():
    from engine.packing import Piece
    p = Piece("1234", 0, "small", "k", "matte", "chels-small-v2", name="Léo", index=2, of=5)
    assert p.tag == "#1234 · Léo · tiers 2/5"


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
        assert sh["pdf"] in names and sh["proof"] in names and len(sh["pieces"]) == 3
    assert {"laminate_notches.dxf", f"s-{pack}_info_sheet.txt", f"s-{pack}_packing_slip.txt"} <= names
    # labels per size = the pack's contents (bonus copies aside)
    got: dict[str, int] = {}
    for sh in res.plan.sheets:
        lay = ws.producer.layouts([sh.size])[sh.size]
        for x in sh.filled:
            assert x.size == sh.size and x.finish == sh.finish
            if not x.bonus:
                got[x.size] = got.get(x.size, 0) + lay.per_piece
    assert got == CAT.packs[pack].contents
    pages = sum(len(pdfium.PdfDocument(str(f))) for f in pdfs)
    assert pages == len(res.plan.sheets)


def test_print_pdf_carries_no_text(ws, tmp_path):
    """Only the labels, the registration marks and the trim marks are printed: no header, no order text."""
    res = ws.producer.run([Order("T", [OrderLine("dino", "starter", "matte", "Léo")])], tmp_path,
                          customer_proofs=False)
    for f in res.files:
        if f.name.endswith("_print.pdf"):
            for page in pdfium.PdfDocument(str(f)):
                assert page.get_textpage().get_text_range().strip() == ""
    slip = (tmp_path / "T_packing_slip.txt").read_text(encoding="utf-8")
    assert "tiers 1/5" in slip and "haut (top)" in slip and "milieu (middle)" in slip and "bas (bottom)" in slip
    info = (tmp_path / "T_info_sheet.txt").read_text(encoding="utf-8")
    assert "milieu:" in info and "Couper la feuille aux traits de coupe en trois tiers (haut / milieu / bas)" in info


def test_unknown_pack_size_is_a_plain_error(ws, tmp_path):
    cat = ws.catalog
    bad = dataclasses.replace(cat.packs["starter"], contents={"pencil": 18})
    cat.packs["bad"] = bad
    try:
        with pytest.raises(OrderError, match="whole number of pieces"):
            ws.producer.run([Order("x", [OrderLine("dino", "bad", "matte", "A")])], tmp_path)
    finally:
        del cat.packs["bad"]
