from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urldefrag

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.iiif.models import NormalizedManifest, ParsedManifest
from app.iiif.normalize import ManifestParseError, parse_manifest
from app.models import Book, Canvas, PageResource
from app.services.covers import choose_cover, cover_url
from app.services.state import recompute_book_state
from app.services.storage import Storage
from app.time import utcnow


@dataclass
class PreviewEntry:
    expires_at: float
    manifest_url: str
    parsed: ParsedManifest


class PreviewCache:
    def __init__(self, ttl_seconds: int = 900, max_entries: int = 32) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: dict[str, PreviewEntry] = {}

    def _purge(self) -> None:
        now = time.monotonic()
        for token in [key for key, entry in self._entries.items() if entry.expires_at <= now]:
            self._entries.pop(token, None)
        while len(self._entries) >= self.max_entries:
            oldest = next(iter(self._entries), None)
            if oldest is None:
                break
            self._entries.pop(oldest, None)

    def put(self, manifest_url: str, parsed: ParsedManifest) -> str:
        self._purge()
        token = secrets.token_urlsafe(24)
        self._entries[token] = PreviewEntry(
            expires_at=time.monotonic() + self.ttl_seconds,
            manifest_url=manifest_url,
            parsed=parsed,
        )
        return token

    def get(self, token: str | None) -> PreviewEntry | None:
        if not token:
            return None
        entry = self._entries.get(token)
        if entry is None:
            return None
        if entry.expires_at <= time.monotonic():
            self._entries.pop(token, None)
            return None
        return entry

    def drop(self, token: str | None) -> None:
        if token:
            self._entries.pop(token, None)


def canonical_manifest_url(url: str) -> str:
    return urldefrag(url.strip())[0]


def parse_manifest_payload(data: Any, manifest_url: str) -> ParsedManifest:
    try:
        return parse_manifest(data, manifest_url)
    except ManifestParseError as exc:
        raise ManifestParseError(str(exc)) from exc


def find_duplicate(session: Session, manifest_url: str) -> Book | None:
    return session.scalar(
        select(Book).where(Book.manifest_url == canonical_manifest_url(manifest_url))
    )


