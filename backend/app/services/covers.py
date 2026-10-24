from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from io import BytesIO

from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.iiif.fetcher import Fetcher, FetchError
from app.iiif.images import ImageServiceResolver
from app.iiif.models import NormalizedCanvas
from app.models import Canvas, PageResource
from app.services.image_validation import DownloadValidationError, validate_image_file
from app.services.storage import EXT_BY_FORMAT, Storage

logger = logging.getLogger(__name__)

COVER_TERMS = (
    "front cover",
    "cover",
    "front board",
    "upper cover",
    "binding",
    "umschlag",
    "einband",
    "couverture",
    "plat sup",
    "portada",
    "copertina",
    "capa",
    "обложка",
    "封面",
    "書封",
    "书封",
    "表紙",
    "表纸",
)
BACK_COVER_TERMS = (
    "back cover",
    "rear cover",
    "back board",
    "lower cover",
    "封底",
    "封底",
    "裏表紙",
    "里表纸",
    "4th cover",
)


def _is_back_cover_label(label: str | None) -> bool:
    value = (label or "").strip().lower()
    return bool(value) and any(term in value for term in BACK_COVER_TERMS)


def _is_cover_label(label: str | None) -> bool:
    value = (label or "").strip().lower()
    if not value or _is_back_cover_label(value):
        return False
    return any(term in value for term in COVER_TERMS)


def choose_cover[T: (NormalizedCanvas, Canvas)](canvases: list[T]) -> T | None:
    """Prefer a Canvas explicitly labelled as the front cover, else the first image."""
    labelled = next(
        (
            canvas
            for canvas in canvases
            if _is_cover_label(getattr(canvas, "label", None)) and _has_image(canvas)
        ),
        None,
    )
    if labelled is not None:
        return labelled
    for canvas in canvases:
        if _has_image(canvas) and not _is_back_cover_label(getattr(canvas, "label", None)):
            return canvas
    return next((canvas for canvas in canvases if _has_image(canvas)), None)


def _has_image[T: (NormalizedCanvas, Canvas)](canvas: T) -> bool:
    if isinstance(canvas, NormalizedCanvas):
        return canvas.image is not None
    return bool(canvas.image_url)


def cover_url[T: (NormalizedCanvas, Canvas)](canvas: T) -> str | None:
    if isinstance(canvas, NormalizedCanvas):
        if canvas.thumbnail_url:
            return canvas.thumbnail_url
        if canvas.image is None:
            return None
        if canvas.image.service:
            return f"{canvas.image.service.id}/full/400,/0/default.jpg"
        return canvas.image.id
    if canvas.thumbnail_url:
        return canvas.thumbnail_url
    if canvas.image_service_id:
        return f"{canvas.image_service_id}/full/400,/0/default.jpg"
    return canvas.image_url


def cover_sequence(book: object) -> int | None:
    extra = getattr(book, "extra", {}) or {}
    value = extra.get("cover_sequence")
    return value if isinstance(value, int) and value > 0 else None


def ensure_book_cover(session: Session, book, canvases: list[Canvas] | None = None) -> None:
    """Backfill the selected cover for records imported before cover tracking existed."""
    extra = book.extra
    sequence = cover_sequence(book)
    if sequence is not None and book.thumbnail_url:
        return
    if canvases is None:
        canvases = list(
            session.scalars(
                select(Canvas).where(Canvas.book_id == book.id).order_by(Canvas.sequence)
            ).all()
        )
    chosen = choose_cover(canvases)
    if chosen is None:
        return
    if "source_thumbnail_url" not in extra:
        extra["source_thumbnail_url"] = book.thumbnail_url
    extra["cover_sequence"] = chosen.sequence
    book.thumbnail_url = cover_url(chosen) or book.thumbnail_url
    book.extra_json = json.dumps(extra, ensure_ascii=False)


def cover_page_available(session: Session, book, sequence: int | None) -> bool:
    if sequence is None:
        return False
    page = session.scalar(
        select(PageResource.id)
        .join(Canvas, Canvas.id == PageResource.canvas_id)
        .where(
            PageResource.book_id == book.id,
            Canvas.sequence == sequence,
            PageResource.status == "complete",
            PageResource.local_path.is_not(None),
        )
        .limit(1)
    )
    return page is not None


