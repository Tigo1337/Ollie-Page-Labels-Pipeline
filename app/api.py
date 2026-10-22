"""JSON API routes."""
from __future__ import annotations

import base64
import io
import threading
from typing import Literal

from fastapi import APIRouter, File, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel, Field

from engine.art import auto_preset, validate_preset
from engine.layout import LayoutError, current_layout
from engine.packing import PackError, pack_pieces, pack_sheets
from engine.config import Preset
from engine.orders import Order, OrderLine, validate_line
from engine.proofs import cut_out, font_chart, review_sheet
from engine.render import LabelSpec
from engine.text import GlyphError, normalise_name

from .db import RunRow
from .repo import NotFound
from .runs import CONTENT_TYPES, run_json, run_production

router = APIRouter()


def svc(request: Request):
    return request.app.state.svc


def repo(request: Request):
    return request.app.state.repo


def disposition(kind: str, filename: str) -> str:
    from urllib.parse import quote
    ascii_ = filename.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
    return f"{kind}; filename=\"{ascii_}\"; filename*=UTF-8''{quote(filename)}"


def png_response(img: Image.Image, filename: str | None = None, download: bool = False) -> Response:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    headers = {"Cache-Control": "no-store"}
    if filename:
        headers["Content-Disposition"] = disposition("attachment" if download else "inline", filename)
    return Response(buf.getvalue(), media_type="image/png", headers=headers)


def data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------- auth / health
class LoginBody(BaseModel):
    secret: str


@router.get("/health")
def health(request: Request):
    return {"ok": True, "storage": request.app.state.store.name}


@router.get("/auth")
def auth_status(request: Request):
    from .main import AUTH_COOKIE, auth_token
    s = request.app.state.settings
    if not s.api_secret:
        return {"required": False, "ok": True, "warning": "LABELS_API_SECRET is not set: the app is open to "
                                                          "anyone with the URL. Add it in Replit Secrets."}
    return {"required": True, "ok": request.cookies.get(AUTH_COOKIE) == auth_token(s.api_secret)}


@router.post("/login")
def login(body: LoginBody, request: Request):
    import hmac

    from .main import AUTH_COOKIE, auth_token
    s = request.app.state.settings
    if not s.api_secret:
        return {"ok": True}
    if not hmac.compare_digest(body.secret.strip(), s.api_secret):
        return JSONResponse({"detail": "That secret is not right."}, status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(AUTH_COOKIE, auth_token(s.api_secret), httponly=True, samesite="lax",
                    secure=request.url.scheme == "https", max_age=60 * 60 * 24 * 365)
    return resp


@router.post("/logout")
def logout():
    from .main import AUTH_COOKIE
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(AUTH_COOKIE)
    return resp


# ---------------------------------------------------------------- catalogue
@router.get("/catalog")
def catalog(request: Request):
    s = svc(request)
    with s.lock:
        cat = s.catalog
    prod = cat.production
    layouts_dir = s.layouts_dir
    per_size, per_pack = {}, {}
    for sid, size in cat.sizes.items():
        try:
            lay = current_layout(cat.sheet, size, layouts_dir)
            per_size[sid] = {"layout_id": lay.layout_id, "per_piece": lay.per_piece, "per_sheet": lay.per_sheet}
        except LayoutError:
            per_size[sid] = {"layout_id": None, "per_piece": 0, "per_sheet": 0}
    for pid, p in cat.packs.items():
        try:
            per_pack[pid] = {"pieces_by_size": pack_pieces(p, cat, layouts_dir), **pack_sheets(p, cat, layouts_dir)}
        except (LayoutError, PackError) as e:
            per_pack[pid] = {"pieces_by_size": {}, "pieces": 0, "batched": 0, "alone": 0, "error": str(e)}
    return {
        "production": prod.__dict__,
        "sheet": {k: v for k, v in cat.sheet.__dict__.items() if k != "raw"},
        "sizes": [dict(size.__dict__, is_rect=size.is_rect, dims=size.dims_label, **per_size[sid])
                  for sid, size in cat.sizes.items()],
        "packs": [dict(p.__dict__, total=p.total, **per_pack[p.id]) for p in cat.packs.values()],
        "finishes": [f.__dict__ for f in cat.finishes.values()],
        "fonts": [f.__dict__ for f in cat.fonts.values()],
    }


# ---------------------------------------------------------------- designs
@router.get("/designs")
def list_designs(request: Request):
    r = repo(request)
    return [r.design_json(row) for row in r.design_rows()]


class NewDesign(BaseModel):
    id: str
    name: str
    fill: str = "#1F3B63"
    stroke: str = "#FFFFFF"
    char_end: float = 0.25


@router.post("/designs")
def create_design(body: NewDesign, request: Request):
    r = repo(request)
    return r.design_json(r.create_design(body.id, body.name, body.fill, body.stroke, body.char_end))


@router.get("/designs/{design_id}")
def get_design(design_id: str, request: Request):
    r = repo(request)
    return r.design_json(r.design_row(design_id))


@router.patch("/designs/{design_id}")
def update_design(design_id: str, fields: dict, request: Request):
    r = repo(request)
    return r.design_json(r.update_design(design_id, fields))


@router.delete("/designs/{design_id}")
def delete_design(design_id: str, request: Request):
    repo(request).delete_design(design_id)
    return {"ok": True}


@router.post("/designs/{design_id}/art/{source}")
async def upload_art(design_id: str, source: str, request: Request, file: UploadFile = File(...)):
    r = repo(request)
    data = await file.read()
    row = r.set_art(design_id, source, data, file.filename or "")
    return r.design_json(row)


@router.get("/designs/{design_id}/art/{source}")
def get_art(design_id: str, source: str, request: Request, variant: str = "prepared", w: int = 0):
    data = repo(request).art_bytes(design_id, source, "original" if variant == "original" else "prepared")
    if w:
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((w, w * 4))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=88)
        return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})
    im_fmt = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    return Response(data, media_type=im_fmt, headers={"Cache-Control": "max-age=3600"})


