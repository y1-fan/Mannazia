from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Book, Canvas, DownloadJob, PageResource, ReadingProgress
from app.schemas import (
    BookDetailOut,
    BookSummaryOut,
    CanvasOut,
    DownloadJobOut,
    MetadataEntryOut,
)
from app.services.covers import cover_page_available, cover_sequence
from app.services.state import active_job as find_active_job
from app.services.state import book_stats, latest_job
from app.services.storage import Storage


def job_out(job: DownloadJob, book_title: str | None = None) -> DownloadJobOut:
    denominator = job.total_pages or 0
    percent = 0.0
    if denominator:
        percent = round(min(100.0, job.completed_pages / denominator * 100), 1)
    return DownloadJobOut(
        id=job.id,
        book_id=job.book_id,
        book_title=book_title,
        state=job.state,
        quality=job.quality,
        total_pages=job.total_pages,
        completed_pages=job.completed_pages,
        failed_pages=job.failed_pages,
        bytes_downloaded=job.bytes_downloaded,
        progress_percent=percent,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )


def book_summary(session: Session, book: Book, storage: Storage) -> BookSummaryOut:
    stats = book_stats(session, book.id)
    progress = session.get(ReadingProgress, book.id)
    unsupported = max(0, book.total_canvases - stats.total_pages)
    sequence = cover_sequence(book)
    cached_cover = storage.cover_path(book.id)
    has_local_cover = cached_cover is not None or (
        cover_page_available(session, book, sequence)
        if sequence is not None
        else stats.local_page_count > 0
    )
    return BookSummaryOut(
        id=book.id,
        title=book.title,
        creator=book.creator,
        thumbnail_url=book.thumbnail_url,
        local_cover_url=(f"/api/books/{book.id}/cover" if has_local_cover else None),
        download_state=book.download_state,
        total_canvases=book.total_canvases,
        total_pages=stats.total_pages,
        completed_pages=stats.completed_pages,
        failed_pages=stats.failed_pages,
        unsupported_canvases=unsupported,
        tags=book.tag_list,
        last_read_index=progress.sequence_index if progress else 0,
        imported_at=book.imported_at,
        updated_at=book.updated_at,
    )


def book_detail(session: Session, book: Book, storage: Storage) -> BookDetailOut:
    summary = book_summary(session, book, storage)
    active = find_active_job(session, book.id)
    latest = latest_job(session, book.id)
    extra = book.extra
    required = extra.get("required_statement") or {}
    if not isinstance(required, dict):
        required = {}
    return BookDetailOut(
        **summary.model_dump(),
        manifest_url=book.manifest_url,
        api_version=book.api_version,
        description=book.description,
        language=book.language,
        date=book.date_display,
        rights=book.rights,
        rights_uri=book.rights_uri,
        metadata=[MetadataEntryOut(**item) for item in book.metadata_entries],
        summary=str(extra.get("summary") or book.description or ""),
        provider=str(extra.get("provider") or ""),
        required_statement={str(k): str(v) for k, v in required.items()},
        homepage=extra.get("homepage") or [],
        rendering=extra.get("rendering") or [],
        see_also=extra.get("see_also") or [],
        structures=extra.get("structures") or [],
        warnings=[
            warning
            for warning in (extra.get("warnings") or [])
            if not str(warning).startswith("Reading quality kept color")
        ],
        source_manifest_id=extra.get("manifest_id"),
        last_refresh_at=book.last_refresh_at,
        downloaded_bytes=_downloaded_bytes(session, book.id),
        local_storage_bytes=storage.local_copy_bytes(book.id),
        archive_bytes=storage.archive_bytes(book.id),
        active_job=job_out(active, book.title) if active else None,
        latest_job=job_out(latest, book.title) if latest else None,
    )


def _downloaded_bytes(session: Session, book_id: str) -> int:
    from sqlalchemy import func, select

    return int(
        session.scalar(
            select(func.coalesce(func.sum(PageResource.file_size), 0)).where(
                PageResource.book_id == book_id,
                PageResource.status == "complete",
            )
        )
        or 0
    )


def canvas_out(canvas: Canvas, page: PageResource | None, storage: Storage) -> CanvasOut:
    service = canvas.service
    local_available = bool(page is not None and page.status == "complete" and page.local_path)
    local_url = f"/api/books/{canvas.book_id}/pages/{canvas.sequence}" if local_available else None
    thumbnail = canvas.thumbnail_url
    if not thumbnail and canvas.image_url:
        if canvas.image_service_id:
            thumbnail = f"{canvas.image_service_id}/full/400,/0/default.jpg"
        else:
            thumbnail = canvas.image_url
    local_thumbnail_url = None
    if storage.thumbnail_path(canvas.book_id, canvas.sequence) is not None:
        local_thumbnail_url = f"/api/books/{canvas.book_id}/thumbs/{canvas.sequence}"
    return CanvasOut(
        id=canvas.id,
        source_id=canvas.source_id,
        index=canvas.sequence,
        label=canvas.label,
        width=canvas.width,
        height=canvas.height,
        image_url=canvas.image_url,
        thumbnail_url=thumbnail,
        local_thumbnail_url=local_thumbnail_url,
        image_service_id=canvas.image_service_id,
        service=service,
        unsupported=canvas.unsupported,
        local_available=local_available,
        local_url=local_url,
        view_url=local_url or canvas.image_url,
        page_status=page.status if page is not None else "unsupported",
    )