def cache_local_cover(session: Session, book, storage: Storage, settings: Settings) -> bool:
    """Create a display cover from a locally saved cover page.

    This must run before a local copy is deleted so the high-quality cover
    survives when the page archive/pages disappear.
    """
    if storage.cover_path(book.id) is not None:
        return True
    sequence = cover_sequence(book)
    if sequence is None:
        ensure_book_cover(session, book)
        sequence = cover_sequence(book)
    if sequence is None:
        return False
    page = session.scalar(
        select(PageResource)
        .join(Canvas, Canvas.id == PageResource.canvas_id)
        .where(
            PageResource.book_id == book.id,
            Canvas.sequence == sequence,
            PageResource.status == "complete",
            PageResource.local_path.is_not(None),
        )
        .limit(1)
    )
    if page is None or not page.local_path:
        return False

    temporary = storage.book_dir(book.id) / f".cover-local-{secrets.token_hex(4)}.part"
    try:
        payload = storage.read_page_bytes(book.id, page.local_path)
        with Image.open(BytesIO(payload)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            width, height = image.size
            target_width = min(width, settings.cover_max_width)
            target_height = max(1, round(height * target_width / width))
            if target_width != width:
                image = image.resize((target_width, target_height), Image.Resampling.LANCZOS)
            image.save(temporary, format="JPEG", quality=90, optimize=True)
        final = storage.book_dir(book.id) / "cover.jpg"
        os.replace(temporary, final)
        storage.remove_cover_files(book.id, keep="jpg")
        extra = book.extra
        extra["cover_local"] = final.name
        extra["cover_width"] = target_width
        extra["cover_height"] = target_height
        extra.pop("cover_error", None)
        extra["warnings"] = [
            warning
            for warning in extra.get("warnings", [])
            if not str(warning).startswith(
                ("Cover image", "No cover page", "The selected cover page")
            )
        ]
        book.extra_json = json.dumps(extra, ensure_ascii=False)
        logger.info("Cached local cover for book %s (%sx%s)", book.id, target_width, target_height)
        return True
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        logger.warning("Could not cache local cover for book %s: %s", book.id, exc)
        return False
    finally:
        temporary.unlink(missing_ok=True)


async def cache_cover(
    session: Session,
    book,
    storage: Storage,
    fetcher: Fetcher,
    resolver: ImageServiceResolver,
    settings: Settings,
) -> tuple[bool, str | None]:
    """Download the selected cover page at display resolution.

    This is intentionally separate from PageResource: caching a cover does not
    make the book partially downloaded and does not count toward offline state.
    """
    sequence = cover_sequence(book)
    if sequence is None:
        ensure_book_cover(session, book)
        sequence = cover_sequence(book)
    if sequence is None:
        return _cover_failure(book, "No cover page could be selected.")
    canvas = session.scalar(
        select(Canvas).where(Canvas.book_id == book.id, Canvas.sequence == sequence)
    )
    if canvas is None or not canvas.image_url:
        return _cover_failure(book, "The selected cover page has no image resource.")

    service_json = None
    if canvas.image_service_json:
        try:
            service_json = json.loads(canvas.image_service_json)
        except (TypeError, ValueError):
            service_json = None

    try:
        request = await resolver.request_for(
            image_url=canvas.image_url,
            service_id=canvas.image_service_id,
            service_json=service_json,
            canvas_width=canvas.width,
            canvas_height=canvas.height,
            max_width=settings.cover_max_width,
        )
    except (FetchError, ValueError) as exc:
        return _cover_failure(book, f"Cover image request failed: {exc}")

    temporary = storage.book_dir(book.id) / f".cover-{secrets.token_hex(4)}.part"
    last_error = "unknown error"
    try:
        for attempt in range(1, settings.download_retries + 1):
            try:
                fetched = await fetcher.download_to_file(
                    request.url, temporary, max_bytes=settings.max_image_bytes
                )
                image_format, _mime, width, height = validate_image_file(temporary)
                extension = EXT_BY_FORMAT[image_format]
                final = storage.book_dir(book.id) / f"cover.{extension}"
                os.replace(temporary, final)
                storage.remove_cover_files(book.id, keep=extension)
                extra = book.extra
                extra["cover_local"] = final.name
                extra["cover_width"] = width
                extra["cover_height"] = height
                extra["cover_request_url"] = request.url
                extra.pop("cover_error", None)
                extra["warnings"] = [
                    warning
                    for warning in extra.get("warnings", [])
                    if not str(warning).startswith(
                        ("Cover image", "No cover page", "The selected cover page")
                    )
                ]
                book.extra_json = json.dumps(extra, ensure_ascii=False)
                logger.info(
                    "Cached cover for book %s (%s, %sx%s, %s bytes)",
                    book.id,
                    request.url.split("?")[0],
                    width,
                    height,
                    fetched.size,
                )
                return True, None
            except FetchError as exc:
                last_error = exc.message
                if not exc.retryable or attempt >= settings.download_retries:
                    break
            except (DownloadValidationError, OSError) as exc:
                last_error = str(exc)
                break
            await asyncio.sleep(min(settings.download_retry_backoff * (2 ** (attempt - 1)), 5.0))
        return _cover_failure(book, f"Cover image could not be cached: {last_error}")
    finally:
        temporary.unlink(missing_ok=True)


def _cover_failure(book, message: str) -> tuple[bool, str]:
    extra = book.extra
    extra["cover_error"] = message
    warnings = [str(item) for item in extra.get("warnings", [])]
    if message not in warnings:
        warnings.append(message)
    extra["warnings"] = warnings
    book.extra_json = json.dumps(extra, ensure_ascii=False)
    logger.warning("Book %s: %s", book.id, message)
    return False, message
