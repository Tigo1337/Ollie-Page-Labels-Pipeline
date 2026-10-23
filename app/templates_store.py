"""Cut templates in the app: the 7 layout templates and the .studio3 files saved from them.

The SVG / DXF / JSON / calibration PDF are made by the engine from layouts/*.json, so they are
never stored. A .studio3 is saved by hand in Silhouette Studio (the format is proprietary, the
app never writes one) and uploaded here; it is stored with the layout's geometry hash at upload
time. When the current geometry of its size no longer has that hash, it is outdated: shown in
red and never put in a bundle.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path

from engine.config import Catalog, geometry_hash, load_catalog
from engine.layout import Layout, LayoutError, current_layout, published

from .storage import BlobNotFound, BlobStore

PREFIX = "templates/"
MAX_STUDIO3 = 50 * 1024 * 1024


def studio3_key(layout_id: str) -> str:
    return f"{PREFIX}{layout_id}.studio3"


def _meta_key(layout_id: str) -> str:
    return f"{PREFIX}{layout_id}.studio3.json"


@dataclass
class Studio3:
    layout_id: str
    geometry_hash: str
    uploaded_at: str
    filename: str
    bytes: int
    current: bool

    def to_json(self) -> dict:
        return self.__dict__


class Templates:
    def __init__(self, store: BlobStore, config_dir: Path, layouts_dir: Path):
        self.store = store
        self.config_dir = config_dir
        self.layouts_dir = layouts_dir

    def catalog(self) -> Catalog:
        """Sheet and sizes from the config files: the layouts are built from these, not the DB."""
        return load_catalog(self.config_dir)

    def layout(self, layout_id: str) -> Layout:
        for versions in published(self.layouts_dir).values():
            for lay in versions:
                if lay.layout_id == layout_id:
                    return lay
        raise LayoutError(f"There is no layout '{layout_id}'.")

    def is_current(self, lay: Layout, cat: Catalog | None = None) -> bool:
        cat = cat or self.catalog()
        size = cat.sizes.get(lay.size)
        return size is not None and geometry_hash(cat.sheet, size) == lay.geometry_hash

    # -- .studio3 uploads ------------------------------------------------------
    def studio3(self, layout_id: str, cat: Catalog | None = None) -> Studio3 | None:
        try:
            meta = json.loads(self.store.get(_meta_key(layout_id)))
        except BlobNotFound:
            return None
        cat = cat or self.catalog()
        try:
            lay = self.layout(layout_id)
            current = meta["geometry_hash"] == lay.geometry_hash and self.is_current(lay, cat)
        except LayoutError:
            current = False
        return Studio3(layout_id=layout_id, geometry_hash=meta["geometry_hash"], uploaded_at=meta["uploaded_at"],
                       filename=meta["filename"], bytes=meta["bytes"], current=current)

    def save_studio3(self, layout_id: str, filename: str, data: bytes) -> Studio3:
        lay = self.layout(layout_id)
        if not filename.lower().endswith(".studio3"):
            raise ValueError("Please upload the .studio3 file you saved in Silhouette Studio.")
        if not data:
            raise ValueError("That file is empty.")
        if len(data) > MAX_STUDIO3:
            raise ValueError("That file is too big for a cut template (over 50 MB).")
        if not self.is_current(lay):
            raise ValueError(f"{layout_id} is not the current layout for its size any more; "
                             "make the template from the current layout instead.")
        self.store.put(studio3_key(layout_id), data)
        meta = {"geometry_hash": lay.geometry_hash, "filename": filename, "bytes": len(data),
                "uploaded_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")}
        self.store.put(_meta_key(layout_id), json.dumps(meta).encode())
        st = self.studio3(layout_id)
        assert st is not None
        return st

    def delete_studio3(self, layout_id: str) -> None:
        self.store.delete(studio3_key(layout_id))
        self.store.delete(_meta_key(layout_id))

    def current_studio3_bytes(self, layout_id: str) -> bytes | None:
        """The .studio3 to put in a bundle, or None when there is none or it is outdated."""
        st = self.studio3(layout_id)
        return self.store.get(studio3_key(layout_id)) if st and st.current else None

    def uploaded_ids(self) -> list[str]:
        return sorted(k[len(PREFIX):-len(".studio3.json")] for k in self.store.list(PREFIX)
                      if k.endswith(".studio3.json"))

    # -- listing ---------------------------------------------------------------
    def listing(self) -> dict:
        cat = self.catalog()
        rows, shown = [], set()
        for size in cat.sizes.values():
            try:
                lay = current_layout(cat.sheet, size, self.layouts_dir)
            except LayoutError as e:
                rows.append({"size": size.id, "size_label": size.label, "error": str(e)})
                continue
            shown.add(lay.layout_id)
            st = self.studio3(lay.layout_id, cat)
            rows.append({
                "layout_id": lay.layout_id, "size": size.id, "size_label": size.label, "dims": size.dims_label,
                "arrangement": lay.arrangement, "per_piece": lay.per_piece, "per_sheet": lay.per_sheet,
                "pairs": size.shape == "pair", "rows": lay.rows, "geometry_hash": lay.geometry_hash,
                "studio3": st.to_json() if st else None,
            })
        # uploads for layouts that are no longer current (red on the page, never bundled)
        outdated = [s.to_json() for lid in self.uploaded_ids() if lid not in shown
                    for s in [self.studio3(lid, cat)] if s is not None]
        return {"layouts": rows, "outdated": outdated}
