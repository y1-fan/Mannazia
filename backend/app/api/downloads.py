from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.serializers import job_out
from app.errors import AppError
from app.models import (
    ACTIVE_JOB_STATES,
    JOB_CANCELLED,
    JOB_DOWNLOADING,
    JOB_FAILED,
    JOB_PAUSED,
    JOB_QUEUED,
    PAGE_FAILED,
    PAGE_PENDING,
    Book,
    DownloadJob,
    PageResource,
)
from app.schemas import DownloadJobOut
from app.services.state import book_stats, recompute_book_state
from app.time import utcnow

router = APIRouter(prefix="/api/downloads", tags=["downloads"])


def _get_job(session: Session, job_id: str) -> DownloadJob:
    job = session.get(DownloadJob, job_id)
    if job is None:
        raise AppError("Download job not found.", status_code=404, code="download_not_found")
    return job


def _get_book(session: Session, job: DownloadJob) -> Book:
    book = session.get(Book, job.book_id)
    if book is None:
        raise AppError("Book not found.", status_code=404, code="book_not_found")
    return book


@router.get("", summary="List download jobs")
def list_downloads(
    session: Session = Depends(get_db),
    book_id: str | None = Query(default=None, max_length=32),
    state: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    conditions = []
    if book_id:
        conditions.append(DownloadJob.book_id == book_id)
    if state:
        conditions.append(DownloadJob.state == state)
    total = int(session.scalar(select(func.count(DownloadJob.id)).where(*conditions)) or 0)
    rows = session.execute(
        select(DownloadJob, Book)
        .join(Book, Book.id == DownloadJob.book_id)
        .where(*conditions)
        .order_by(DownloadJob.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "items": [job_out(job, book.title) for job, book in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{job_id}", response_model=DownloadJobOut, summary="Get a download job")
def get_download(job_id: str, session: Session = Depends(get_db)) -> DownloadJobOut:
    job = _get_job(session, job_id)
    book = _get_book(session, job)
    return job_out(job, book.title)


@router.post("/{job_id}/pause", response_model=DownloadJobOut, summary="Pause a download")
async def pause_download(
    job_id: str, request: Request, session: Session = Depends(get_db)
) -> DownloadJobOut:
    job = _get_job(session, job_id)
    book = _get_book(session, job)
    if job.state == JOB_PAUSED:
        return job_out(job, book.title)
    if job.state not in {JOB_QUEUED, JOB_DOWNLOADING}:
        raise AppError(
            "Only queued or active downloads can be paused.",
            status_code=409,
            code="download_not_active",
        )
    job.state = JOB_PAUSED
    job.error = None
    job.updated_at = utcnow()
    book.download_state = "paused"
    session.commit()
    await request.app.state.download_manager.stop_async(job.id, cancel=False)
    session.expire_all()
    job = _get_job(session, job_id)
    book = _get_book(session, job)
    return job_out(job, book.title)


@router.post("/{job_id}/resume", response_model=DownloadJobOut, summary="Resume a paused download")
async def resume_download(
    job_id: str, request: Request, session: Session = Depends(get_db)
) -> DownloadJobOut:
    job = _get_job(session, job_id)
    book = _get_book(session, job)
    manager = request.app.state.download_manager
    if job.state not in {JOB_PAUSED}:
        raise AppError(
            "Only paused downloads can be resumed.", status_code=409, code="download_not_paused"
        )
    if manager.is_running(job.id):
        raise AppError(
            "The download is still stopping; try again in a moment.",
            status_code=409,
            code="download_stopping",
        )
    other = session.scalar(
        select(DownloadJob).where(
            DownloadJob.book_id == book.id,
            DownloadJob.id != job.id,
            DownloadJob.state.in_(ACTIVE_JOB_STATES),
        )
    )
    if other is not None:
        raise AppError(
            "Another download is active for this book.",
            status_code=409,
            code="download_already_active",
            details={"job_id": other.id},
        )
    _reset_failed_pages(session, book.id)
    stats = book_stats(session, book.id)
    job.state = JOB_QUEUED
    job.error = None
    job.completed_at = None
    job.total_pages = stats.total_pages
    job.completed_pages = stats.completed_pages
    job.failed_pages = stats.failed_pages
    job.updated_at = utcnow()
    book.download_state = "queued"
    session.commit()
    manager.start(job.id)
    return job_out(job, book.title)


@router.post("/{job_id}/cancel", response_model=DownloadJobOut, summary="Cancel a download")
async def cancel_download(
    job_id: str, request: Request, session: Session = Depends(get_db)
) -> DownloadJobOut:
    job = _get_job(session, job_id)
    book = _get_book(session, job)
    if job.state == JOB_CANCELLED:
        return job_out(job, book.title)
    if job.state not in {JOB_QUEUED, JOB_DOWNLOADING, JOB_PAUSED}:
        raise AppError(
            "This download has already finished.",
            status_code=409,
            code="download_finished",
        )
    job.state = JOB_CANCELLED
    job.completed_at = utcnow()
    job.error = None
    job.updated_at = utcnow()
    recompute_book_state(session, book, request.app.state.storage, verify_files=False)
    session.commit()
    await request.app.state.download_manager.stop_async(job.id, cancel=True)
    session.expire_all()
    job = _get_job(session, job_id)
    book = _get_book(session, job)
    return job_out(job, book.title)


@router.post("/{job_id}/retry", response_model=DownloadJobOut, summary="Retry failed pages")
async def retry_download(
    job_id: str, request: Request, session: Session = Depends(get_db)
) -> DownloadJobOut:
    job = _get_job(session, job_id)
    book = _get_book(session, job)
    manager = request.app.state.download_manager
    if job.state not in {JOB_FAILED, JOB_PAUSED, JOB_CANCELLED}:
        raise AppError(
            "Only failed, paused or cancelled downloads can be retried.",
            status_code=409,
            code="download_not_retryable",
        )
    if manager.is_running(job.id):
        raise AppError(
            "The download is still stopping; try again in a moment.",
            status_code=409,
            code="download_stopping",
        )
    other = session.scalar(
        select(DownloadJob).where(
            DownloadJob.book_id == book.id,
            DownloadJob.id != job.id,
            DownloadJob.state.in_(ACTIVE_JOB_STATES),
        )
    )
    if other is not None:
        raise AppError(
            "Another download is active for this book.",
            status_code=409,
            code="download_already_active",
            details={"job_id": other.id},
        )
    _reset_failed_pages(session, book.id)
    stats = book_stats(session, book.id)
    job.state = JOB_QUEUED
    job.error = None
    job.completed_at = None
    job.total_pages = stats.total_pages
    job.completed_pages = stats.completed_pages
    job.failed_pages = stats.failed_pages
    job.updated_at = utcnow()
    book.download_state = "queued"
    session.commit()
    manager.start(job.id)
    return job_out(job, book.title)


def _reset_failed_pages(session: Session, book_id: str) -> None:
    pages = session.scalars(
        select(PageResource).where(
            PageResource.book_id == book_id, PageResource.status == PAGE_FAILED
        )
    ).all()
    for page in pages:
        page.status = PAGE_PENDING
        page.error = None
