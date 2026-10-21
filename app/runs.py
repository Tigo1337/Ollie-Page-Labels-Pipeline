"""Production runs: generate files with the engine and keep them in blob storage."""
from __future__ import annotations

import datetime as dt
import secrets
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from engine.orders import Order

from .db import RunRow
from .engine_service import EngineService

CONTENT_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".svg": "image/svg+xml",
                 ".dxf": "application/dxf", ".txt": "text/plain; charset=utf-8", ".zip": "application/zip",
                 ".json": "application/json", ".studio3": "application/octet-stream"}


def file_kind(name: str) -> str:
    if name.endswith("_print.pdf"):
        return "print"
    if name.startswith("chels-") and name.endswith((".svg", ".dxf", ".studio3")):
        return "template"
    if name.endswith("_customer_proof.png"):
        return "customer-proof"
    if name.endswith("_proof.png"):
        return "page-proof"
    if "laminate_notches" in name:
        return "notch"
    if "packing_slip" in name:
        return "slip"
    if "info_sheet" in name:
        return "info"
    if name.endswith(".zip"):
        return "zip"
    return "other"


def run_production(svc: EngineService, orders: list[Order], title: str, request: dict,
                   lang: str | None = None, unpaired: str = "bonus",
                   studio3: Callable[[str], bytes | None] | None = None) -> RunRow:
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    tmp = Path(tempfile.mkdtemp(prefix="labels-run-"))
    try:
        with svc.lock:
            res = svc.producer().run(orders, tmp, lang=lang, unpaired=unpaired, studio3=studio3)
        files = []
        for f in sorted(tmp.iterdir()):
            svc.store.put(f"runs/{run_id}/{f.name}", f.read_bytes())
            files.append({"name": f.name, "size": f.stat().st_size, "kind": file_kind(f.name)})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    row = RunRow(id=run_id, title=title, prefix=res.prefix, request=request, files=files,
                 summary=res.summary, warnings=res.warnings)
    with svc.repo.Session() as s:
        s.add(row)
        s.commit()
    return row


def run_json(row: RunRow) -> dict:
    return {"id": row.id, "title": row.title, "prefix": row.prefix, "created_at": row.created_at.isoformat(),
            "request": row.request, "files": row.files, "summary": row.summary, "warnings": row.warnings}
