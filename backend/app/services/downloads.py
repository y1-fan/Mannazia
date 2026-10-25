from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.config import Settings
from app.db import Database
from app.iiif.fetcher import Fetcher, FetchError
from app.iiif.images import ImageServiceResolver
from app.models import (
    ACTIVE_JOB_STATES,
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_DOWNLOADING,
    JOB_FAILED,
    JOB_PAUSED,
    JOB_QUEUED,
    PAGE_COMPLETE,
    PAGE_DOWNLOADING,
    PAGE_FAILED,
    PAGE_PENDING,
    Book,
    Canvas,
    DownloadJob,
    PageResource,
)
from app.services.covers import cache_local_cover, ensure_book_cover
from app.services.image_processing import (
    PROCESSING_FAILED_WARNING,
    ImageProcessingError,
    convert_tiff_to_png,
    process_page_image,
)
from app.services.image_validation import DownloadValidationError, validate_image_file
from app.services.qualities import effective_max_width
from app.services.state import (
    book_stats,
    mark_interrupted_jobs_paused,
    recompute_book_state,
    reconcile_page_states,
    verify_local_files,
)
from app.services.storage import EXT_BY_FORMAT, Storage, StorageError
from app.time import utcnow

logger = logging.getLogger(__name__)


class _Stopped(Exception):
    pass


@dataclass
class _Control:
    pause: bool = False
    cancel: bool = False

    @property
    def stopped(self) -> bool:
        return self.pause or self.cancel


@dataclass
class _PageWork:
    page_id: str
    sequence: int
    image_url: str | None
    service_id: str | None
    service_json: dict[str, Any] | None
    canvas_width: int | None
    canvas_height: int | None
    max_width: int
    quality: str


