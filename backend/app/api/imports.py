from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import Settings
from app.errors import AppError
from app.iiif.fetcher import FetchError
from app.iiif.normalize import ManifestParseError
from app.schemas import ImportPreviewOut, ImportRequest, MetadataEntryOut
from app.services.library import (
    canonical_manifest_url,
    find_duplicate,
)

router = APIRouter(prefix="/api/import", tags=["import"])


def _fetch_error(exc: FetchError) -> AppError:
    if exc.code in {
        "blocked_destination",
        "invalid_url",
        "scheme_not_allowed",
        "credentials_in_url",
        "resolution_failed",
        "url_too_long",
        "insecure_redirect",
        "invalid_redirect",
    }:
        return AppError(exc.message, status_code=400, code=exc.code)
    if exc.code in {"invalid_json", "manifest_invalid"}:
        return AppError(exc.message, status_code=422, code="manifest_invalid")
    return AppError(
        exc.message,
        status_code=502,
        code=exc.code,
        details={"remote_status": exc.status_code} if exc.status_code else None,
    )


def _duplicate_preview(book) -> ImportPreviewOut:
    extra = book.extra
    return ImportPreviewOut(
        manifest_url=book.manifest_url,
        api_version=book.api_version,
        title=book.title,
        creator=book.creator or "",
        description=book.description or "",
        language=book.language or "",
        date=book.date_display or "",
        rights=book.rights or "",
        rights_uri=book.rights_uri or "",
        required_statement=extra.get("required_statement") or {},
        thumbnail_url=book.thumbnail_url,
        canvas_count=book.total_canvases,
        image_canvas_count=int(extra.get("image_canvas_count") or 0),
        metadata=[MetadataEntryOut(**item) for item in book.metadata_entries],
        summary=book.description or "",
        provider=str(extra.get("provider") or ""),
        homepage=extra.get("homepage") or [],
        rendering=extra.get("rendering") or [],
        warnings=[],
        preview_token=None,
        duplicate_of=book.id,
        duplicate_title=book.title,
    )


@router.post("/preview", response_model=ImportPreviewOut, summary="Preview an IIIF Manifest")
async def preview_manifest(
    payload: ImportRequest, request: Request, session: Session = Depends(get_db)
) -> ImportPreviewOut:
    settings: Settings = request.app.state.settings
    manifest_url = canonical_manifest_url(payload.manifest_url)
    duplicate = find_duplicate(session, manifest_url)
    if duplicate is not None:
        return _duplicate_preview(duplicate)

    try:
        data, _final_url = await request.app.state.fetcher.fetch_json(
            manifest_url, max_bytes=settings.max_manifest_bytes
        )
        from app.services.library import parse_manifest_payload

        parsed = parse_manifest_payload(data, manifest_url)
    except FetchError as exc:
        raise _fetch_error(exc) from exc
    except ManifestParseError as exc:
        raise AppError(str(exc), status_code=422, code="manifest_invalid") from exc

    token = request.app.state.preview_cache.put(manifest_url, parsed)
    normalized = parsed.normalized
    from app.services.covers import choose_cover, cover_url

    selected_cover = choose_cover(normalized.canvases)
    preview_thumbnail = cover_url(selected_cover) if selected_cover else normalized.thumbnail_url
    return ImportPreviewOut(
        manifest_url=manifest_url,
        api_version=normalized.api_version,
        title=normalized.label,
        creator=normalized.creator,
        description=normalized.description,
        language=normalized.language,
        date=normalized.date,
        rights=normalized.rights,
        rights_uri=normalized.rights_uri,
        required_statement={
            "label": normalized.required_statement_label,
            "value": normalized.required_statement_value,
        },
        thumbnail_url=preview_thumbnail,
        canvas_count=len(normalized.canvases),
        image_canvas_count=normalized.image_canvas_count,
        metadata=[MetadataEntryOut(**entry.model_dump()) for entry in normalized.metadata],
        summary=normalized.description,
        provider=normalized.provider,
        homepage=normalized.homepage,
        rendering=normalized.rendering,
        warnings=normalized.warnings,
        preview_token=token,
    )


@router.post("/validate-url", summary="Validate a Manifest URL without fetching it")
async def validate_url(payload: ImportRequest, request: Request) -> dict[str, object]:
    try:
        target = await request.app.state.fetcher.guard.resolve(payload.manifest_url)
    except Exception as exc:  # URLGuardError
        from app.iiif.urls import URLGuardError

        if isinstance(exc, URLGuardError):
            raise AppError(exc.message, status_code=400, code=exc.code) from exc
        raise
    return {
        "allowed": True,
        "host": target.host,
        "port": target.port,
        "private_address_exception": target.allowed_private,
    }
