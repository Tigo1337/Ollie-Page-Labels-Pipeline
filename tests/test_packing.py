import itertools
import random

import pytest

from engine.config import load_catalog
from engine.packing import STRATEGIES, Job, labels_per_sheet
from engine.workspace import REPO

CAT = load_catalog(REPO / "config")
PROD = CAT.production
EPS = 1e-6


def jobs_for(contents):
    out, seq = [], 0
    for sid, q in contents.items():
        for _ in range(q):
            out.append(Job(size=sid, key=sid, seq=seq))
            seq += 1
    return out


def overlap(a, b):
    return a[0] < b[2] - EPS and b[0] < a[2] - EPS and a[1] < b[3] - EPS and b[1] < a[3] - EPS


def check_sheets(sheets):
    b = PROD.bleed
    for sheet in sheets:
        boxes = [p.bleed_box(b) for p in sheet.placements]
        for bx in boxes:
            # margins: no ink closer than 12 mm to any edge; bleed box on the page
            assert bx[0] >= PROD.margin - EPS and bx[1] >= PROD.margin - EPS
            assert bx[2] <= PROD.page_w - PROD.margin + EPS and bx[3] <= PROD.page_h - PROD.margin + EPS
            assert 0 <= bx[0] and bx[2] <= PROD.page_w and 0 <= bx[1] and bx[3] <= PROD.page_h
            for k in PROD.keepout_rects():
                assert not overlap(bx, k), f"bleed box {bx} enters keep-out {k}"
        cuts = [(p.x, p.y, p.x + p.w, p.y + p.h) for p in sheet.placements]
        for a, c in itertools.combinations(cuts, 2):
            grown = (a[0] - PROD.gap, a[1] - PROD.gap, a[2] + PROD.gap, a[3] + PROD.gap)
            assert not overlap(grown, c), f"cut lines closer than {PROD.gap} mm: {a} {c}"


@pytest.mark.parametrize("strategy", list(STRATEGIES))
@pytest.mark.parametrize("pack", list(CAT.packs))
def test_packs_never_overlap(strategy, pack):
    jobs = jobs_for(CAT.packs[pack].contents)
    sheets = STRATEGIES[strategy].pack(jobs, CAT.sizes, PROD)
    assert sum(len(s.placements) for s in sheets) == len(jobs)
    check_sheets(sheets)


@pytest.mark.parametrize("strategy", list(STRATEGIES))
def test_random_mixes_never_overlap(strategy):
    rng = random.Random(7)
    for _ in range(25):
        contents = {sid: rng.randint(0, 70) for sid in CAT.sizes}
        jobs = jobs_for(contents)
        sheets = STRATEGIES[strategy].pack(jobs, CAT.sizes, PROD)
        assert sorted(j.seq for s in sheets for j in [p.job for p in s.placements]) == [j.seq for j in jobs]
        check_sheets(sheets)


def test_rows_never_mix_sizes_and_names_stay_together():
    jobs, seq = [], 0
    for name in ("A", "B", "C"):
        for sid, q in CAT.packs["school"].contents.items():
            for _ in range(q):
                jobs.append(Job(size=sid, key=f"{name}{sid}", group=name, seq=seq))
                seq += 1
    sheets = STRATEGIES["tidy-rows"].pack(jobs, CAT.sizes, PROD)
    check_sheets(sheets)
    for s in sheets:
        rows = {}
        for p in s.placements:
            rows.setdefault(round(p.y, 3), set()).add(p.job.size)
        assert all(len(v) == 1 for v in rows.values())
    # reading order within each size: names are contiguous (A..., B..., C...)
    for sid in CAT.sizes:
        seq_names = [p.job.group for s in sheets for p in sorted(s.placements, key=lambda p: (p.y, p.x))
                     if p.job.size == sid]
        collapsed = [g for i, g in enumerate(seq_names) if i == 0 or g != seq_names[i - 1]]
        assert collapsed == sorted(set(collapsed))


def test_partial_sheet_starts_top_left():
    jobs = jobs_for({"mini": 7})
    sheet = STRATEGIES["tidy-rows"].pack(jobs, CAT.sizes, PROD)[0]
    first = min(sheet.placements, key=lambda p: (p.y, p.x))
    assert first.y - PROD.bleed == pytest.approx(PROD.margin)
    ys = sorted({p.y for p in sheet.placements})
    assert len(ys) == 3  # 3 in the top band, then 3, then 1


def test_tidy_columns_line_up():
    jobs = jobs_for({"small": 55})
    sheet = STRATEGIES["tidy-rows"].pack(jobs, CAT.sizes, PROD)[0]
    pitch = CAT.sizes["small"].w + PROD.gap
    for p in sheet.placements:
        k = (p.x - PROD.bleed - PROD.margin) / pitch
        assert abs(k - round(k)) < 1e-6


def test_labels_per_sheet_numbers():
    per = {sid: labels_per_sheet(s, PROD) for sid, s in CAT.sizes.items()}
    assert per == {"mini": 99, "small": 55, "medium": 34, "large": 15, "round": 34, "square": 22}
