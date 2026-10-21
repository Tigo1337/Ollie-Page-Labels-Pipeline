"""Bulk artwork imports run in the background, so a large ZIP never hits a request timeout.

The upload is saved to a temporary file, then a worker thread imports it image by image and keeps
its progress here; the page polls it. One import at a time (single-user app).
"""
from __future__ import annotations

import datetime as _dt
import logging
import secrets
import shutil
import threading
from pathlib import Path
from typing import BinaryIO

from .bulk_import import import_zip
from .repo import Repo

log = logging.getLogger(__name__)


class ImportJobs:
    def __init__(self, repo: Repo, work_dir: Path):
        self.repo = repo
        self.work_dir = work_dir
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.last_id: str | None = None

    def start(self, upload: BinaryIO, filename: str = "") -> dict:
        with self._lock:
            if any(j["status"] == "running" for j in self._jobs.values()):
                raise ValueError("An import is already running. Wait for it to finish, then import again.")
            job_id = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
            self.work_dir.mkdir(parents=True, exist_ok=True)
            path = self.work_dir / f"{job_id}.zip"
            with path.open("wb") as f:
                shutil.copyfileobj(upload, f, 1024 * 1024)
            job = {"id": job_id, "file": filename, "status": "running", "done": 0, "total": 0, "current": "",
                   "report": None, "error": None, "started_at": _dt.datetime.now(_dt.timezone.utc).isoformat()}
            self._jobs[job_id] = job
            self.last_id = job_id
        threading.Thread(target=self._run, args=(job, path), daemon=True).start()
        return dict(job)

    def _run(self, job: dict, path: Path) -> None:
        def progress(done: int, total: int, current: str) -> None:
            job.update(done=done, total=total, current=current)
        try:
            with path.open("rb") as f:
                rep = import_zip(self.repo, f, progress)
            job.update(status="done", report=rep.__dict__)
        except ValueError as e:                 # plain-language problems (not a ZIP, ...)
            job.update(status="error", error=str(e))
        except Exception as e:  # noqa: BLE001 - keep the app running, report in plain words
            log.exception("Artwork import failed")
            job.update(status="error", error=f"The import stopped ({type(e).__name__}). The details are in the "
                                             "server log; images imported so far are kept.")
        finally:
            path.unlink(missing_ok=True)

    def get(self, job_id: str) -> dict | None:
        job = self._jobs.get(job_id)
        return dict(job) if job else None

    def latest(self) -> dict | None:
        return self.get(self.last_id) if self.last_id else None
