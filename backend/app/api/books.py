from __future__ import annotations

import json
import logging
import secrets

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_book_or_404, get_db
from app.api.serializers import book_detail, book_summary, canvas_out, job_out
from app.config import Settings
from app.errors import AppError
from app.iiif.fetcher import FetchError
from app.iiif.normalize import ManifestParseError
from app.models import (
    ACTIVE_JOB_STATES,
    BOOK_DOWNLOAD_STATES,
    PAGE_COMPLETE,
    Book,
    Canvas,
    DownloadJob,
    PageResource,
    ReadingProgress,
)
from app.schemas import (
    BookDetailOut,
    BookListOut,
    BookUpdate,
    CanvasListOut,
    DownloadJobOut,
    DownloadStartIn,
    ImportRequest,
    ProgressIn,
    ProgressOut,
)
from app.services.covers import cache_local_cover
from app.services.library import (
    DuplicateBookError,
    canonical_manifest_url,
    create_book,
    find_duplicate,
    parse_manifest_payload,
    update_book_metadata,
)
from app.services.state import active_job, recompute_book_state
from app.services.storage import Storage, StorageError
from app.time import utcnow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/books", tags=["books"])


@router.post("", response_model=BookDetailOut, status_code=201, summary="Import a Manifest")
async def import_book(
    payload: ImportRequest, request: Request, session: Session = Depends(get_db)
) -> BookDetailOut:
    settings: Settings = request.app.state.settings
    storage: Storage = request.app.state.storage
    manifest_url = canonical_manifest_url(payload.manifest_url)
    duplicate = find_duplicate(session, manifest_url)
    if duplicate is not None:
        raise AppError(
            "This Manifest URL is already in the library.",
            status_code=409,
            code="duplicate_book",
            details={"book_id": duplicate.id, "title": duplicate.title},
        )

    parsed = None
    cache_entry = request.app.state.preview_cache.get(payload.preview_token)
    if cache_entry is not None and cache_entry.manifest_url == manifest_url:
        parsed = cache_entry.parsed
    if parsed is None:
        try:
            data, _ = await request.app.state.fetcher.fetch_json(
                manifest_url, max_bytes=settings.max_manifest_bytes
            )
            parsed = parse_manifest_payload(data, manifest_url)
        except FetchError as exc:
            from app.api.imports import _fetch_error

            raise _fetch_error(exc) from exc
        except ManifestParseError as exc:
            raise AppError(str(exc), status_code=422, code="manifest_invalid") from exc

    try:
        book = create_book(
            session,
            storage,
            manifest_url=manifest_url,
            parsed=parsed,
            title=payload.title,
            creator=payload.creator,
            description=payload.description,
            language=payload.language,
            date_display=payload.date,
            rights=payload.rights,
            rights_uri=payload.rights_uri,
            tags=payload.tags,
        )
    except DuplicateBookError as exc:
        raise AppError(
            "This Manifest URL is already in the library.",
            status_code=409,
            code="duplicate_book",
            details={"book_id": exc.book.id, "title": exc.book.title},
        ) from exc

    session.commit()
    from app.services.covers import cache_cover

    await cache_cover(
        session,
        book,
        storage,
        request.app.state.fetcher,
        request.app.state.image_resolver,
        settings,
    )
    session.commit()
    request.app.state.preview_cache.drop(payload.preview_token)
    request.app.state.thumbnail_manager.start(book.id)
    return book_detail(session, book, storage)