@router.post("/designs/import-zip", status_code=202)
def bulk_import(request: Request, file: UploadFile = File(...)):
    """Starts a background import of the ZIP and returns the job; poll /designs/import-zip/{id}."""
    return request.app.state.imports.start(file.file, file.filename or "")


@router.get("/designs/import-zip/latest")
def bulk_import_latest(request: Request):
    return request.app.state.imports.latest()


@router.get("/designs/import-zip/{job_id}")
def bulk_import_status(job_id: str, request: Request):
    job = request.app.state.imports.get(job_id)
    if job is None:
        raise NotFound("That import is not known (the app may have restarted).")
    return job


@router.get("/designs/{design_id}/review.png")
def design_review(design_id: str, request: Request, font: int = 1, finish: str = "matte", download: bool = False):
    s = svc(request)
    with s.lock:
        img = review_sheet(s.renderer, s.ui, design_id, font_id=font, finish=finish)
    return png_response(img, f"review_{design_id}_font{font}.png", download)


@router.get("/designs/{design_id}/thumb.png")
def design_thumb(design_id: str, request: Request, name: str = "Léo", size: str = "medium", font: int = 1):
    s = svc(request)
    with s.lock:
        cat = s.catalog
        lab = s.renderer.render(LabelSpec(design_id, size, name, "", font))
        img = cut_out(lab, cat.sizes[size], cat.sheet.bleed, 7.0)
    return png_response(img)


# ---------------------------------------------------------------- crop presets
@router.get("/designs/{design_id}/presets")
def get_presets(design_id: str, request: Request):
    """Saved or automatic preset for every size, plus what the crop editor needs to draw them."""
    s = svc(request)
    with s.lock:
        cat = s.catalog
        design = s.renderer.design(design_id)
        dims = s.assets.art_sources(design_id)
        review = repo(request).design_json(repo(request).design_row(design_id)).get("review", {})
        out = []
        for sid, size in cat.sizes.items():
            saved = design.presets.get(sid)
            auto = None
            if size.default_source in dims:
                w, h = dims[size.default_source]
                auto = auto_preset(design, size, cat.sheet.bleed, w, h).to_dict()
            out.append({"size": sid, "preset": saved.to_dict() if saved else auto, "auto": auto,
                        "is_auto": saved is None, "review": review.get(sid)})
    return {"sizes": out, "art": {k: list(v) for k, v in dims.items()}, "bleed": cat.sheet.bleed,
            "safe": cat.production.safe}


@router.put("/designs/{design_id}/presets/{size_id}")
def save_preset(design_id: str, size_id: str, body: dict, request: Request):
    s = svc(request)
    with s.lock:
        if size_id not in s.catalog.sizes:
            raise NotFound(f"Unknown size '{size_id}'.")
        try:
            preset = Preset.from_dict(body)
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError("That crop could not be read.") from e
        validate_preset(preset, s.assets.art_sources(design_id))
    repo(request).set_preset(design_id, size_id, preset)
    return {"ok": True, "preset": preset.to_dict()}


@router.delete("/designs/{design_id}/presets/{size_id}")
def reset_preset(design_id: str, size_id: str, request: Request):
    repo(request).set_preset(design_id, size_id, None)
    return {"ok": True}


@router.post("/designs/{design_id}/presets/{size_id}/copy-to-rect")
def copy_preset_to_rect(design_id: str, size_id: str, request: Request):
    """Copy one size's saved crop to every rectangular size (fractions, so each keeps its own shape)."""
    s = svc(request)
    with s.lock:
        cat = s.catalog
        preset = s.renderer.design(design_id).presets.get(size_id)
    if preset is None:
        raise ValueError("Save this size's crop first, then copy it.")
    targets = [sid for sid, size in cat.sizes.items() if size.is_rect and sid != size_id]
    for sid in targets:
        repo(request).set_preset(design_id, sid, preset)
    return {"ok": True, "copied_to": targets}


# ---------------------------------------------------------------- shop settings
@router.get("/shop")
def get_shop(request: Request):
    return repo(request).setting("shop")


