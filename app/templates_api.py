"""Routes for the Templates page: the 7 layout cut templates and their .studio3 uploads."""
from __future__ import annotations

import io

from fastapi import APIRouter, File, Request, Response, UploadFile

from engine.gallery import render_layout
from engine.templates import KINDS, file_name, template_bytes

from .api import disposition
from .repo import NotFound
from .runs import CONTENT_TYPES
from .templates_store import studio3_key

router = APIRouter()
_previews: dict[str, bytes] = {}


def tpl(request: Request):
    return request.app.state.templates


@router.get("/templates")
def list_templates(request: Request):
    return tpl(request).listing()


def _layout_and_size(request: Request, layout_id: str):
    t = tpl(request)
    try:
        lay = t.layout(layout_id)
    except ValueError as e:
        raise NotFound(str(e)) from e
    cat = t.catalog()
    if lay.size not in cat.sizes:
        raise NotFound(f"Layout '{layout_id}' is for a size that no longer exists.")
    return lay, cat.sizes[lay.size], cat


@router.get("/templates/{layout_id}/preview.png")
def preview(layout_id: str, request: Request):
    lay, size, cat = _layout_and_size(request, layout_id)
    key = f"{layout_id}:{lay.geometry_hash}"
    if key not in _previews:
        buf = io.BytesIO()
        render_layout(lay, size, cat.sheet, dpi=100).save(buf, "PNG")
        _previews[key] = buf.getvalue()
    return Response(_previews[key], media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@router.get("/templates/{layout_id}/files/{kind}")
def template_file(layout_id: str, kind: str, request: Request, download: bool = False):
    if kind not in KINDS:
        raise NotFound(f"No template file '{kind}'. Files: {', '.join(KINDS)}.")
    lay, size, cat = _layout_and_size(request, layout_id)
    name = file_name(layout_id, kind)
    ext = "." + name.rsplit(".", 1)[-1]
    disp = "attachment" if download or ext == ".dxf" else "inline"
    return Response(template_bytes(lay, size, cat.sheet, kind), media_type=CONTENT_TYPES[ext],
                    headers={"Content-Disposition": disposition(disp, name)})


@router.post("/templates/{layout_id}/studio3")
async def upload_studio3(layout_id: str, request: Request, file: UploadFile = File(...)):
    data = await file.read()
    return tpl(request).save_studio3(layout_id, file.filename or "", data).to_json()


@router.get("/templates/{layout_id}/studio3")
def download_studio3(layout_id: str, request: Request):
    data = request.app.state.store.get(studio3_key(layout_id))
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": disposition("attachment", f"{layout_id}.studio3")})


@router.delete("/templates/{layout_id}/studio3")
def delete_studio3(layout_id: str, request: Request):
    tpl(request).delete_studio3(layout_id)
    return {"ok": True}
