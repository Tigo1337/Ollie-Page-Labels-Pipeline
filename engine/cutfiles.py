"""Cut files: R12 DXF (mm, layer CUT, y flipped) and SVG (mm viewBox)."""
from __future__ import annotations

from .geometry import Point


def _fmt(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def dxf_r12(paths: list[list[Point]], page_h: float, page_w: float, layer: str = "CUT") -> str:
    """One closed POLYLINE per path. Input points are page mm with y down; DXF y = page_h − y."""
    out: list[str] = []

    def g(code: int, value) -> None:
        out.append(str(code))
        out.append(value if isinstance(value, str) else _fmt(value))

    g(0, "SECTION"); g(2, "HEADER")
    g(9, "$ACADVER"); g(1, "AC1009")
    g(9, "$EXTMIN"); g(10, 0.0); g(20, 0.0); g(30, 0.0)
    g(9, "$EXTMAX"); g(10, page_w); g(20, page_h); g(30, 0.0)
    g(9, "$LIMMIN"); g(10, 0.0); g(20, 0.0)
    g(9, "$LIMMAX"); g(10, page_w); g(20, page_h)
    g(0, "ENDSEC")

    g(0, "SECTION"); g(2, "TABLES")
    g(0, "TABLE"); g(2, "LTYPE"); g(70, "1")
    g(0, "LTYPE"); g(2, "CONTINUOUS"); g(70, "0"); g(3, "Solid line"); g(72, "65"); g(73, "0"); g(40, 0.0)
    g(0, "ENDTAB")
    g(0, "TABLE"); g(2, "LAYER"); g(70, "1")
    g(0, "LAYER"); g(2, layer); g(70, "0"); g(62, "1"); g(6, "CONTINUOUS")
    g(0, "ENDTAB")
    g(0, "ENDSEC")

    g(0, "SECTION"); g(2, "ENTITIES")
    for pts in paths:
        g(0, "POLYLINE"); g(8, layer); g(66, "1"); g(70, "1")
        g(10, 0.0); g(20, 0.0); g(30, 0.0)
        for x, y in pts:
            g(0, "VERTEX"); g(8, layer); g(10, x); g(20, page_h - y); g(30, 0.0)
        g(0, "SEQEND"); g(8, layer)
    g(0, "ENDSEC")
    g(0, "EOF")
    return "\n".join(out) + "\n"


def svg(paths: list[list[Point]], page_w: float, page_h: float, stroke: str = "#FF0000",
        stroke_mm: float = 0.2) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_fmt(page_w)}mm" height="{_fmt(page_h)}mm" '
        f'viewBox="0 0 {_fmt(page_w)} {_fmt(page_h)}">',
        f'<g fill="none" stroke="{stroke}" stroke-width="{_fmt(stroke_mm)}" stroke-linejoin="round">',
    ]
    for pts in paths:
        d = "M" + " L".join(f"{_fmt(x)},{_fmt(y)}" for x, y in pts) + " Z"
        lines.append(f'<path d="{d}"/>')
    lines += ["</g>", "</svg>"]
    return "\n".join(lines) + "\n"


def parse_dxf_polylines(text: str) -> list[list[Point]]:
    """Minimal reader for our own R12 output (used by tests and the page proof check)."""
    tokens = text.splitlines()
    pairs = [(tokens[i].strip(), tokens[i + 1].strip()) for i in range(0, len(tokens) - 1, 2)]
    paths: list[list[Point]] = []
    cur: list[Point] | None = None
    in_vertex = False
    vx = vy = 0.0
    for code, val in pairs:
        if code == "0":
            if in_vertex and cur is not None:
                cur.append((vx, vy))
            in_vertex = False
            if val == "POLYLINE":
                cur = []
            elif val == "VERTEX":
                in_vertex = True
            elif val == "SEQEND" and cur is not None:
                paths.append(cur)
                cur = None
        elif in_vertex and code == "10":
            vx = float(val)
        elif in_vertex and code == "20":
            vy = float(val)
    return paths