@router.patch("/shop")
def update_shop(body: dict, request: Request):
    r = repo(request)
    shop = dict(r.setting("shop"))
    if "default_finish" in body:
        if body["default_finish"] not in svc(request).catalog.finishes:
            raise ValueError(f"Unknown finish '{body['default_finish']}'.")
        shop["default_finish"] = body["default_finish"]
    r.set_setting("shop", shop)
    return shop


# ---------------------------------------------------------------- previews
class PreviewBody(BaseModel):
    design: str
    size: str
    name: str
    line2: str = ""
    font: int = 1
    finish: str = "matte"
    preset: dict | None = None
    scale: float = Field(default=9.0, ge=2, le=24)  # px per mm of the preview image


@router.post("/preview")
def preview(body: PreviewBody, request: Request):
    """One label as the buyer sees it, plus cap heights and warnings (used by forms and the crop editor)."""
    s = svc(request)
    with s.lock:
        cat = s.catalog
        if body.size not in cat.sizes:
            raise NotFound(f"Unknown size '{body.size}'.")
        preset = Preset.from_dict(body.preset) if body.preset else None
        lab = s.renderer.render(LabelSpec(body.design, body.size, body.name, body.line2, body.font, body.finish),
                                preset=preset)
        img = cut_out(lab, cat.sizes[body.size], cat.sheet.bleed, body.scale,
                      holo=body.finish == "holographic")
    return {"image": data_url(img), "cap_mm": lab.cap_mm, "warnings": lab.warnings,
            "preset": lab.preset.to_dict(), "preset_is_auto": lab.preset_is_auto,
            "min_cap_mm": cat.production.min_cap_mm}


@router.get("/check-name")
def check_name(request: Request, name: str, font: int = 1, line2: str = ""):
    s = svc(request)
    text = normalise_name(name) + normalise_name(line2)
    with s.lock:
        try:
            s.renderer.fonts.check_glyphs(text, font)
        except GlyphError as e:
            return {"ok": False, "message": str(e), "missing": e.missing,
                    "alternatives": [{"id": f.id, "name": f.name} for f in e.alternatives]}
    return {"ok": True, "normalised": normalise_name(name)}


@router.get("/fontchart.png")
def fontchart(request: Request, lang: str = "en", download: bool = False):
    s = svc(request)
    with s.lock:
        img = font_chart(s.renderer, s.ui, s.texts(), lang=lang)
    return png_response(img, "font_chart.png", download)


# ---------------------------------------------------------------- fonts
@router.get("/fonts")
def fonts(request: Request):
    return {"fonts": svc(request).font_status(), "job": request.app.state.font_job}


@router.post("/fonts/download")
def download_fonts(request: Request, force: bool = False):
    job = request.app.state.font_job
    if job["running"]:
        return {"started": False, "job": job}
    s = svc(request)

    def work():
        job["running"] = True
        try:
            job["report"] = s.download_fonts(force=force)
        finally:
            job["running"] = False
    threading.Thread(target=work, daemon=True).start()
    return {"started": True}


# ---------------------------------------------------------------- make labels (quick order)
class MakeBody(BaseModel):
    order_id: str = ""
    design: str
    pack: str
    finish: str = ""      # empty = the shop's default finish
    name: str
    line2: str = ""
    font: int = 1
    lang: str = "en"
    unpaired: Literal["bonus", "blank"] = "bonus"   # the other half of a sheet printed alone


@router.post("/make")
def make(body: MakeBody, request: Request):
    s = svc(request)
    finish = body.finish or repo(request).setting("shop")["default_finish"]
    body = body.model_copy(update={"finish": finish})
    line = OrderLine(body.design, body.pack, finish, body.name, body.line2, body.font)
    with s.lock:
        errs = validate_line(line, s.catalog)
    if errs:
        raise ValueError(" ".join(errs))
    order_id = body.order_id.strip() or "quick-" + normalise_name(body.name).replace(" ", "-")[:30]
    order = Order(order_id, [line], lang=body.lang)
    row = run_production(s, [order], title=f"{order_id} · {normalise_name(body.name)}",
                         request=body.model_dump(), lang=body.lang, unpaired=body.unpaired,
                         studio3=request.app.state.templates.current_studio3_bytes)
    return run_json(row)


@router.get("/runs")
def list_runs(request: Request, limit: int = 30):
    from sqlalchemy import select
    with repo(request).Session() as ses:
        rows = list(ses.scalars(select(RunRow).order_by(RunRow.created_at.desc()).limit(limit)))
    return [run_json(r) for r in rows]


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request):
    with repo(request).Session() as ses:
        row = ses.get(RunRow, run_id)
    if row is None:
        raise NotFound("That production run does not exist.")
    return run_json(row)


@router.get("/runs/{run_id}/files/{name}")
def run_file(run_id: str, name: str, request: Request, download: bool = False):
    if "/" in name or "\\" in name or name.startswith("."):
        raise NotFound("No such file.")
    data = request.app.state.store.get(f"runs/{run_id}/{name}")
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    disp = "attachment" if download or ext in (".zip", ".dxf") else "inline"
    return Response(data, media_type=CONTENT_TYPES.get(ext, "application/octet-stream"),
                    headers={"Content-Disposition": disposition(disp, name)})
