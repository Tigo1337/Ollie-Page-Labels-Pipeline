"""Piece batching (three pieces = one sheet), pack math, the envelope estimate, and the bundle every
pack produces."""
import dataclasses
import zipfile

import pypdfium2 as pdfium
import pytest

from engine.config import Pack, load_catalog
from engine.orders import Order, OrderError, OrderLine
from engine.packing import PackError, envelope, order_envelope, pack_pieces, pack_sheets
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
    assert envelope(3, prod) == {"weight_g": 23.0, "thickness_mm": 1.05, "kind": "standard", "tier": "standard-30",
                                 "lettermail": "Lettermail, up to 30 g", "warning": ""}
    assert envelope(5, prod)["lettermail"] == "Lettermail, 30–50 g"                  # starter: 35 g
    assert envelope(7, prod)["weight_g"] == 47.0 and envelope(7, prod)["kind"] == "standard"   # daycare
    school = envelope(14, prod)                                                        # 89 g, 4.9 mm
    assert school["weight_g"] == 89.0 and school["kind"] == "oversized"
    assert school["lettermail"] == "Oversized letter, up to 100 g"
    assert school["warning"] == "14 pieces, over 50 g: ships as an oversized letter, up to 100 g."
    # thickness alone can make a light envelope oversized; over 500 g or 20 mm it is a parcel
    thin_heavy = dataclasses.replace(prod, piece_weight_g=1.0, piece_thickness_mm=0.6)
    assert envelope(9, thin_heavy)["kind"] == "oversized" and "mm thick" in envelope(9, thin_heavy)["warning"]
    assert envelope(58, prod)["kind"] == "parcel"
    heavy = dataclasses.replace(prod, piece_weight_g=10.0)
    assert envelope(3, heavy)["lettermail"] == "Lettermail, 30–50 g"
    assert pack_sheets(CAT.packs["daycare"], CAT, LAYOUTS)["envelope"]["weight_g"] == 47.0


def test_bonus_copies_go_in_only_when_they_keep_the_postage():
    prod = CAT.production
    starter_alone = order_envelope(5, 7, prod)         # 35 g; with its 7 bonus copies 77 g = oversized
    assert not starter_alone["bonus_in_envelope"] and starter_alone["pieces"] == 5
    assert starter_alone["lettermail"] == "Lettermail, 30–50 g"
    assert "oversized letter, up to 100 g" in starter_alone["bonus_note"]
    school_alone = order_envelope(14, 7, prod)         # 89 g -> 131 g: 100 g step -> 200 g step
    assert not school_alone["bonus_in_envelope"] and school_alone["weight_g"] == 89.0
    small = order_envelope(2, 1, prod)                 # 17 g -> 23 g: still up to 30 g
    assert small["bonus_in_envelope"] and small["pieces"] == 3 and "bonus_note" not in small
    assert order_envelope(3, 0, prod)["bonus_in_envelope"] is False


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


def test_packing_guide_tells_the_pieces_apart(ws, tmp_path):
    """Nothing on the sheet; the packing guide lists each envelope's pieces (size, name, design, font, where)
    and flags look-alikes between orders: identical labels are interchangeable, the others are not."""
    from engine.packing_guide import look_alikes
    orders = [Order("A1", [OrderLine("dino", "starter", "matte", "Léo")], customer="Ann"),
              Order("B2", [OrderLine("fox", "starter", "matte", "Leo")]),
              Order("C3", [OrderLine("dino", "starter", "matte", "Léo")]),
              Order("D4", [OrderLine("dino", "round30", "matte", "Zoé", "", 3)])]
    res = ws.producer.run(orders, tmp_path, customer_proofs=False)
    guide = tmp_path / f"{res.prefix}_packing_guide.pdf"
    assert guide in res.files
    with zipfile.ZipFile(res.zip_path) as z:
        assert guide.name in z.namelist()
    text = "\n".join(p.get_textpage().get_text_range() for p in pdfium.PdfDocument(str(guide)))
    for want in ("Envelope 1 · Order #A1 · Ann", "Envelope 4 · Order #D4", "3 pieces · Round · Zoé",
                 "Look-alikes", "same label as #C3 (either will do)", "Forest Fox · font 1"):
        assert want in text, want
    envs = res.summary["envelopes"]
    assert [e["order"] for e in envs] == ["A1", "B2", "C3", "D4"]
    a1 = envs[0]
    assert a1["real"] == 5 and a1["lettermail"] == "Lettermail, 30–50 g"
    assert a1["pieces"] == 5 and sum(p["count"] for p in a1["labels"]) == 5
    assert {p["size"] for p in a1["labels"]} == {"pencil", "small", "medium", "round"}
    assert all(w.startswith("sheet ") for p in a1["labels"] for w in p["where"])
    alikes = look_alikes(res.envelopes)
    small = next(a for a in alikes if a["size"] == "small")
    assert not small["identical"] and {p["order"] for p in small["pieces"]} == {"A1", "B2", "C3"}
    same = {p["order"]: p["same_as"] for p in small["pieces"]}
    assert same == {"A1": ["C3"], "B2": [], "C3": ["A1"]}
    assert not any(a["name"] == "Zoé" for a in alikes)                     # only one order has Zoé
    # every piece of the run is in exactly one envelope (or set aside as a bonus spare)
    placed = sum(e["real"] + e["bonus"] for e in envs)
    assert placed == sum(len(sh.filled) for sh in res.plan.sheets)


def test_packing_slip_and_summary_follow_the_bonus_rule(ws, tmp_path):
    res = ws.producer.run([Order("S", [OrderLine("dino", "school", "matte", "Sam")])], tmp_path,
                          customer_proofs=False)
    env = res.summary["envelopes"][0]
    assert (env["real"], env["bonus"], env["bonus_in_envelope"], env["weight_g"]) == (14, 7, False, 89.0)
    slip = (tmp_path / "S_packing_slip.txt").read_text(encoding="utf-8")
    assert "keep aside as a spare" in slip and "same envelope" not in slip
    assert "Envelope: 14 piece(s), about 89 g and 4.9 mm — Oversized letter, up to 100 g" in slip
