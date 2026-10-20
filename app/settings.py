"""Runtime settings, all from environment variables (Replit Secrets / env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_url: str
    storage: str            # "local" | "replit" | "auto"
    api_secret: str | None
    config_dir: Path
    frontend_dist: Path
    layouts_dir: Path = REPO / "layouts"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("LABELS_DATA_DIR", REPO / "data"))
    db = os.environ.get("LABELS_DATABASE_URL") or os.environ.get("DATABASE_URL") \
        or f"sqlite:///{data_dir / 'app.db'}"
    for prefix in ("postgres://", "postgresql://"):  # use the psycopg 3 driver
        if db.startswith(prefix):
            db = "postgresql+psycopg://" + db[len(prefix):]
    return Settings(
        data_dir=data_dir,
        database_url=db,
        storage=os.environ.get("LABELS_STORAGE", "auto"),
        api_secret=os.environ.get("LABELS_API_SECRET") or None,
        config_dir=Path(os.environ.get("LABELS_CONFIG_DIR", REPO / "config")),
        frontend_dist=REPO / "frontend" / "dist",
        layouts_dir=Path(os.environ.get("LABELS_LAYOUTS_DIR", REPO / "layouts")),
    )
