"""Etsy listings routes: the editable groups and shop fields, listing images, the import CSV."""
from __future__ import annotations

import io

from fastapi import APIRouter, Request, Response
from PIL import Image
from pydantic import BaseModel

from .api import disposition
from .listings_service import CSV_NAME

router = APIRouter()


def listings(request: Request):
    return request.app.state.listings


@router.get("/listings")
def get_listings(request: Request):
    return listings(request).status()


@router.put("/listings")
def save_listings(body: dict, request: Request):
    listings(request).save(body)
    return listings(request).status()


class ImagesBody(BaseModel):
    groups: list[str] | None = None     # None = every listing
    upload_only: bool = False           # re-send the stored images to R2 without rendering them again


@router.post("/listings/images", status_code=202)
def make_images(body: ImagesBody, request: Request):
    return listings(request).start(body.groups, body.upload_only)


@router.get("/listings/job")
def listings_job(request: Request):
    return listings(request).latest()


@router.get("/listings/images.zip")
def images_zip(request: Request):
    return Response(listings(request).zip_bytes(), media_type="application/zip",
                    headers={"Content-Disposition": disposition("attachment", "etsy_listing_images.zip")})


@router.get("/listings/images/{name}")
def listing_image(name: str, request: Request, w: int = 0, download: bool = False):
    data = listings(request).image_bytes(name)
    if w:
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((min(w, 1200), min(w, 1200)))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})
    return Response(data, media_type="image/png",
                    headers={"Content-Disposition": disposition("attachment" if download else "inline", name),
                             "Cache-Control": "no-cache"})


@router.get("/listings/csv")
def listings_csv(request: Request, groups: str = ""):
    ids = [g for g in groups.split(",") if g] or None
    data = listings(request).csv(ids)
    return Response(data.encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": disposition("attachment", CSV_NAME)})
