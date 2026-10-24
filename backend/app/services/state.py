from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ACTIVE_JOB_STATES,
    DOWNLOADING,
    ERROR,
    JOB_DOWNLOADING,
    JOB_FAILED,
    JOB_PAUSED,
    JOB_QUEUED,
    OFFLINE,
    ONLINE,
    PAGE_COMPLETE,
    PAGE_DOWNLOADING,
    PAGE_FAILED,
    PAGE_PENDING,
    PARTIAL,
    PAUSED,
    QUEUED,
    Book,
    DownloadJob,
    PageResource,
)
from app.services.storage import Storage, StorageError


@dataclass
class BookStats:
    total_pages: int = 0
    completed_pages: int = 0
    failed_pages: int = 0
    pending_pages: int = 0
    bytes_downloaded: int = 0
    missing_files: int = 0
    local_page_count: int = 0
    notes: list[str] = field(default_factory=list)


def book_stats(session: Session, book_id: str) -> BookStats:
    total_canvases = int(session.scalar(select(Book.total_canvases).where(Book.id == book_id)) or 0)
    rows = session.execute(
        select(
            PageResource.status,
            func.count(PageResource.id),
            func.coalesce(func.sum(PageResource.file_size), 0),
        )
        .where(PageResource.book_id == book_id)
        .group_by(PageResource.status)
    ).all()
    stats = BookStats()
    for status, count, size in rows:
        if status == PAGE_COMPLETE:
            stats.completed_pages = int(count)
            stats.bytes_downloaded = int(size or 0)
            stats.local_page_count = int(count)
        elif status == PAGE_FAILED:
            stats.failed_pages = int(count)
        elif status in (PAGE_DOWNLOADING, PAGE_PENDING):
            stats.pending_pages += int(count)
        stats.total_pages += int(count)
    if stats.total_pages < total_canvases:
        stats.notes.append(
            f"{total_canvases - stats.total_pages} canvas(es) have no supported primary "
            "image and cannot be saved offline."
        )
    return stats


def latest_job(session: Session, book_id: str) -> DownloadJob | None:
    return session.scalar(
        select(DownloadJob)
        .where(DownloadJob.book_id == book_id)
        .order_by(DownloadJob.created_at.desc(), DownloadJob.id.desc())
        .limit(1)
    )


def active_job(session: Session, book_id: str) -> DownloadJob | None:
    return session.scalar(
        select(DownloadJob)
        .where(DownloadJob.book_id == book_id, DownloadJob.state.in_(ACTIVE_JOB_STATES))
        .order_by(DownloadJob.created_at.desc(), DownloadJob.id.desc())
        .limit(1)
    )


def verify_local_files(
    session: Session, book: Book, storage: Storage, *, checksum: bool = True
) -> tuple[bool, int]:
    """Verify every completed page file; mark missing/corrupt resources failed."""
    pages = session.scalars(
        select(PageResource).where(
            PageResource.book_id == book.id, PageResource.status == PAGE_COMPLETE
        )
    ).all()
    missing = 0
    for page in pages:
        try:
            if not page.local_path:
                raise StorageError("No local path")
            if not storage.page_exists(book.id, page.local_path):
                raise StorageError("File is missing")
            size = storage.page_size(book.id, page.local_path)
            if page.file_size is not None and size != page.file_size:
                raise StorageError("File size does not match the download record")
            if (
                checksum
                and page.checksum
                and storage.page_sha256(book.id, page.local_path) != page.checksum
            ):
                raise StorageError("File checksum does not match the download record")
        except (OSError, StorageError) as exc:
            page.status = PAGE_FAILED
            page.error = f"Local file verification failed: {exc}"
            page.local_path = None
            page.file_size = None
            page.checksum = None
            missing += 1
    return missing == 0, missing


def recompute_book_state(
    session: Session, book: Book, storage: Storage, *, verify_files: bool = True
) -> str:
    running = active_job(session, book.id)
    if running is not None:
        mapping = {
            JOB_QUEUED: QUEUED,
            JOB_DOWNLOADING: DOWNLOADING,
            JOB_PAUSED: PAUSED,
        }
        book.download_state = mapping.get(running.state, PARTIAL)
        return book.download_state

    if verify_files:
        stats_before = book_stats(session, book.id)
        if stats_before.completed_pages:
            verify_local_files(session, book, storage)
        session.flush()

    stats = book_stats(session, book.id)
    last = latest_job(session, book.id)
    all_required_complete = stats.total_pages > 0 and stats.completed_pages == stats.total_pages
    all_canvases_covered = stats.total_pages == book.total_canvases

    if all_required_complete and all_canvases_covered:
        book.download_state = OFFLINE
    elif stats.completed_pages > 0:
        book.download_state = PARTIAL
    elif last is not None and last.state == JOB_FAILED:
        book.download_state = ERROR
    else:
        book.download_state = ONLINE
    return book.download_state


def reconcile_page_states(session: Session) -> int:
    """Reset page rows that were mid-flight when the process stopped."""
    pages = session.scalars(
        select(PageResource).where(PageResource.status == PAGE_DOWNLOADING)
    ).all()
    for page in pages:
        page.status = PAGE_PENDING
    return len(pages)


def mark_interrupted_jobs_paused(session: Session) -> int:
    jobs = session.scalars(
        select(DownloadJob).where(DownloadJob.state.in_([JOB_QUEUED, JOB_DOWNLOADING]))
    ).all()
    from app.time import utcnow

    for job in jobs:
        job.state = JOB_PAUSED
        job.error = job.error or "Download was interrupted by an application restart."
        job.updated_at = utcnow()
    return len(jobs)
