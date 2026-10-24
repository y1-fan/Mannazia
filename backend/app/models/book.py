from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ONLINE, Base
from app.time import UTCDateTime, utcnow


class Book(Base):
    __tablename__ = "books"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    manifest_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    api_version: Mapped[str] = mapped_column(String(4), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    creator: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(100))
    date_display: Mapped[str | None] = mapped_column(String(200))
    rights: Mapped[str | None] = mapped_column(Text)
    rights_uri: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    total_canvases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    download_state: Mapped[str] = mapped_column(
        String(20), default=ONLINE, nullable=False, index=True
    )
    tags: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    extra_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    source_snapshot: Mapped[str | None] = mapped_column(Text)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    last_refresh_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )

    canvases: Mapped[list[Canvas]] = relationship(
        back_populates="book",
        cascade="all, delete-orphan",
        order_by="Canvas.sequence",
        passive_deletes=True,
    )
    page_resources: Mapped[list[PageResource]] = relationship(
        back_populates="book", cascade="all, delete-orphan", passive_deletes=True
    )
    download_jobs: Mapped[list[DownloadJob]] = relationship(
        back_populates="book",
        cascade="all, delete-orphan",
        order_by="DownloadJob.created_at.desc()",
        passive_deletes=True,
    )
    progress: Mapped[ReadingProgress | None] = relationship(
        back_populates="book", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )

    @property
    def tag_list(self) -> list[str]:
        try:
            value = json.loads(self.tags or "[]")
            return [str(item) for item in value] if isinstance(value, list) else []
        except (TypeError, ValueError):
            return []

    @property
    def metadata_entries(self) -> list[dict[str, str]]:
        try:
            value = json.loads(self.metadata_json or "[]")
            return value if isinstance(value, list) else []
        except (TypeError, ValueError):
            return []

    @property
    def extra(self) -> dict[str, Any]:
        try:
            value = json.loads(self.extra_json or "{}")
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}


class Canvas(Base):
    __tablename__ = "canvases"
    __table_args__ = (
        UniqueConstraint("book_id", "sequence", name="uq_canvas_book_sequence"),
        Index("ix_canvas_book_sequence", "book_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    book_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str | None] = mapped_column(Text, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    image_url: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    image_service_id: Mapped[str | None] = mapped_column(Text)
    image_service_json: Mapped[str | None] = mapped_column(Text)
    related_resources_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    annotations_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    unsupported: Mapped[bool] = mapped_column(default=False, nullable=False)

    book: Mapped[Book] = relationship(back_populates="canvases")
    page_resource: Mapped[PageResource | None] = relationship(
        back_populates="canvas", cascade="all, delete-orphan", uselist=False, passive_deletes=True
    )

    @property
    def service(self) -> dict[str, Any] | None:
        if not self.image_service_json:
            return None
        try:
            value = json.loads(self.image_service_json)
            return value if isinstance(value, dict) else None
        except (TypeError, ValueError):
            return None

    @property
    def related_resources(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.related_resources_json or "[]")
            return value if isinstance(value, list) else []
        except (TypeError, ValueError):
            return []


class PageResource(Base):
    __tablename__ = "page_resources"
    __table_args__ = (UniqueConstraint("canvas_id", name="uq_page_canvas"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    book_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canvas_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("canvases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    request_url: Mapped[str | None] = mapped_column(Text)
    local_path: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    file_size: Mapped[int | None] = mapped_column(Integer)
    checksum: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )

    book: Mapped[Book] = relationship(back_populates="page_resources")
    canvas: Mapped[Canvas] = relationship(back_populates="page_resource")


class DownloadJob(Base):
    __tablename__ = "download_jobs"
    __table_args__ = (Index("ix_download_job_book_state", "book_id", "state"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    book_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    quality: Mapped[str] = mapped_column(
        String(20), default="research", server_default="research", nullable=False
    )
    total_pages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_pages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_pages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bytes_downloaded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    book: Mapped[Book] = relationship(back_populates="download_jobs")


class ReadingProgress(Base):
    __tablename__ = "reading_progress"

    book_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    canvas_id: Mapped[str | None] = mapped_column(String(32))
    source_canvas_id: Mapped[str | None] = mapped_column(Text)
    sequence_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )

    book: Mapped[Book] = relationship(back_populates="progress")


# Imported for convenience in app code that does `from app.models import ...`.
__all__ = [
    "Base",
    "Book",
    "Canvas",
    "DownloadJob",
    "PageResource",
    "ReadingProgress",
]
