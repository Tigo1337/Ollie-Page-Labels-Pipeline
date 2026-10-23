"""Orders routes: the order list, Etsy CSV import, editing, batches (plan and make) and status."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, File, Request, UploadFile
from pydantic import BaseModel

from .repo import NotFound

router = APIRouter()


def orders(request: Request):
    return request.app.state.orders


@router.get("/orders")
def list_orders(request: Request, status: str | None = None):
    return {"orders": orders(request).list(status or None), "job": orders(request).latest_job()}


@router.post("/orders/import")
async def import_orders(request: Request, file: UploadFile = File(...)):
    return orders(request).import_csv(await file.read())


@router.post("/orders")
def create_order(body: dict, request: Request):
    return orders(request).create(body)


@router.patch("/orders/{order_id}")
def update_order(order_id: str, body: dict, request: Request):
    return orders(request).update(order_id, body)


@router.delete("/orders/{order_id}")
def delete_order(order_id: str, request: Request):
    orders(request).delete(order_id)
    return {"ok": True}


class StatusBody(BaseModel):
    orders: list[str]
    status: Literal["new", "made", "shipped", "cancelled"]


@router.post("/orders/status")
def set_status(body: StatusBody, request: Request):
    return {"changed": orders(request).set_status(body.orders, body.status)}


class BatchBody(BaseModel):
    orders: list[str]
    unpaired: Literal["bonus", "blank"] = "bonus"


@router.post("/orders/plan")
def plan_batch(body: BatchBody, request: Request):
    return orders(request).plan(body.orders, body.unpaired)


@router.post("/orders/batch", status_code=202)
def make_batch(body: BatchBody, request: Request):
    return orders(request).start_batch(body.orders, body.unpaired)


@router.get("/orders/batch/{job_id}")
def batch_status(job_id: str, request: Request):
    job = orders(request).job(job_id)
    if job is None:
        raise NotFound("That batch is not known (the app may have restarted).")
    return job
