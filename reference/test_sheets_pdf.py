"""Layout test PDF: one page per size, Studio landscape frame + /Rotate 270 (SCM style), marks, hairline cut outlines."""
import json, sys
sys.argv=['x']; exec(open('tools/sheet_opt.py').read().split('if __name__')[0])
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from pypdf import PdfReader, PdfWriter
SW, SH = 279.4, 215.9   # Studio frame
def to_studio(x, y, w, h): return (SW - y - h, x, h, w)
sizes = json.load(open('config/sizes.json'))['sizes']
c = canvas.Canvas('out/layout_test_sheets_raw.pdf', pagesize=(SW*mm, SH*mm))
Y = lambda y: (SH - y) * mm   # Studio y-down -> PDF y-up
def rect(X, Yt, W, H, fill=0, stroke=1): c.rect(X*mm, Y(Yt+H), W*mm, H*mm, fill=fill, stroke=stroke)
for k, v in sizes.items():
    L = best(v); cw, ch = L['cell_w'], L['cell_h']
    c.setFillColorRGB(0,0,0)
    # SCM three-mark Type 1 in Studio frame: square TL, L at TR, L at BL
    t, ins, ln = 1.0, INSET, LEN
    c.setLineWidth(t*mm)
    c.rect(ins*mm, Y(ins+5), 5*mm, 5*mm, fill=1, stroke=1)
    c.line((SW-ins-ln+t/2)*mm, Y(ins), (SW-ins)*mm, Y(ins)); c.line((SW-ins)*mm, Y(ins), (SW-ins)*mm, Y(ins+ln-t/2))
    c.line(ins*mm, Y(SH-ins), (ins+ln-t/2)*mm, Y(SH-ins)); c.line(ins*mm, Y(SH-ins), ins*mm, Y(SH-ins-ln+t/2))
    # trim line at X=139.7 (ticks + dashed guide)
    c.setLineWidth(0.6); c.line(139.7*mm, Y(0), 139.7*mm, Y(6)); c.line(139.7*mm, Y(SH-6), 139.7*mm, Y(SH))
    c.setStrokeColorRGB(.6,.6,.65); c.setLineWidth(0.3); c.setDash(3,3); c.line(139.7*mm, Y(8), 139.7*mm, Y(SH-8)); c.setDash()
    c.setStrokeColorRGB(.85,0,.5); c.setLineWidth(0.25)
    n = 0
    for x, y in L['top'] + L['bottom']:
        parts = [(x, y, cw, ch)] if v['shape'] != 'pair' else [(x, y, 30, ch), (x+32.5, y, 30, ch)]
        for p in parts:
            X0, Y0, W, H = to_studio(*p); n += 1
            if v['shape'] == 'round': c.circle((X0+W/2)*mm, Y(Y0+H/2), W/2*mm)
            else: c.roundRect(X0*mm, Y(Y0+H), W*mm, H*mm, v.get('r', 2)*mm)
    c.saveState(); c.translate(150*mm, Y(212)); c.setFont('Helvetica', 7); c.setFillColorRGB(.4,.4,.45)
    c.drawString(0, 0, f"sheet: test, template: chels-{k}-v1  ({L['per_sheet']}{' pairs' if v['shape']=='pair' else ''})"); c.restoreState()
    c.showPage()
c.save()
r = PdfReader('out/layout_test_sheets_raw.pdf'); w = PdfWriter()
for pg in r.pages: pg.rotate(270); w.add_page(pg)
w.write('out/label-layout-test-sheets.pdf'); print('ok', len(r.pages))
