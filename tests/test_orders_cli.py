import json

import pytest

from engine.cli import main
from engine.orders import Order, OrderError, OrderLine, parse_sku


def test_parse_sku_new_and_old(ws):
    cat = ws.catalog
    # new: <design>-<pack>, finish = matte
    assert parse_sku("dino-school", cat) == ("dino", "school", "matte")
    assert parse_sku("space-cat-pencil51", cat) == ("space-cat", "pencil51", "matte")
    assert parse_sku("Rainbow-Clouds-STARTER", cat) == ("rainbow-clouds", "starter", "matte")
    # old: <design>-<pack>-<finish>, any of the old finishes still parses
    assert parse_sku("dino-school-holographic", cat) == ("dino", "school", "holographic")
    assert parse_sku("space-cat-pencil51-matte", cat) == ("space-cat", "pencil51", "matte")
    assert parse_sku("Rainbow-Clouds-STARTER-gloss", cat) == ("rainbow-clouds", "starter", "gloss")
    for bad in ("dino-huge-matte", "dino-huge", "nope-school", "dino-school-shiny"):
        with pytest.raises(OrderError):
            parse_sku(bad, cat)


def test_expand_into_pieces_and_old_finishes_become_matte(ws):
    o = Order("1", [OrderLine("dino", "starter", "matte", "Anna"), OrderLine("dino", "starter", "gloss", "Ben"),
                    OrderLine("fox", "pencil51", "holographic", "Cleo")])
    ex = ws.producer.expand([o])
    assert set(ex.by_finish()) == {"matte"}
    assert [(p.size, p.name) for p in ex.pieces[:5]] == [("pencil", "Anna"), ("small", "Anna"), ("small", "Anna"),
                                                         ("medium", "Anna"), ("round", "Anna")]
    assert [(p.size, p.name) for p in ex.pieces[10:]] == [("pencil", "Cleo")] * 3
    assert [(p.index, p.of) for p in ex.pieces] == [(i, 13) for i in range(1, 14)]
    assert [p.seq for p in ex.pieces] == sorted(p.seq for p in ex.pieces)
    assert {p.layout_id for p in ex.pieces} == {"chels-pencil-v2", "chels-small-v2", "chels-medium-v2",
                                                "chels-round-v2"}
    assert len(ex.warnings) == 2 and "'gloss'" in ex.warnings[0] and "'holographic'" in ex.warnings[1]
    assert all("matte laminate" in w for w in ex.warnings)
    assert all(spec.finish == "matte" for spec in ex.specs.values())


def test_old_finish_order_is_produced_in_matte_with_a_warning(ws, tmp_path):
    res = ws.producer.run([Order("g", [OrderLine("dino", "round30", "gloss", "Anna")])], tmp_path,
                          customer_proofs=False)
    assert set(res.summary["finishes"]) == {"matte"}
    assert any("'gloss' finish, produced in matte laminate" in w for w in res.warnings)
    assert res.summary["warnings"] == res.warnings


def test_order_json_without_a_finish_is_matte():
    o = Order.from_dict({"order_id": "x", "lines": [{"design": "dino", "pack": "school", "name": "A"}]})
    assert o.lines[0].finish == "matte"


def test_unknown_things_give_plain_errors(ws, tmp_path):
    with pytest.raises(OrderError, match="Unknown design 'nope'"):
        ws.producer.run([Order("x", [OrderLine("nope", "school", "matte", "A")])], tmp_path)
    with pytest.raises(OrderError, match="no glyph"):
        ws.producer.run([Order("x", [OrderLine("dino", "pencil51", "matte", "Nguyễn", "", 1)])], tmp_path)


def test_cli_commands(ws, tmp_path, capsys):
    data = str(ws.assets.root)
    assert main(["--data", data, "packs"]) == 0
    out = capsys.readouterr().out
    assert "Back-to-school pack (208 + 8 shoe pairs)" in out
    assert "envelope ≈ 89 g, Over 50 g (oversized)" in out and "standard Lettermail is limited to 5 mm" in out
    assert "envelope ≈ 35 g, Lettermail, up to 50 g" in out
    order = tmp_path / "o.json"
    order.write_text(json.dumps({"order_id": "c1", "lines": [
        {"design": "dino", "pack": "starter", "name": "Zoë", "font": 1}]}))
    assert main(["--data", data, "order", str(order), "--out", str(tmp_path / "out")]) == 0
    files = {p.name for p in (tmp_path / "out").iterdir()}
    want = {"c1.zip", "laminate_notches.dxf", "c1_info_sheet.txt", "c1_info_sheet.pdf", "c1_packing_slip.txt",
            "c1_packing_slip.pdf", "c1_customer_proof.png"}
    for i, size in enumerate(("pencil", "small", "medium", "round"), 1):
        want |= {f"c1_matte_chels-{size}-v2_print.pdf", f"chels-{size}-v2.svg", f"chels-{size}-v2.dxf",
                 f"c1_sheet{i:02d}_proof.png"}
    assert want <= files
    out = capsys.readouterr().out
    assert "sheet 2: chels-small-v2 matte  haut: #c1 · Zoë · tiers 2/5" in out
    assert "milieu: #c1 · Zoë · tiers 3/5" in out and "bas: #c1 · Zoë · tiers 3/5 (bonus)" in out
    assert main(["--data", data, "pack-samples", "--pack", "shoe12", "--out", str(tmp_path / "samples")]) == 0
    assert (tmp_path / "samples" / "shoe12_matte" / "sample-shoe12-matte.zip").exists()
    assert main(["--data", data, "fontchart", "--out", str(tmp_path / "fc.png")]) == 0
    assert main(["--data", data, "review", "dino", "--out", str(tmp_path / "r.png")]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"order_id": "b", "lines": [{"design": "dino", "pack": "x", "name": "A"}]}))
    assert main(["--data", data, "order", str(bad), "--out", str(tmp_path / "o2")]) == 2
    assert "Unknown pack 'x'" in capsys.readouterr().err
