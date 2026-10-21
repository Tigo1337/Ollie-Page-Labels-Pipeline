import json

import pytest

from engine.cli import main
from engine.orders import Order, OrderError, OrderLine, parse_sku


def test_parse_sku(ws):
    cat = ws.catalog
    assert parse_sku("dino-school-holographic", cat) == ("dino", "school", "holographic")
    assert parse_sku("space-cat-pencil60-matte", cat) == ("space-cat", "pencil60", "matte")
    assert parse_sku("Rainbow-Clouds-STARTER-gloss", cat) == ("rainbow-clouds", "starter", "gloss")
    with pytest.raises(OrderError):
        parse_sku("dino-huge-matte", cat)


def test_expand_into_halves(ws):
    o = Order("1", [OrderLine("dino", "starter", "matte", "Anna"), OrderLine("dino", "starter", "gloss", "Ben"),
                    OrderLine("fox", "pencil60", "matte", "Cleo")])
    ex = ws.producer.expand([o])
    by = ex.by_finish()
    assert [(h.size, h.name) for h in by["matte"]] == [("pencil", "Anna"), ("small", "Anna"),
                                                       ("pencil", "Cleo"), ("pencil", "Cleo")]
    assert [(h.size, h.name) for h in by["gloss"]] == [("pencil", "Ben"), ("small", "Ben")]
    assert [(h.index, h.of) for h in ex.halves] == [(i, 6) for i in range(1, 7)]
    assert [h.seq for h in ex.halves] == sorted(h.seq for h in ex.halves)
    assert {h.layout_id for h in ex.halves} == {"chels-pencil-v1", "chels-small-v1"}


def test_unknown_things_give_plain_errors(ws, tmp_path):
    with pytest.raises(OrderError, match="Unknown design 'nope'"):
        ws.producer.run([Order("x", [OrderLine("nope", "school", "matte", "A")])], tmp_path)
    with pytest.raises(OrderError, match="no glyph"):
        ws.producer.run([Order("x", [OrderLine("dino", "pencil60", "matte", "Nguyễn", "", 1)])], tmp_path)


def test_cli_commands(ws, tmp_path, capsys):
    data = str(ws.assets.root)
    assert main(["--data", data, "packs"]) == 0
    assert "Back-to-school pack (96 + 8 shoe pairs)" in capsys.readouterr().out
    order = tmp_path / "o.json"
    order.write_text(json.dumps({"order_id": "c1", "lines": [
        {"design": "dino", "pack": "starter", "finish": "gloss", "name": "Zoë", "font": 1}]}))
    assert main(["--data", data, "order", str(order), "--out", str(tmp_path / "out")]) == 0
    files = {p.name for p in (tmp_path / "out").iterdir()}
    assert {"c1.zip", "c1_gloss_chels-pencil-v1_print.pdf", "c1_gloss_chels-small-v1_print.pdf",
            "chels-pencil-v1.svg", "chels-pencil-v1.dxf", "chels-small-v1.svg", "chels-small-v1.dxf",
            "c1_sheet01_proof.png", "c1_sheet02_proof.png", "laminate_notches.dxf", "c1_info_sheet.txt",
            "c1_info_sheet.pdf", "c1_packing_slip.txt", "c1_packing_slip.pdf", "c1_customer_proof.png"} <= files
    assert "sheet 2: chels-small-v1 gloss" in capsys.readouterr().out
    assert main(["--data", data, "pack-samples", "--pack", "shoe8", "--finish", "holographic",
                 "--out", str(tmp_path / "samples")]) == 0
    assert (tmp_path / "samples" / "shoe8_holographic" / "sample-shoe8-holographic.zip").exists()
    assert main(["--data", data, "fontchart", "--out", str(tmp_path / "fc.png")]) == 0
    assert main(["--data", data, "review", "dino", "--out", str(tmp_path / "r.png")]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"order_id": "b", "lines": [{"design": "dino", "pack": "x", "finish": "gloss",
                                                            "name": "A"}]}))
    assert main(["--data", data, "order", str(bad), "--out", str(tmp_path / "o2")]) == 2
    assert "Unknown pack 'x'" in capsys.readouterr().err