def _clean_optional(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = value.replace("\x00", "").strip()
    if not value:
        return None
    return value[:limit]


def normalize_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    result: list[str] = []
    for tag in tags:
        cleaned = _clean_optional(tag, 40)
        if cleaned and cleaned not in result:
            result.append(cleaned)
        if len(result) >= 20:
            break
    return result


def create_book(
    session: Session,
    storage: Storage,
    *,
    manifest_url: str,
    parsed: ParsedManifest,
    title: str | None = None,
    creator: str | None = None,
    description: str | None = None,
    language: str | None = None,
    date_display: str | None = None,
    rights: str | None = None,
    rights_uri: str | None = None,
    tags: list[str] | None = None,
) -> Book:
    manifest_url = canonical_manifest_url(manifest_url)
    existing = find_duplicate(session, manifest_url)
    if existing is not None:
        raise DuplicateBookError(existing)

    normalized = parsed.normalized
    book_id = secrets.token_hex(16)
    selected_cover = choose_cover(normalized.canvases)
    selected_cover_url = cover_url(selected_cover) if selected_cover else normalized.thumbnail_url
    source_thumbnail_url = normalized.thumbnail_url
    book = Book(
        id=book_id,
        manifest_url=manifest_url,
        api_version=normalized.api_version,
        title=_clean_optional(title, 500)
        or _clean_optional(normalized.label, 500)
        or "Untitled book",
        creator=_clean_optional(creator, 500) or _clean_optional(normalized.creator, 500),
        description=_clean_optional(description, 20000)
        or _clean_optional(normalized.description, 20000),
        language=_clean_optional(language, 100) or _clean_optional(normalized.language, 100),
        date_display=_clean_optional(date_display, 200) or _clean_optional(normalized.date, 200),
        rights=_clean_optional(rights, 10000) or _clean_optional(normalized.rights, 10000),
        rights_uri=_clean_optional(rights_uri, 2000)
        or _clean_optional(normalized.rights_uri, 2000),
        thumbnail_url=selected_cover_url,
        total_canvases=len(normalized.canvases),
        tags=json.dumps(normalize_tags(tags), ensure_ascii=False),
        metadata_json=json.dumps(
            [entry.model_dump() for entry in normalized.metadata], ensure_ascii=False
        ),
        extra_json=json.dumps(
            {
                "summary": normalized.description,
                "required_statement": {
                    "label": normalized.required_statement_label,
                    "value": normalized.required_statement_value,
                },
                "homepage": normalized.homepage,
                "rendering": normalized.rendering,
                "see_also": normalized.see_also,
                "provider": normalized.provider,
                "structures": [node.model_dump() for node in normalized.structures],
                "warnings": normalized.warnings,
                "manifest_id": normalized.manifest_id,
                "image_canvas_count": normalized.image_canvas_count,
                "cover_sequence": selected_cover.index if selected_cover else None,
                "source_thumbnail_url": source_thumbnail_url,
            },
            ensure_ascii=False,
        ),
        imported_at=utcnow(),
        last_refresh_at=utcnow(),
    )
    session.add(book)

    for canvas_model in normalized.canvases:
        image = canvas_model.image
        canvas = Canvas(
            id=secrets.token_hex(16),
            book_id=book_id,
            source_id=canvas_model.source_id,
            sequence=canvas_model.index,
            label=canvas_model.label,
            width=canvas_model.width,
            height=canvas_model.height,
            image_url=image.id if image else None,
            thumbnail_url=canvas_model.thumbnail_url,
            image_service_id=image.service.id if image and image.service else None,
            image_service_json=(
                json.dumps(image.service.model_dump(), ensure_ascii=False)
                if image and image.service
                else None
            ),
            related_resources_json=json.dumps(
                [item.model_dump() for item in canvas_model.other_images], ensure_ascii=False
            ),
            annotations_json=json.dumps(canvas_model.annotations, ensure_ascii=False),
            unsupported=canvas_model.unsupported,
        )
        session.add(canvas)
        if image is not None:
            session.add(
                PageResource(
                    id=secrets.token_hex(16),
                    book_id=book_id,
                    canvas_id=canvas.id,
                    source_url=image.id,
                    status="pending",
                )
            )

    if not book.thumbnail_url:
        first_image = next((c.image for c in normalized.canvases if c.image), None)
        if first_image:
            book.thumbnail_url = cover_url(selected_cover) if selected_cover else None
            if not book.thumbnail_url:
                if first_image.service:
                    book.thumbnail_url = f"{first_image.service.id}/full/400,/0/default.jpg"
                else:
                    book.thumbnail_url = first_image.id

    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        duplicate = find_duplicate(session, manifest_url)
        if duplicate is not None:
            raise DuplicateBookError(duplicate) from exc
        raise

    storage.ensure_book_dir(book_id)
    storage.write_manifest_snapshot(book_id, parsed.raw)
    storage.write_book_snapshot(book_id, snapshot_book(book, normalized))
    session.flush()
    recompute_book_state(session, book, storage, verify_files=False)
    return book


class DuplicateBookError(Exception):
    def __init__(self, book: Book) -> None:
        super().__init__("This Manifest URL is already in the library.")
        self.book = book


def snapshot_book(book: Book, normalized: NormalizedManifest) -> dict[str, Any]:
    return {
        "id": book.id,
        "manifest_url": book.manifest_url,
        "api_version": book.api_version,
        "title": book.title,
        "creator": book.creator,
        "description": book.description,
        "language": book.language,
        "date": book.date_display,
        "rights": book.rights,
        "rights_uri": book.rights_uri,
        "thumbnail_url": book.thumbnail_url,
        "total_canvases": book.total_canvases,
        "imported_at": book.imported_at.isoformat(),
        "normalized": normalized.model_dump(mode="json"),
    }


def update_book_metadata(session: Session, book: Book, values: dict[str, Any]) -> Book:
    mapping = {
        "title": (500, True),
        "creator": (500, False),
        "description": (20000, False),
        "language": (100, False),
        "date": (200, False),
        "rights": (10000, False),
        "rights_uri": (2000, False),
    }
    for field, (limit, required) in mapping.items():
        if field not in values:
            continue
        value = _clean_optional(values[field], limit)
        if required and not value:
            continue
        setattr(book, "date_display" if field == "date" else field, value)
    if "tags" in values:
        book.tags = json.dumps(normalize_tags(values["tags"]), ensure_ascii=False)
    book.updated_at = utcnow()
    session.flush()
    return book