class DownloadManager:
    """In-process async download worker backed by SQLite state."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        storage: Storage,
        fetcher: Fetcher,
        resolver: ImageServiceResolver,
    ) -> None:
        self.settings = settings
        self.db = db
        self.storage = storage
        self.fetcher = fetcher
        self.resolver = resolver
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._controls: dict[str, _Control] = {}
        self._semaphore = asyncio.Semaphore(settings.download_concurrency)
        self._shutting_down = False

    # ------------------------------------------------------------------ lifecycle
    async def startup(self) -> None:
        removed = self.storage.cleanup_temporary_files()
        if removed:
            logger.info("Removed %s stale partial download file(s)", removed)
        auto_resume: list[str] = []
        with self.db.session() as session:
            paused = mark_interrupted_jobs_paused(session)
            reset = reconcile_page_states(session)
            if paused or reset:
                logger.info(
                    "Reconciled %s interrupted job(s) and %s in-flight page(s)", paused, reset
                )
            books = session.scalars(select(Book)).all()
            for book in books:
                ensure_book_cover(session, book)
                recompute_book_state(session, book, self.storage, verify_files=True)
                cache_local_cover(session, book, self.storage, self.settings)
                # Upgrade complete downloads created before CBZ packaging existed.
                self._archive_completed_book(session, book)
            if self.settings.auto_resume_downloads:
                jobs = session.scalars(
                    select(DownloadJob).where(
                        DownloadJob.state == JOB_PAUSED,
                        DownloadJob.error.like("%interrupted by an application restart%"),
                    )
                ).all()
                for job in jobs:
                    job.state = JOB_QUEUED
                    job.error = None
                    auto_resume.append(job.id)
        for job_id in auto_resume:
            self.start(job_id)

    async def shutdown(self) -> None:
        self._shutting_down = True
        for control in self._controls.values():
            control.pause = True
        tasks = list(self._tasks.items())
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(task for _, task in tasks), return_exceptions=True),
                    timeout=4.0,
                )
            except TimeoutError:
                for _job_id, task in tasks:
                    task.cancel()
                await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
        with self.db.session() as session:
            jobs = session.scalars(
                select(DownloadJob).where(DownloadJob.state.in_([JOB_QUEUED, JOB_DOWNLOADING]))
            ).all()
            for job in jobs:
                job.state = JOB_PAUSED
                job.error = job.error or "Download was interrupted by application shutdown."
                job.updated_at = utcnow()
            reconcile_page_states(session)
            for book in session.scalars(select(Book)).all():
                recompute_book_state(session, book, self.storage, verify_files=False)
        logger.info("Download manager stopped")

    # ------------------------------------------------------------------ controls
    def start(self, job_id: str) -> bool:
        if self._shutting_down:
            return False
        existing = self._tasks.get(job_id)
        if existing is not None and not existing.done():
            return False
        control = _Control()
        self._controls[job_id] = control
        task = asyncio.create_task(self._run(job_id), name=f"download-{job_id}")
        self._tasks[job_id] = task

        def _cleanup(_task: asyncio.Task[None]) -> None:
            self._tasks.pop(job_id, None)
            self._controls.pop(job_id, None)

        task.add_done_callback(_cleanup)
        return True

    def pause(self, job_id: str) -> None:
        control = self._controls.get(job_id)
        if control:
            control.pause = True

    def cancel(self, job_id: str) -> None:
        control = self._controls.get(job_id)
        if control:
            control.cancel = True

    def is_running(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        return task is not None and not task.done()

    async def stop_async(self, job_id: str, *, cancel: bool = False, timeout: float = 8.0) -> None:
        """Request a graceful stop and wait for the worker to acknowledge it."""
        control = self._controls.get(job_id)
        if control is not None:
            if cancel:
                control.cancel = True
            else:
                control.pause = True
        task = self._tasks.get(job_id)
        if task is None or task.done():
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Download task %s ended with an error while stopping", job_id)

    def running_job_ids(self) -> list[str]:
        return [job_id for job_id, task in self._tasks.items() if not task.done()]

    # ------------------------------------------------------------------ main loop
    async def _run(self, job_id: str) -> None:
        control = self._controls.setdefault(job_id, _Control())
        try:
            work, book_id = self._prepare_job(job_id)
            if not work:
                self._finish(job_id, book_id, control)
                return
            await self._run_pages(job_id, book_id, work, control)
            self._finish(job_id, book_id, control)
        except asyncio.CancelledError:
            self._mark_stopped(job_id)
            raise
        except Exception:
            logger.exception("Download job %s crashed", job_id)
            self._mark_failed(job_id, "The download task stopped unexpectedly.")
        finally:
            if job_id in self._tasks:
                # The done callback performs final cleanup; nothing to await here.
                pass

    def _prepare_job(self, job_id: str) -> tuple[list[_PageWork], str]:
        with self.db.session() as session:
            job = session.get(DownloadJob, job_id)
            if job is None:
                raise RuntimeError("Download job no longer exists")
            if job.state not in {JOB_QUEUED, JOB_DOWNLOADING}:
                return [], job.book_id
            book = session.get(Book, job.book_id)
            if book is None:
                raise RuntimeError("Book no longer exists")
            job.state = JOB_DOWNLOADING
            job.updated_at = utcnow()
            job.error = None
            book.download_state = "downloading"
            book.updated_at = utcnow()
            session.flush()

            stats = book_stats(session, book.id)
            job.total_pages = stats.total_pages
            job.completed_pages = stats.completed_pages
            job.failed_pages = stats.failed_pages
            job.bytes_downloaded = stats.bytes_downloaded
            max_width = effective_max_width(job.quality, self.settings.download_max_width)

            rows = session.execute(
                select(PageResource, Canvas)
                .join(Canvas, Canvas.id == PageResource.canvas_id)
                .where(
                    PageResource.book_id == book.id,
                    PageResource.status.in_([PAGE_PENDING, PAGE_FAILED, PAGE_DOWNLOADING]),
                )
                .order_by(Canvas.sequence)
            ).all()
            work: list[_PageWork] = []
            for page, canvas in rows:
                if not canvas.image_url:
                    continue
                service_json = None
                if canvas.image_service_json:
                    try:
                        service_json = json.loads(canvas.image_service_json)
                    except (TypeError, ValueError):
                        service_json = None
                work.append(
                    _PageWork(
                        page_id=page.id,
                        sequence=canvas.sequence,
                        image_url=canvas.image_url,
                        service_id=canvas.image_service_id,
                        service_json=service_json,
                        canvas_width=canvas.width,
                        canvas_height=canvas.height,
                        max_width=max_width,
                        quality=job.quality,
                    )
                )
            return work, book.id

    async def _run_pages(
        self,
        job_id: str,
        book_id: str,
        work: list[_PageWork],
        control: _Control,
    ) -> None:
        queue: asyncio.Queue[_PageWork | None] = asyncio.Queue()
        for item in work:
            queue.put_nowait(item)
        worker_count = min(self.settings.download_concurrency, max(1, len(work)))
        for _ in range(worker_count):
            queue.put_nowait(None)

        async def worker() -> None:
            while True:
                item = await queue.get()
                try:
                    if item is None:
                        return
                    if control.stopped or self._shutting_down:
                        continue
                    await self._download_page(job_id, book_id, item, control)
                finally:
                    queue.task_done()

        await asyncio.gather(*(worker() for _ in range(worker_count)))

    async def _download_page(
        self, job_id: str, book_id: str, work: _PageWork, control: _Control
    ) -> None:
        async with self._semaphore:
            if control.stopped or self._shutting_down:
                return
            temp_path: Path | None = None
            try:
                with self.db.session() as session:
                    page = session.get(PageResource, work.page_id)
                    job = session.get(DownloadJob, job_id)
                    if page is None or job is None:
                        return
                    if job.state != JOB_DOWNLOADING:
                        return
                    page.status = PAGE_DOWNLOADING
                    page.attempts += 1
                    page.error = None
                    session.flush()

                request = await self.resolver.request_for(
                    image_url=work.image_url,
                    service_id=work.service_id,
                    service_json=work.service_json,
                    canvas_width=work.canvas_width,
                    canvas_height=work.canvas_height,
                    max_width=work.max_width,
                )
                if control.stopped or self._shutting_down:
                    self._reset_page_if_stopped(work.page_id)
                    return

                temp_path = self.storage.pages_dir(book_id) / (
                    f".tmp-{work.sequence:06d}-{secrets.token_hex(4)}.part"
                )
                last_error: FetchError | DownloadValidationError | None = None
                for attempt in range(1, self.settings.download_retries + 1):
                    try:
                        await self.fetcher.download_to_file(
                            request.url, temp_path, max_bytes=self.settings.max_image_bytes
                        )
                        source_format, _source_mime, _sw, _sh = validate_image_file(temp_path)
                        warning = None
                        if work.quality in {"reading", "standard", "appreciation"}:
                            try:
                                warning = process_page_image(temp_path, work.quality)
                            except ImageProcessingError as exc:
                                warning = PROCESSING_FAILED_WARNING
                                logger.warning(
                                    "Page %s could not be processed for %s quality: %s",
                                    work.sequence,
                                    work.quality,
                                    exc,
                                )
                                if source_format == "TIFF":
                                    convert_tiff_to_png(temp_path)
                        elif source_format == "TIFF":
                            # Research keeps pixels losslessly, but browsers cannot display TIFF.
                            convert_tiff_to_png(temp_path)
                        image_format, mime, _width, _height = validate_image_file(temp_path)
                        extension = EXT_BY_FORMAT[image_format]
                        relative = self.storage.relative_page_path(work.sequence, extension)
                        final_path = self.storage.resolve_relative(book_id, relative)
                        final_path.parent.mkdir(parents=True, exist_ok=True)
                        size = temp_path.stat().st_size
                        checksum = _file_sha256(temp_path)
                        os.replace(temp_path, final_path)
                        temp_path = None
                        self._record_success(
                            book_id=book_id,
                            page_id=work.page_id,
                            relative=relative,
                            mime=mime,
                            size=size,
                            checksum=checksum,
                            request_url=request.url,
                            warning=warning,
                        )
                        return
                    except FetchError as exc:
                        last_error = exc
                        if not exc.retryable or attempt >= self.settings.download_retries:
                            break
                    except DownloadValidationError as exc:
                        last_error = exc
                        break
                    except ImageProcessingError as exc:
                        last_error = DownloadValidationError(str(exc))
                        break
                    except OSError as exc:
                        last_error = DownloadValidationError(f"Could not store the image: {exc}")
                        break
                    if control.stopped or self._shutting_down:
                        break
                    delay = min(
                        self.settings.download_retry_backoff * (2 ** (attempt - 1))
                        + random.uniform(0, 0.2),
                        15.0,
                    )
                    await asyncio.sleep(delay)

                if control.stopped or self._shutting_down:
                    self._reset_page_if_stopped(work.page_id)
                    return
                message = str(last_error) if last_error else "Unknown download error"
                if isinstance(last_error, FetchError) and last_error.code:
                    message = f"{last_error.code}: {last_error.message}"
                self._record_failure(work.page_id, message)
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)

    def _record_success(
        self,
        *,
        book_id: str,
        page_id: str,
        relative: str,
        mime: str,
        size: int,
        checksum: str,
        request_url: str,
        warning: str | None = None,
    ) -> None:
        with self.db.session() as session:
            page = session.get(PageResource, page_id)
            job = session.scalar(
                select(DownloadJob)
                .where(DownloadJob.book_id == book_id, DownloadJob.state == JOB_DOWNLOADING)
                .order_by(DownloadJob.created_at.desc())
                .limit(1)
            )
            if page is None:
                return
            page.status = PAGE_COMPLETE
            page.local_path = relative
            page.mime_type = mime
            page.file_size = size
            page.checksum = checksum
            page.request_url = request_url
            page.error = None
            page.updated_at = utcnow()
            if warning:
                book = session.get(Book, book_id)
                if book is not None:
                    extra = book.extra
                    warnings = [str(item) for item in extra.get("warnings", [])]
                    if warning not in warnings:
                        warnings.append(warning)
                        extra["warnings"] = warnings
                        book.extra_json = json.dumps(extra, ensure_ascii=False)
            if job is not None:
                job.completed_pages = job.completed_pages + 1
                job.bytes_downloaded = job.bytes_downloaded + size
                job.updated_at = utcnow()

    def _record_failure(self, page_id: str, message: str) -> None:
        with self.db.session() as session:
            page = session.get(PageResource, page_id)
            if page is None:
                return
            page.status = PAGE_FAILED
            page.error = message[:2000]
            page.updated_at = utcnow()

    def _reset_page_if_stopped(self, page_id: str) -> None:
        with self.db.session() as session:
            page = session.get(PageResource, page_id)
            if page is not None and page.status == PAGE_DOWNLOADING:
                page.status = PAGE_PENDING
                page.updated_at = utcnow()

    # ------------------------------------------------------------------ finalization
    def _finish(self, job_id: str, book_id: str, control: _Control) -> None:
        with self.db.session() as session:
            job = session.get(DownloadJob, job_id)
            book = session.get(Book, book_id)
            if job is None or book is None:
                return
            stats = book_stats(session, book.id)
            job.total_pages = stats.total_pages
            job.completed_pages = stats.completed_pages
            job.failed_pages = stats.failed_pages
            job.bytes_downloaded = stats.bytes_downloaded
            job.updated_at = utcnow()

            if control.cancel or job.state == JOB_CANCELLED:
                job.state = JOB_CANCELLED
                job.completed_at = utcnow()
                job.error = None
                self._reset_downloading_pages(session, book.id)
                session.flush()
                recompute_book_state(session, book, self.storage, verify_files=False)
            elif control.pause or job.state == JOB_PAUSED:
                job.state = JOB_PAUSED
                job.error = None
                self._reset_downloading_pages(session, book.id)
                book.download_state = "paused"
            else:
                missing = 0
                if stats.total_pages and stats.completed_pages == stats.total_pages:
                    _ok, missing = verify_local_files(session, book, self.storage)
                stats = book_stats(session, book.id)
                job.completed_pages = stats.completed_pages
                job.failed_pages = stats.failed_pages
                job.bytes_downloaded = stats.bytes_downloaded
                if stats.failed_pages or missing:
                    job.state = JOB_FAILED
                    job.error = (
                        f"{stats.failed_pages} page(s) failed. "
                        "Completed pages remain available; retry failed pages or resume later."
                    )
                else:
                    job.state = JOB_COMPLETED
                    job.error = None
                job.completed_at = utcnow()
                session.flush()
                if job.state == JOB_COMPLETED:
                    self._archive_completed_book(session, book)
                recompute_book_state(session, book, self.storage, verify_files=True)
            session.flush()
            self._write_manifest(session, book, job)

    def _archive_completed_book(self, session, book: Book) -> None:
        """Package a complete download into book.cbz and remove loose page files."""
        archive = self.storage.archive_path(book.id)
        rows = session.execute(
            select(PageResource, Canvas)
            .join(Canvas, Canvas.id == PageResource.canvas_id)
            .where(
                PageResource.book_id == book.id,
                PageResource.status == "complete",
                PageResource.local_path.is_not(None),
            )
            .order_by(Canvas.sequence)
        ).all()
        stats = book_stats(session, book.id)
        if not rows or stats.completed_pages != stats.total_pages or stats.failed_pages:
            return
        pages = [
            (canvas.sequence, page.local_path, page.file_size)
            for page, canvas in rows
            if page.local_path is not None
        ]
        if len(pages) != stats.completed_pages:
            return
        loose = [
            (sequence, relative)
            for sequence, relative, _size in pages
            if self.storage.resolve_relative(book.id, relative).is_file()
        ]
        if archive.is_file() and not loose and self.storage.archive_is_stored(book.id):
            return
        try:
            created = self.storage.create_page_archive(
                book.id, [(sequence, relative) for sequence, relative, _size in pages]
            )
            if created is None:
                return
            expected = {Path(relative).name: int(size or 0) for _sequence, relative, size in pages}
            valid, error = self.storage.verify_page_archive(book.id, expected)
            if not valid:
                logger.warning("Could not fully verify CBZ for book %s: %s", book.id, error)
                return
        except (OSError, StorageError, ValueError):
            logger.exception("Could not package CBZ for book %s", book.id)
            return
        cache_local_cover(session, book, self.storage, self.settings)
        for _sequence, relative in loose:
            try:
                self.storage.resolve_relative(book.id, relative).unlink(missing_ok=True)
            except (OSError, StorageError):
                logger.warning("Could not remove loose page file %s for book %s", relative, book.id)
        logger.info("Packaged book %s into %s (%s pages)", book.id, created.name, len(pages))

    def _mark_stopped(self, job_id: str) -> None:
        try:
            with self.db.session() as session:
                job = session.get(DownloadJob, job_id)
                if job is None:
                    return
                if job.state in {JOB_QUEUED, JOB_DOWNLOADING}:
                    job.state = JOB_PAUSED
                    job.error = job.error or "Download was interrupted by application shutdown."
                    job.updated_at = utcnow()
                book = session.get(Book, job.book_id)
                if book is not None:
                    self._reset_downloading_pages(session, book.id)
                    recompute_book_state(session, book, self.storage, verify_files=False)
                    self._write_manifest(session, book, job)
        except Exception:
            logger.exception("Could not persist stopped download job %s", job_id)

    def _mark_failed(self, job_id: str, message: str) -> None:
        try:
            with self.db.session() as session:
                job = session.get(DownloadJob, job_id)
                if job is None:
                    return
                job.state = JOB_FAILED
                job.error = message
                job.completed_at = utcnow()
                job.updated_at = utcnow()
                book = session.get(Book, job.book_id)
                if book is not None:
                    self._reset_downloading_pages(session, book.id)
                    recompute_book_state(session, book, self.storage, verify_files=False)
                    self._write_manifest(session, book, job)
        except Exception:
            logger.exception("Could not mark download job %s failed", job_id)

    def _reset_downloading_pages(self, session, book_id: str) -> None:
        pages = session.scalars(
            select(PageResource).where(
                PageResource.book_id == book_id, PageResource.status == PAGE_DOWNLOADING
            )
        ).all()
        for page in pages:
            page.status = PAGE_PENDING

    def _write_manifest(self, session, book: Book, job: DownloadJob) -> None:
        try:
            rows = session.execute(
                select(PageResource, Canvas)
                .join(Canvas, Canvas.id == PageResource.canvas_id)
                .where(PageResource.book_id == book.id)
                .order_by(Canvas.sequence)
            ).all()
            pages = []
            for page, canvas in rows:
                pages.append(
                    {
                        "sequence": canvas.sequence,
                        "canvas_id": canvas.id,
                        "source_canvas_id": canvas.source_id,
                        "source_url": page.source_url,
                        "request_url": page.request_url,
                        "local_path": page.local_path,
                        "mime_type": page.mime_type,
                        "file_size": page.file_size,
                        "sha256": page.checksum,
                        "status": page.status,
                        "error": page.error,
                    }
                )
            self.storage.write_download_manifest(
                book.id,
                {
                    "book_id": book.id,
                    "book_state": book.download_state,
                    "job_id": job.id,
                    "job_state": job.state,
                    "quality": job.quality,
                    "total_canvases": book.total_canvases,
                    "total_pages": job.total_pages,
                    "completed_pages": job.completed_pages,
                    "failed_pages": job.failed_pages,
                    "archive": (
                        self.storage.archive_path(book.id).name
                        if self.storage.archive_path(book.id).is_file()
                        else None
                    ),
                    "pages": pages,
                },
            )
        except (OSError, StorageError):
            logger.exception("Could not write download-manifest.json for book %s", book.id)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def job_is_active(job: DownloadJob) -> bool:
    return job.state in ACTIVE_JOB_STATES
