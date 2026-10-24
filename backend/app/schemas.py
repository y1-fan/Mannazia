from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class MetadataEntryOut(BaseModel):
    label: str
    value: str


class PreviewRequest(BaseModel):
    manifest_url: str = Field(min_length=1, max_length=4096)


class ImportRequest(BaseModel):
    manifest_url: str = Field(min_length=1, max_length=4096)
    preview_token: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=500)
    creator: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=20000)
    language: str | None = Field(default=None, max_length=100)
    date: str | None = Field(default=None, max_length=200)
    rights: str | None = Field(default=None, max_length=10000)
    rights_uri: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=20)


class ImportPreviewOut(BaseModel):
    manifest_url: str
    api_version: str
    title: str
    creator: str = ""
    description: str = ""
    language: str = ""
    date: str = ""
    rights: str = ""
    rights_uri: str = ""
    required_statement: dict[str, str] = Field(default_factory=dict)
    thumbnail_url: str | None = None
    canvas_count: int = 0
    image_canvas_count: int = 0
    metadata: list[MetadataEntryOut] = Field(default_factory=list)
    summary: str = ""
    provider: str = ""
    homepage: list[dict[str, Any]] = Field(default_factory=list)
    rendering: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    preview_token: str | None = None
    duplicate_of: str | None = None
    duplicate_title: str | None = None


class BookUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    creator: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=20000)
    language: str | None = Field(default=None, max_length=100)
    date: str | None = Field(default=None, max_length=200)
    rights: str | None = Field(default=None, max_length=10000)
    rights_uri: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=20)


class DownloadStartIn(BaseModel):
    quality: Literal["reading", "standard", "appreciation", "research"] = "research"


class DownloadJobOut(BaseModel):
    id: str
    book_id: str
    book_title: str | None = None
    state: str
    quality: str = "research"
    total_pages: int
    completed_pages: int
    failed_pages: int
    bytes_downloaded: int
    progress_percent: float
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class BookSummaryOut(BaseModel):
    id: str
    title: str
    creator: str | None = None
    thumbnail_url: str | None = None
    local_cover_url: str | None = None
    download_state: str
    total_canvases: int
    total_pages: int
    completed_pages: int
    failed_pages: int
    unsupported_canvases: int
    tags: list[str] = Field(default_factory=list)
    last_read_index: int = 0
    imported_at: datetime
    updated_at: datetime


class BookDetailOut(BookSummaryOut):
    manifest_url: str
    api_version: str
    description: str | None = None
    language: str | None = None
    date: str | None = None
    rights: str | None = None
    rights_uri: str | None = None
    metadata: list[MetadataEntryOut] = Field(default_factory=list)
    summary: str = ""
    provider: str = ""
    required_statement: dict[str, str] = Field(default_factory=dict)
    homepage: list[dict[str, Any]] = Field(default_factory=list)
    rendering: list[dict[str, Any]] = Field(default_factory=list)
    see_also: list[dict[str, Any]] = Field(default_factory=list)
    structures: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_manifest_id: str | None = None
    last_refresh_at: datetime | None = None
    downloaded_bytes: int = 0
    local_storage_bytes: int = 0
    archive_bytes: int = 0
    active_job: DownloadJobOut | None = None
    latest_job: DownloadJobOut | None = None


class BookListOut(BaseModel):
    items: list[BookSummaryOut]
    total: int
    limit: int
    offset: int


class CanvasOut(BaseModel):
    id: str
    source_id: str | None = None
    index: int
    label: str
    width: int | None = None
    height: int | None = None
    image_url: str | None = None
    thumbnail_url: str | None = None
    local_thumbnail_url: str | None = None
    image_service_id: str | None = None
    service: dict[str, Any] | None = None
    unsupported: bool = False
    local_available: bool = False
    local_url: str | None = None
    view_url: str | None = None
    page_status: str = "pending"


class CanvasListOut(BaseModel):
    book_id: str
    download_state: str
    total: int
    items: list[CanvasOut]


class ProgressIn(BaseModel):
    canvas_id: str | None = Field(default=None, max_length=32)
    source_canvas_id: str | None = Field(default=None, max_length=4096)
    sequence_index: int = Field(ge=0, le=1_000_000)


class ProgressOut(BaseModel):
    book_id: str
    canvas_id: str | None = None
    source_canvas_id: str | None = None
    sequence_index: int = 0
    updated_at: datetime | None = None


class StorageOut(BaseModel):
    books_bytes: int
    data_bytes: int
    config_bytes: int
    database_bytes: int
    book_count: int
    book_file_count: int
    free_bytes: int
    total_bytes: int


class SystemInfoOut(BaseModel):
    name: str
    version: str
    environment: str
    download_concurrency: int
    download_max_width: int
    cover_max_width: int
    download_image_format: str
    max_manifest_bytes: int
    max_image_bytes: int
    allowed_private_host_count: int
    allow_private_networks: bool
    auto_resume_downloads: bool
    security_notice: str


class HealthOut(BaseModel):
    status: str
    version: str
    database: str
    books_directory: str
    active_downloads: int


class MessageOut(BaseModel):
    message: str
