from __future__ import annotations

import asyncio
import json
import logging
import secrets
from typing import Any

from sqlalchemy import select

from app.config import Settings
from app.db import Database
from app.iiif.fetcher import Fetcher, FetchError
from app.models import Book, Canvas
from app.services.image_processing import (
    ImageProcessingError,
    convert_tiff_to_jpeg,
)
from app.services.image_validation import DownloadValidationError, validate_image_file
from app.services.storage import EXT_BY_FORMAT, Storage

logger = logging.getLogger(__name__)


class ThumbnailManager:
    """Fetch and cache page thumbnails in the background.

    Thumbnails are intentionally independent from download jobs: they never make
    a book partial/offline and they are kept when a local copy is removed.
    """

    def __init__(
        self,
        settings: Settings,
        db: Database,
        storage: Storage,
        fetcher: Fetcher,
    ) -> None:
        self.settings = settings
        self.db = db
        self.storage = storage
        self.fetcher = fetcher
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._semaphore = asyncio.Semaphore(settings.thumbnail_concurrency)
        self._shutting_down = False

    async def startup(self) -> None:
        if not self.settings.page_thumbnails_enabled:
            return
        with self.db.session() as session:
            book_ids = list(session.scalars(select(Book.id)).all())
        for book_id in book_ids:
            self.start(book_id)

    async def shutdown(self) -> None:
        self._shutting_down = True
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    def start(self, book_id: str) -> bool:
        if not self.settings.page_thumbnails_enabled or self._shutting_down:
            return False
        existing = self._tasks.get(book_id)
        if existing is not None and not existing.done():
            return False
        task = asyncio.create_task(self._run(book_id), name=f"thumbnails-{book_id}")
        self._tasks[book_id] = task

        def _cleanup(finished: asyncio.Task[None]) -> None:
            self._tasks.pop(book_id, None)
            if finished.cancelled():
                return
            exception = finished.exception()
            if exception is not None:
                logger.warning("Thumbnail task for book %s failed: %s", book_id, exception)

        task.add_done_callback(_cleanup)
        return True

    def cancel(self, book_id: str) -> None:
        task = self._tasks.get(book_id)
        if task is not None and not task.done():
            task.cancel()

    async def stop_async(self, book_id: str, *, timeout: float = 4.0) -> None:
        task = self._tasks.get(book_id)
        if task is None or task.done():
            return
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except (TimeoutError, asyncio.CancelledError):
            pass
        except Exception:
            logger.exception("Thumbnail task for book %s failed while stopping", book_id)

    async def _run(self, book_id: str) -> None:
        rows = self._book_canvases(book_id)
        if not rows:
            return
        queue: asyncio.Queue[tuple[int, str | None, str | None, dict[str, Any] | None]] = (
            asyncio.Queue()
        )
        for sequence, thumbnail_url, service_id, service_json in rows:
            if self.storage.thumbnail_path(book_id, sequence) is not None:
                continue
            queue.put_nowait((sequence, thumbnail_url, service_id, service_json))
        if queue.empty():
            return
        worker_count = min(self.settings.thumbnail_concurrency, max(1, queue.qsize()))
        for _ in range(worker_count):
            queue.put_nowait((-1, None, None, None))

        async def worker() -> None:
            while True:
                sequence, thumbnail_url, service_id, service_json = await queue.get()
                try:
                    if sequence < 0:
                        return
                    await self._fetch_one(
                        book_id, sequence, thumbnail_url, service_id, service_json
                    )
                finally:
                    queue.task_done()

        await asyncio.gather(*(worker() for _ in range(worker_count)))

    def _book_canvases(
        self, book_id: str
    ) -> list[tuple[int, str | None, str | None, dict[str, Any] | None]]:
        with self.db.session() as session:
            if session.get(Book, book_id) is None:
                return []
            canvases = session.scalars(
                select(Canvas).where(Canvas.book_id == book_id).order_by(Canvas.sequence)
            ).all()
            rows = []
            for canvas in canvases:
                try:
                    service_json = (
                        json.loads(canvas.image_service_json) if canvas.image_service_json else None
                    )
                except (TypeError, ValueError):
                    service_json = None
                rows.append(
                    (canvas.sequence, canvas.thumbnail_url, canvas.image_service_id, service_json)
                )
            return rows

    @staticmethod
    def _thumbnail_url(
        thumbnail_url: str | None, service_id: str | None, service_json: dict[str, Any] | None
    ) -> str | None:
        if thumbnail_url:
            return thumbnail_url
        if not service_id:
            return None
        profile = (service_json or {}).get("profile")
        level = ""
        values = profile if isinstance(profile, list) else [profile]
        for value in values:
            if isinstance(value, str) and "level0" in value.lower():
                level = "level0"
                break
        size = "max" if level == "level0" else "400,"
        return f"{service_id.rstrip('/')}/full/{size}/0/default.jpg"

    async def _fetch_one(
        self,
        book_id: str,
        sequence: int,
        thumbnail_url: str | None,
        service_id: str | None,
        service_json: dict[str, Any] | None,
    ) -> None:
        url = self._thumbnail_url(thumbnail_url, service_id, service_json)
        if not url:
            return
        async with self._semaphore:
            if self._shutting_down:
                return
            if self.storage.thumbnail_path(book_id, sequence) is not None:
                return
            book_dir = self.storage.book_dir(book_id)
            if not book_dir.is_dir():
                return
            thumbnails = self.storage.thumbnails_dir(book_id)
            temporary = thumbnails / f".tmp-{sequence:06d}-{secrets.token_hex(4)}.part"
            try:
                for attempt in range(1, min(self.settings.download_retries, 2) + 1):
                    try:
                        await self.fetcher.download_to_file(
                            url,
                            temporary,
                            max_bytes=self.settings.thumbnail_max_bytes,
                        )
                        image_format, _mime, _width, _height = validate_image_file(temporary)
                        if image_format == "TIFF":
                            convert_tiff_to_jpeg(temporary, quality=85)
                            image_format, _mime, _width, _height = validate_image_file(temporary)
                        extension = EXT_BY_FORMAT[image_format]
                        self.storage.store_thumbnail(book_id, sequence, temporary, extension)
                        return
                    except FetchError as exc:
                        if not exc.retryable or attempt >= min(self.settings.download_retries, 2):
                            logger.debug(
                                "Could not cache thumbnail %s for book %s: %s",
                                sequence,
                                book_id,
                                exc.message,
                            )
                            return
                        await asyncio.sleep(
                            min(self.settings.download_retry_backoff * (2 ** (attempt - 1)), 4.0)
                        )
                    except (DownloadValidationError, ImageProcessingError, OSError) as exc:
                        logger.debug(
                            "Could not store thumbnail %s for book %s: %s",
                            sequence,
                            book_id,
                            exc,
                        )
                        return
            finally:
                temporary.unlink(missing_ok=True)
