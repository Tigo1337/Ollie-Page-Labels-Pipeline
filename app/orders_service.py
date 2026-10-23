"""Orders: import Etsy's order CSV, keep orders until they are made, make several at once (a batch).

Batching is the point: three pieces of the same size make a sheet, and pieces from different orders
share sheets, so a batch prints fewer sheets (and fewer free bonus copies) than the same orders made
one by one. An order can be made only when every line is valid (design with artwork, bundle, font,
characters the font has) and checked (no `review` notes left from the import).

Statuses: new (to make) → made (a run has its files) → shipped; cancelled. Making an order again is
allowed (a reprint); every run that made it is kept in `runs`.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re
import secrets
import threading

from sqlalchemy import select

from engine.etsy_orders import ImportResult, parse_orders_csv
from engine.orders import LEGACY_FINISHES, Order, OrderLine, validate_line
from engine.packing import order_envelope
from engine.text import GlyphError, normalise_name

from .db import OrderRow
from .repo import NotFound, Repo
from .runs import run_json, run_production

log = logging.getLogger(__name__)
STATUSES = ("new", "made", "shipped", "cancelled")
ORDER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_CSV = 10 * 1024 * 1024


def clean_line(x: dict) -> dict:
    """An order line as stored: known fields only, the right types."""
    if not isinstance(x, dict):
        raise ValueError("An order line could not be read.")
    try:
        font = int(x.get("font", 1))
    except (TypeError, ValueError):
        raise ValueError(f"Font must be a number, got '{x.get('font')}'.") from None
    finish = str(x.get("finish") or "matte")
    review = x.get("review") or []
    if not isinstance(review, list):
        review = [str(review)]
    return {"design": str(x.get("design") or "").strip(), "pack": str(x.get("pack") or "").strip(),
            "name": normalise_name(str(x.get("name") or "")), "line2": normalise_name(str(x.get("line2") or "")),
            "font": font, "finish": finish if finish in LEGACY_FINISHES else "matte",
            "personalization": str(x.get("personalization") or ""), "sku": str(x.get("sku") or ""),
            "review": [str(r) for r in review][:10]}


class Orders:
    def __init__(self, repo: Repo, svc, templates=None):
        self.repo = repo
        self.svc = svc
        self.templates = templates
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.last_job: str | None = None

    # -- reading ----------------------------------------------------------------------------------
    def problems(self, line: dict) -> list[str]:
        """Why a line cannot be made yet (empty = it can)."""
        cat = self.svc.catalog
        out = validate_line(OrderLine(line["design"], line["pack"], line["finish"], line["name"], line["line2"],
                                      line["font"]), cat)
        if not out:
            if not {"wide", "square"} <= set(self.svc.assets.art_sources(line["design"])):
                out.append(f"{cat.designs[line['design']].name} has no artwork yet.")
            try:
                with self.svc.lock:
                    self.svc.renderer.fonts.check_glyphs(line["name"] + line["line2"], int(line["font"]))
            except GlyphError as e:
                out.append(str(e))
            except Exception as e:  # noqa: BLE001 - e.g. fonts not downloaded yet: say so, keep the list working
                out.append(str(e))
        return out

    def to_json(self, row: OrderRow) -> dict:
        lines = []
        for ln in row.lines:
            ln = clean_line(ln)
            lines.append({**ln, "problems": self.problems(ln)})
        ready = bool(lines) and not any(ln["problems"] or ln["review"] for ln in lines)
        return {"id": row.id, "created_at": row.created_at.isoformat() if row.created_at else None,
                "order_date": row.order_date, "customer": row.customer, "lang": row.lang, "status": row.status,
                "lines": lines, "source": row.source, "runs": list(row.runs or []), "notes": row.notes,
                "ready": ready}

    def list(self, status: str | None = None) -> list[dict]:
        with self.repo.Session() as s:
            q = select(OrderRow).order_by(OrderRow.created_at, OrderRow.id)
            if status:
                q = q.where(OrderRow.status == status)
            rows = list(s.scalars(q))
        return [self.to_json(r) for r in rows]

    def row(self, order_id: str) -> OrderRow:
        with self.repo.Session() as s:
            r = s.get(OrderRow, order_id)
        if r is None:
            raise NotFound(f"Order '{order_id}' not found.")
        return r

    # -- writing ----------------------------------------------------------------------------------
    def import_csv(self, data: bytes) -> dict:
        if len(data) > MAX_CSV:
            raise ValueError("That file is too big for an order export (over 10 MB).")
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        res: ImportResult = parse_orders_csv(text, self.repo.setting("listings"), self.svc.catalog)
        added, existing = [], []
        with self.repo.Session() as s:
            for o in res.orders:
                if s.get(OrderRow, o["id"]) is not None:
                    existing.append(o["id"])
                    continue
                s.add(OrderRow(id=o["id"], order_date=o["order_date"], customer=o["customer"], lang=o["lang"],
                               lines=[clean_line(ln) for ln in o["lines"]], transactions=o["transactions"],
                               source=o["source"], runs=[], status="new"))
                added.append(o["id"])
            s.commit()
        to_check = sum(1 for o in res.orders if o["id"] in added and any(ln["review"] for ln in o["lines"]))
        return {"rows": res.rows, "added": added, "already_imported": existing, "skipped": res.skipped,
                "to_check": to_check}

    def create(self, body: dict) -> dict:
        order_id = str(body.get("id") or "").strip()
        if not order_id:
            order_id = "M" + _dt.datetime.now().strftime("%y%m%d-%H%M%S")
        if not ORDER_ID_RE.match(order_id):
            raise ValueError("The order number can only use letters, digits, '.', '_' and '-'.")
        lines = [clean_line(x) for x in body.get("lines") or []]
        if not lines:
            raise ValueError("An order needs at least one line.")
        with self.repo.Session() as s:
            if s.get(OrderRow, order_id) is not None:
                raise ValueError(f"There is already an order {order_id}.")
            s.add(OrderRow(id=order_id, customer=str(body.get("customer") or "").strip()[:200],
                           lang="fr" if body.get("lang") == "fr" else "en", lines=lines, transactions=[],
                           source="manual", runs=[], status="new", notes=str(body.get("notes") or "")))
            s.commit()
        return self.to_json(self.row(order_id))

    def update(self, order_id: str, body: dict) -> dict:
        with self.repo.Session() as s:
            r = s.get(OrderRow, order_id)
            if r is None:
                raise NotFound(f"Order '{order_id}' not found.")
            if "lines" in body:
                lines = [clean_line(x) for x in body["lines"] or []]
                if not lines:
                    raise ValueError("An order needs at least one line (cancel the order instead).")
                r.lines = lines
            if "customer" in body:
                r.customer = str(body["customer"] or "").strip()[:200]
            if "lang" in body:
                r.lang = "fr" if body["lang"] == "fr" else "en"
            if "notes" in body:
                r.notes = str(body["notes"] or "")
            if "status" in body:
                if body["status"] not in STATUSES:
                    raise ValueError(f"Unknown status '{body['status']}'.")
                r.status = body["status"]
            s.commit()
        return self.to_json(self.row(order_id))

    def set_status(self, order_ids: list[str], status: str) -> int:
        if status not in STATUSES:
            raise ValueError(f"Unknown status '{status}'.")
        with self.repo.Session() as s:
            rows = [s.get(OrderRow, i) for i in order_ids]
            for r in rows:
                if r is not None:
                    r.status = status
            s.commit()
        return sum(1 for r in rows if r is not None)

    def delete(self, order_id: str) -> None:
        with self.repo.Session() as s:
            r = s.get(OrderRow, order_id)
            if r is None:
                raise NotFound(f"Order '{order_id}' not found.")
            s.delete(r)
            s.commit()

    # -- batches ----------------------------------------------------------------------------------
    def engine_orders(self, order_ids: list[str]) -> list[Order]:
        """The orders as the engine takes them, oldest first (the batcher fills sheets oldest first).
        Refuses orders that cannot be made yet, naming every reason."""
        if not order_ids:
            raise ValueError("Select at least one order.")
        rows, errors = [], []
        for oid in dict.fromkeys(order_ids):
            r = self.row(oid)
            info = self.to_json(r)
            for i, ln in enumerate(info["lines"], 1):
                for p in ln["problems"]:
                    errors.append(f"Order {oid}, line {i}: {p}")
                if ln["review"]:
                    errors.append(f"Order {oid}, line {i}: to check ({'; '.join(ln['review'])})")
            if r.status == "cancelled":
                errors.append(f"Order {oid} is cancelled.")
            rows.append(r)
        if errors:
            raise ValueError("Some orders cannot be made yet: " + " ".join(errors[:12])
                             + (" …" if len(errors) > 12 else ""))
        rows.sort(key=lambda r: (r.created_at, r.id))
        return [Order(r.id, [OrderLine(ln["design"], ln["pack"], ln.get("finish") or "matte", ln["name"],
                                       ln.get("line2", ""), int(ln.get("font", 1))) for ln in r.lines],
                      customer=r.customer, lang=r.lang) for r in rows]

    def plan(self, order_ids: list[str], unpaired: str = "bonus") -> dict:
        """What a batch of these orders would print, without rendering: sheets batched vs each order
        alone, bonus copies, and each order's envelope."""
        orders = self.engine_orders(order_ids)
        with self.svc.lock:
            producer = self.svc.producer()
            _, plan = producer.plan(orders, unpaired)
            alone = sum(len(producer.plan([o], unpaired)[1].sheets) for o in orders)
            prod = self.svc.catalog.production
        real: dict[str, int] = {}
        bonus: dict[str, int] = {}
        for sh in plan.sheets:
            for p in sh.filled:
                (bonus if p.bonus else real)[p.order_id] = (bonus if p.bonus else real).get(p.order_id, 0) + 1
        sizes: dict[str, int] = {}
        for sh in plan.sheets:
            sizes[sh.size] = sizes.get(sh.size, 0) + 1
        return {"orders": [o.order_id for o in orders], "sheets": len(plan.sheets), "sheets_alone": alone,
                "sheets_by_size": sizes, "bonus": sum(bonus.values()),
                "blank": sum(1 for sh in plan.sheets for p in sh.pieces if p is None),
                "envelopes": [{"order": o.order_id, **order_envelope(real.get(o.order_id, 0),
                                                                     bonus.get(o.order_id, 0), prod)}
                              for o in orders]}

    def start_batch(self, order_ids: list[str], unpaired: str = "bonus") -> dict:
        if unpaired not in ("bonus", "blank"):
            raise ValueError("Empty pieces are either bonus copies or blank.")
        orders = self.engine_orders(order_ids)            # refuse now, in plain words, not in the job
        with self._lock:
            if any(j["status"] == "running" for j in self._jobs.values()):
                raise ValueError("A batch is already being made. Wait for it to finish.")
            job_id = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
            job = {"id": job_id, "status": "running", "orders": [o.order_id for o in orders], "run": None,
                   "error": None, "started_at": _dt.datetime.now(_dt.timezone.utc).isoformat()}
            self._jobs[job_id] = job
            self.last_job = job_id
        threading.Thread(target=self._run_batch, args=(job, orders, unpaired), daemon=True).start()
        return dict(job)

    def _run_batch(self, job: dict, orders: list[Order], unpaired: str) -> None:
        ids = [o.order_id for o in orders]
        title = (f"Order {ids[0]} · {orders[0].customer}" if len(ids) == 1 and orders[0].customer else
                 f"Order {ids[0]}" if len(ids) == 1 else f"Batch · {len(ids)} orders ({', '.join(ids[:6])}"
                 + (" …" if len(ids) > 6 else "") + ")")
        try:
            row = run_production(self.svc, orders, title=title,
                                 request={"orders": ids, "unpaired": unpaired, "source": "orders"},
                                 unpaired=unpaired,
                                 studio3=self.templates.current_studio3_bytes if self.templates else None)
            with self.repo.Session() as s:
                for oid in ids:
                    r = s.get(OrderRow, oid)
                    if r is not None:
                        r.runs = list(r.runs or []) + [row.id]
                        if r.status == "new":
                            r.status = "made"
                s.commit()
            job.update(status="done", run=run_json(row))
        except ValueError as e:                          # plain-language problems (glyphs, packs...)
            job.update(status="error", error=str(e))
        except Exception as e:  # noqa: BLE001 - keep the app running, report in plain words
            log.exception("Batch failed")
            job.update(status="error", error=f"The batch stopped ({type(e).__name__}). The details are in the "
                                             "server log; no order was marked as made.")

    def job(self, job_id: str) -> dict | None:
        j = self._jobs.get(job_id)
        return dict(j) if j else None

    def latest_job(self) -> dict | None:
        return self.job(self.last_job) if self.last_job else None
