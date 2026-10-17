"""Blob storage behind one small interface: Replit Object Storage or a local folder."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


class BlobStore(Protocol):
    name: str

    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def list(self, prefix: str = "") -> list[str]: ...


class BlobNotFound(FileNotFoundError):
    pass


class LocalBlobStore:
    name = "local"

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _p(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError(f"Bad storage key: {key}")
        return p

    def put(self, key: str, data: bytes) -> None:
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)

    def get(self, key: str) -> bytes:
        p = self._p(key)
        if not p.exists():
            raise BlobNotFound(f"File not found in storage: {key}")
        return p.read_bytes()

    def exists(self, key: str) -> bool:
        return self._p(key).exists()

    def delete(self, key: str) -> None:
        p = self._p(key)
        if p.exists():
            p.unlink()

    def list(self, prefix: str = "") -> list[str]:
        base = self.root.resolve()
        return sorted(str(p.relative_to(base)).replace("\\", "/") for p in base.rglob("*")
                      if p.is_file() and not p.name.endswith(".tmp")
                      and str(p.relative_to(base)).replace("\\", "/").startswith(prefix))


class ReplitBlobStore:
    """Replit Object Storage (needs the `replit-object-storage` package and a bucket)."""
    name = "replit"

    def __init__(self):
        from replit.object_storage import Client  # type: ignore[import-not-found]
        self.c = Client()

    def put(self, key: str, data: bytes) -> None:
        self.c.upload_from_bytes(key, data)

    def get(self, key: str) -> bytes:
        try:
            return self.c.download_as_bytes(key)
        except Exception as e:  # the client raises its own not-found type
            if not self.c.exists(key):
                raise BlobNotFound(f"File not found in storage: {key}") from e
            raise

    def exists(self, key: str) -> bool:
        return self.c.exists(key)

    def delete(self, key: str) -> None:
        self.c.delete(key, ignore_not_found=True)

    def list(self, prefix: str = "") -> list[str]:
        return sorted(o.name for o in self.c.list(prefix=prefix))


def make_store(kind: str, data_dir: Path) -> BlobStore:
    if kind in ("replit", "auto"):
        try:
            store = ReplitBlobStore()
            store.list("__probe__")
            log.info("Using Replit Object Storage")
            return store
        except Exception as e:
            if kind == "replit":
                raise RuntimeError(f"Replit Object Storage is not available: {e}") from e
            log.info("Replit Object Storage not available (%s); using local folder", e)
    return LocalBlobStore(data_dir / "blobs")
