"""SQLAlchemy models. SQLite by default; any SQLAlchemy URL (e.g. Postgres) works."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Setting(Base):
    """Editable configuration blobs: production, sizes, packs, finishes, fonts, texts."""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list] = mapped_column(JSON)


class DesignRow(Base):
    __tablename__ = "designs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    fill: Mapped[str] = mapped_column(String(9))
    stroke: Mapped[str] = mapped_column(String(9))
    char_end: Mapped[float] = mapped_column(Float)
    stroke_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    cap_frac: Mapped[float] = mapped_column(Float, default=0.52)
    position: Mapped[int] = mapped_column(Integer, default=0)
    # artwork: content hash + pixel size of the image the engine crops from
    wide_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    wide_w: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wide_h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wide_orig_ext: Mapped[str | None] = mapped_column(String(8), nullable=True)
    square_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    square_w: Mapped[int | None] = mapped_column(Integer, nullable=True)
    square_h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    square_ext: Mapped[str | None] = mapped_column(String(8), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class PresetRow(Base):
    __tablename__ = "presets"
    design_id: Mapped[str] = mapped_column(ForeignKey("designs.id", ondelete="CASCADE"), primary_key=True)
    size_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)


class RunRow(Base):
    """One production run (an order or a batch): its files live in blob storage under runs/<id>/."""
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    title: Mapped[str] = mapped_column(String(200))
    prefix: Mapped[str] = mapped_column(String(200))
    request: Mapped[dict] = mapped_column(JSON)
    files: Mapped[list] = mapped_column(JSON)
    summary: Mapped[dict] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON)
    notes: Mapped[str] = mapped_column(Text, default="")


def make_session_factory(url: str):
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk(dbapi_conn, _rec):  # pragma: no cover - trivial
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