@router.get("", response_model=BookListOut, summary="List books")
def list_books(
    request: Request,
    session: Session = Depends(get_db),
    query: str | None = Query(default=None, max_length=200),
    state: str | None = Query(default=None, max_length=20),
    tag: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=60, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> BookListOut:
    storage: Storage = request.app.state.storage
    conditions = []
    if query:
        pattern = f"%{query.strip()}%"
        conditions.append(
            or_(
                Book.title.ilike(pattern),
                Book.creator.ilike(pattern),
                Book.description.ilike(pattern),
                Book.language.ilike(pattern),
                Book.date_display.ilike(pattern),
                Book.rights.ilike(pattern),
                Book.rights_uri.ilike(pattern),
                Book.tags.ilike(pattern),
                Book.metadata_json.ilike(pattern),
                func.json_extract(Book.extra_json, "$.provider").ilike(pattern),
                func.json_extract(Book.extra_json, "$.summary").ilike(pattern),
                func.json_extract(Book.extra_json, "$.required_statement").ilike(pattern),
            )
        )
    if state:
        if state not in BOOK_DOWNLOAD_STATES:
            raise AppError(
                f"Unknown download state '{state}'.", code="invalid_state", status_code=400
            )
        conditions.append(Book.download_state == state)
    if tag:
        conditions.append(Book.tags.ilike(f'%"{tag.strip()}"%'))

    total = int(session.scalar(select(func.count(Book.id)).where(*conditions)) or 0)
    books = session.scalars(
        select(Book)
        .where(*conditions)
        .order_by(Book.imported_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return BookListOut(
        items=[book_summary(session, book, storage) for book in books],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{book_id}", response_model=BookDetailOut, summary="Get a book")
def get_book(book_id: str, request: Request, session: Session = Depends(get_db)) -> BookDetailOut:
    book = get_book_or_404(session, book_id)
    return book_detail(session, book, request.app.state.storage)


@router.patch("/{book_id}", response_model=BookDetailOut, summary="Edit book metadata")
def patch_book(
    book_id: str,
    payload: BookUpdate,
    request: Request,
    session: Session = Depends(get_db),
) -> BookDetailOut:
    book = get_book_or_404(session, book_id)
    values = payload.model_dump(exclude_unset=True)
    update_book_metadata(session, book, values)
    session.commit()
    return book_detail(session, book, request.app.state.storage)


@router.delete("/{book_id}", status_code=204, summary="Delete a book and its local files")
async def delete_book(
    book_id: str, request: Request, session: Session = Depends(get_db)
) -> Response:
    book = get_book_or_404(session, book_id)
    manager = request.app.state.download_manager
    jobs = session.scalars(
        select(DownloadJob).where(
            DownloadJob.book_id == book.id, DownloadJob.state.in_(ACTIVE_JOB_STATES)
        )
    ).all()
    for job in jobs:
        await manager.stop_async(job.id, cancel=True)
    await request.app.state.thumbnail_manager.stop_async(book.id)
    storage: Storage = request.app.state.storage
    try:
        storage.delete_local_copy(book.id)
    except (OSError, StorageError) as exc:
        raise AppError(
            f"The local files could not be deleted: {exc}",
            status_code=500,
            code="storage_delete_failed",
        ) from exc
    session.delete(book)
    session.commit()
    return Response(status_code=204)


@router.get("/{book_id}/canvases", response_model=CanvasListOut, summary="List canvases")
def list_canvases(
    book_id: str, request: Request, session: Session = Depends(get_db)
) -> CanvasListOut:
    book = get_book_or_404(session, book_id)
    storage: Storage = request.app.state.storage
    rows = session.execute(
        select(Canvas, PageResource)
        .outerjoin(PageResource, PageResource.canvas_id == Canvas.id)
        .where(Canvas.book_id == book.id)
        .order_by(Canvas.sequence)
    ).all()
    items = [canvas_out(canvas, page, storage) for canvas, page in rows]
    return CanvasListOut(
        book_id=book.id,
        download_state=book.download_state,
        total=len(items),
        items=items,
    )


@router.get("/{book_id}/pages/{sequence}", summary="Serve a locally stored page image")
def get_local_page(
    book_id: str, sequence: int, request: Request, session: Session = Depends(get_db)
) -> Response:
    book = get_book_or_404(session, book_id)
    row = session.execute(
        select(Canvas, PageResource)
        .join(PageResource, PageResource.canvas_id == Canvas.id)
        .where(Canvas.book_id == book.id, Canvas.sequence == sequence)
    ).first()
    if row is None:
        raise AppError("Page not found.", status_code=404, code="page_not_found")
    page = row[1]
    if page.status != PAGE_COMPLETE or not page.local_path:
        raise AppError(
            "This page is not stored locally.",
            status_code=404,
            code="page_not_local",
            details={"book_id": book.id, "sequence": sequence},
        )
    storage: Storage = request.app.state.storage
    try:
        if not storage.page_exists(book.id, page.local_path):
            raise StorageError("Page file is missing")
        path = storage.resolve_relative(book.id, page.local_path)
    except StorageError as exc:
        raise AppError(
            "The local page file is missing.", status_code=404, code="page_file_missing"
        ) from exc
    headers = {"Cache-Control": "private, max-age=3600"}
    if page.checksum:
        headers["ETag"] = f'"{page.checksum}"'
    media_type = page.mime_type or "application/octet-stream"
    if path.is_file():
        return FileResponse(path, media_type=media_type, headers=headers)
    try:
        payload = storage.read_page_bytes(book.id, page.local_path)
    except (OSError, StorageError) as exc:
        raise AppError(
            "The local page file is missing.", status_code=404, code="page_file_missing"
        ) from exc
    return Response(content=payload, media_type=media_type, headers=headers)


@router.get("/{book_id}/thumbs/{sequence}", summary="Serve a cached page thumbnail")
def get_local_thumbnail(
    book_id: str, sequence: int, request: Request, session: Session = Depends(get_db)
) -> FileResponse:
    book = get_book_or_404(session, book_id)
    exists = session.scalar(
        select(Canvas.id).where(Canvas.book_id == book.id, Canvas.sequence == sequence)
    )
    if exists is None:
        raise AppError("Page not found.", status_code=404, code="page_not_found")
    storage: Storage = request.app.state.storage
    thumbnail = storage.thumbnail_path(book.id, sequence)
    if thumbnail is None:
        raise AppError(
            "This page thumbnail is not cached yet.",
            status_code=404,
            code="thumbnail_not_cached",
        )
    return FileResponse(
        thumbnail,
        media_type=storage.thumbnail_media_type(thumbnail),
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/{book_id}/cover", summary="Serve a locally available cover image")
def get_cover(book_id: str, request: Request, session: Session = Depends(get_db)) -> Response:
    book = get_book_or_404(session, book_id)
    storage: Storage = request.app.state.storage
    cached_cover = storage.cover_path(book.id)
    if cached_cover is not None:
        return FileResponse(
            cached_cover,
            media_type=storage.cover_media_type(cached_cover),
            headers={"Cache-Control": "private, max-age=3600"},
        )

    from app.services.covers import cover_sequence

    sequence = cover_sequence(book)
    query = (
        select(PageResource)
        .join(Canvas, Canvas.id == PageResource.canvas_id)
        .where(
            PageResource.book_id == book.id,
            PageResource.status == PAGE_COMPLETE,
        )
    )
    if sequence is not None:
        query = query.where(Canvas.sequence == sequence)
    else:
        query = query.order_by(Canvas.sequence)
    page = session.scalars(query.limit(1)).first()
    if page is None or not page.local_path:
        raise AppError(
            "No local cover image is available.", status_code=404, code="cover_not_found"
        )
    try:
        if not storage.page_exists(book.id, page.local_path):
            raise StorageError("Cover page file is missing")
        path = storage.resolve_relative(book.id, page.local_path)
    except StorageError as exc:
        raise AppError(
            "The local cover file is missing.", status_code=404, code="cover_not_found"
        ) from exc
    headers = {"Cache-Control": "private, max-age=3600"}
    media_type = page.mime_type or "application/octet-stream"
    if path.is_file():
        return FileResponse(path, media_type=media_type, headers=headers)
    try:
        payload = storage.read_page_bytes(book.id, page.local_path)
    except (OSError, StorageError) as exc:
        raise AppError(
            "The local cover file is missing.", status_code=404, code="cover_not_found"
        ) from exc
    return Response(content=payload, media_type=media_type, headers=headers)


@router.get("/{book_id}/progress", response_model=ProgressOut, summary="Get reading progress")
def get_progress(book_id: str, session: Session = Depends(get_db)) -> ProgressOut:
    book = get_book_or_404(session, book_id)
    progress = session.get(ReadingProgress, book.id)
    if progress is None:
        return ProgressOut(book_id=book.id, sequence_index=0)
    return ProgressOut(
        book_id=book.id,
        canvas_id=progress.canvas_id,
        source_canvas_id=progress.source_canvas_id,
        sequence_index=progress.sequence_index,
        updated_at=progress.updated_at,
    )


@router.put("/{book_id}/progress", response_model=ProgressOut, summary="Save reading progress")
def put_progress(
    book_id: str, payload: ProgressIn, session: Session = Depends(get_db)
) -> ProgressOut:
    book = get_book_or_404(session, book_id)
    canvas: Canvas | None = None
    if payload.canvas_id:
        canvas = session.get(Canvas, payload.canvas_id)
        if canvas is None or canvas.book_id != book.id:
            raise AppError(
                "Canvas not found in this book.", status_code=404, code="canvas_not_found"
            )
    elif payload.source_canvas_id:
        canvas = session.scalar(
            select(Canvas).where(
                Canvas.book_id == book.id, Canvas.source_id == payload.source_canvas_id
            )
        )
    sequence_index = payload.sequence_index
    if canvas is not None:
        sequence_index = canvas.sequence - 1
    elif book.total_canvases:
        if sequence_index >= book.total_canvases:
            raise AppError(
                "The reading position is outside this book.",
                status_code=400,
                code="invalid_sequence",
            )
    else:
        sequence_index = 0

    progress = session.get(ReadingProgress, book.id)
    if progress is None:
        progress = ReadingProgress(book_id=book.id)
        session.add(progress)
    progress.canvas_id = canvas.id if canvas else None
    progress.source_canvas_id = canvas.source_id if canvas else payload.source_canvas_id
    progress.sequence_index = sequence_index
    progress.updated_at = utcnow()
    session.commit()
    return ProgressOut(
        book_id=book.id,
        canvas_id=progress.canvas_id,
        source_canvas_id=progress.source_canvas_id,
        sequence_index=progress.sequence_index,
        updated_at=progress.updated_at,
    )


@router.post(
    "/{book_id}/downloads",
    response_model=DownloadJobOut,
    summary="Queue a local download",
)
async def start_download(
    book_id: str,
    request: Request,
    payload: DownloadStartIn | None = None,
    session: Session = Depends(get_db),
) -> DownloadJobOut:
    book = get_book_or_404(session, book_id)
    running = active_job(session, book.id)
    if running is not None:
        raise AppError(
            "A download for this book is already active.",
            status_code=409,
            code="download_already_active",
            details={"job_id": running.id, "state": running.state},
        )
    total_pages = int(
        session.scalar(select(func.count(PageResource.id)).where(PageResource.book_id == book.id))
        or 0
    )
    if total_pages == 0:
        raise AppError(
            "This book has no supported image pages to download.",
            status_code=400,
            code="no_downloadable_pages",
        )
    from app.services.state import book_stats

    stats = book_stats(session, book.id)
    job = DownloadJob(
        id=secrets.token_hex(16),
        book_id=book.id,
        state="queued",
        quality=payload.quality if payload is not None else "research",
        total_pages=stats.total_pages,
        completed_pages=stats.completed_pages,
        failed_pages=stats.failed_pages,
        bytes_downloaded=stats.bytes_downloaded,
        created_at=utcnow(),
    )
    session.add(job)
    book.download_state = "queued"
    session.commit()
    request.app.state.download_manager.start(job.id)
    return job_out(job, book.title)


@router.delete(
    "/{book_id}/local-copy",
    response_model=BookDetailOut,
    summary="Delete downloaded pages but keep the book record",
)
async def delete_local_copy(
    book_id: str, request: Request, session: Session = Depends(get_db)
) -> BookDetailOut:
    book = get_book_or_404(session, book_id)
    manager = request.app.state.download_manager
    jobs = session.scalars(
        select(DownloadJob).where(
            DownloadJob.book_id == book.id, DownloadJob.state.in_(ACTIVE_JOB_STATES)
        )
    ).all()
    for job in jobs:
        await manager.stop_async(job.id, cancel=True)
    storage: Storage = request.app.state.storage
    settings: Settings = request.app.state.settings
    # Preserve a high-quality cover before its source pages/archive disappear.
    cache_local_cover(session, book, storage, settings)
    try:
        storage.delete_downloaded_pages(book.id)
    except (OSError, StorageError) as exc:
        raise AppError(
            f"Local page files could not be deleted: {exc}",
            status_code=500,
            code="storage_delete_failed",
        ) from exc
    pages = session.scalars(select(PageResource).where(PageResource.book_id == book.id)).all()
    for page in pages:
        page.status = "pending"
        page.local_path = None
        page.request_url = None
        page.mime_type = None
        page.file_size = None
        page.checksum = None
        page.error = None
        page.attempts = 0
        page.updated_at = utcnow()
    for job in session.scalars(select(DownloadJob).where(DownloadJob.book_id == book.id)).all():
        session.delete(job)
    extra = book.extra
    warnings = [str(item) for item in extra.get("warnings", [])]
    quality_warnings = [
        warning
        for warning in warnings
        if not warning.startswith(
            ("Image processing failed for some pages", "Reading quality kept color")
        )
    ]
    if len(quality_warnings) != len(warnings):
        extra["warnings"] = quality_warnings
        book.extra_json = json.dumps(extra, ensure_ascii=False)
    book.download_state = "online"
    session.commit()
    recompute_book_state(session, book, storage, verify_files=False)
    session.commit()
    return book_detail(session, book, storage)
