from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings

BOOK_ID_RE = re.compile(r"^[a-f0-9]{32}$")

MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "TIFF": "image/tiff",
}
EXT_BY_FORMAT = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
    "GIF": "gif",
    "TIFF": "tif",
}
EXT_BY_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/tiff": "tif",
}

COVER_EXTENSIONS = ("jpg", "png", "webp", "gif")
THUMBNAIL_EXTENSIONS = ("jpg", "jpeg", "png", "webp", "gif")
MIME_BY_EXTENSION = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


class StorageError(Exception):
    pass


@dataclass
class StorageUsage:
    books_bytes: int
    data_bytes: int
    config_bytes: int
    database_bytes: int
    book_count: int
    book_file_count: int
    free_bytes: int
    total_bytes: int

    def as_dict(self) -> dict[str, int]:
        return {
            "books_bytes": self.books_bytes,
            "data_bytes": self.data_bytes,
            "config_bytes": self.config_bytes,
            "database_bytes": self.database_bytes,
            "book_count": self.book_count,
            "book_file_count": self.book_file_count,
            "free_bytes": self.free_bytes,
            "total_bytes": self.total_bytes,
        }


def validate_book_id(book_id: str) -> str:
    if not BOOK_ID_RE.fullmatch(book_id or ""):
        raise StorageError("Invalid book identifier")
    return book_id


class Storage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.books_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def book_dir(self, book_id: str) -> Path:
        validate_book_id(book_id)
        path = (self.root / book_id).resolve()
        if not path.is_relative_to(self.root):
            raise StorageError("Invalid book storage path")
        return path

    def ensure_book_dir(self, book_id: str) -> Path:
        path = self.book_dir(book_id)
        path.mkdir(parents=True, exist_ok=True)
        (path / "pages").mkdir(exist_ok=True)
        return path

    def pages_dir(self, book_id: str) -> Path:
        path = self.book_dir(book_id) / "pages"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cover_path(self, book_id: str) -> Path | None:
        book_dir = self.book_dir(book_id)
        for extension in COVER_EXTENSIONS:
            candidate = book_dir / f"cover.{extension}"
            if candidate.is_file():
                return candidate
        return None

    def cover_media_type(self, path: Path) -> str:
        return MIME_BY_EXTENSION.get(path.suffix.lower().lstrip("."), "application/octet-stream")

    def remove_cover_files(self, book_id: str, *, keep: str | None = None) -> None:
        book_dir = self.book_dir(book_id)
        for extension in COVER_EXTENSIONS:
            if extension == keep:
                continue
            (book_dir / f"cover.{extension}").unlink(missing_ok=True)

    def thumbnails_dir(self, book_id: str) -> Path:
        path = self.book_dir(book_id) / "thumbs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def thumbnail_path(self, book_id: str, sequence: int) -> Path | None:
        thumbnails = self.book_dir(book_id) / "thumbs"
        for extension in THUMBNAIL_EXTENSIONS:
            candidate = thumbnails / f"{sequence:06d}.{extension}"
            if candidate.is_file():
                return candidate
        return None

    def remove_thumbnail_files(
        self, book_id: str, sequence: int, *, keep: str | None = None
    ) -> None:
        thumbnails = self.book_dir(book_id) / "thumbs"
        for extension in THUMBNAIL_EXTENSIONS:
            if extension == keep:
                continue
            (thumbnails / f"{sequence:06d}.{extension}").unlink(missing_ok=True)

    def store_thumbnail(self, book_id: str, sequence: int, source: Path, extension: str) -> Path:
        extension = re.sub(r"[^a-z0-9]", "", extension.lower()) or "jpg"
        thumbnails = self.thumbnails_dir(book_id)
        final = thumbnails / f"{sequence:06d}.{extension}"
        os.replace(source, final)
        self.remove_thumbnail_files(book_id, sequence, keep=extension)
        return final

    def thumbnail_media_type(self, path: Path) -> str:
        return MIME_BY_EXTENSION.get(path.suffix.lower().lstrip("."), "application/octet-stream")

    def archive_path(self, book_id: str) -> Path:
        return self.book_dir(book_id) / "book.cbz"

    def archive_bytes(self, book_id: str) -> int:
        archive = self.archive_path(book_id)
        try:
            return archive.stat().st_size if archive.is_file() else 0
        except OSError:
            return 0

    def archive_is_stored(self, book_id: str) -> bool:
        """Page images are already compressed; a stored CBZ avoids deflate expansion."""
        archive = self.archive_path(book_id)
        if not archive.is_file():
            return False
        try:
            with zipfile.ZipFile(archive, "r") as handle:
                return all(item.compress_type == zipfile.ZIP_STORED for item in handle.infolist())
        except (OSError, zipfile.BadZipFile):
            return False

    def local_copy_bytes(self, book_id: str) -> int:
        """Actual disk usage of downloaded page images, including CBZ packaging."""
        total = self.archive_bytes(book_id)
        pages = self.book_dir(book_id) / "pages"
        if not pages.is_dir():
            return total
        for item in pages.iterdir():
            if not item.is_file() or item.name.startswith("."):
                continue
            if item.name.endswith((".part", ".tmp")):
                continue
            try:
                total += item.stat().st_size
            except OSError:
                continue
        return total

    def create_page_archive(self, book_id: str, pages: Iterable[tuple[int, str]]) -> Path | None:
        """Package downloaded page images into a CBZ (ZIP) and return its path.

        Loose page files take precedence. When a previous archive exists, missing
        entries are read from it so retries can extend an existing CBZ. The new
        archive is written atomically and loose files are left for the caller.
        """
        book_dir = self.book_dir(book_id)
        final = self.archive_path(book_id)
        old_archive: zipfile.ZipFile | None = None
        if final.is_file():
            try:
                old_archive = zipfile.ZipFile(final, "r")
            except (OSError, zipfile.BadZipFile):
                old_archive = None

        temporary = book_dir / "book.cbz.tmp"
        expected: dict[str, int] = {}
        seen: set[str] = set()
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
                for sequence, relative in pages:
                    path = self.resolve_relative(book_id, relative)
                    name = path.name
                    if name in seen:
                        name = f"{sequence:06d}{path.suffix}"
                    if name in seen:
                        raise StorageError("Duplicate page file name while creating CBZ")
                    if path.is_file():
                        payload = path.read_bytes()
                    elif old_archive is not None:
                        try:
                            payload = old_archive.read(name)
                        except (KeyError, OSError, zipfile.BadZipFile) as exc:
                            raise StorageError(f"Page is missing from the CBZ: {name}") from exc
                    else:
                        continue
                    seen.add(name)
                    archive.writestr(name, payload)
                    expected[name] = len(payload)
            if old_archive is not None:
                old_archive.close()
                old_archive = None
            if not expected:
                return None
            with zipfile.ZipFile(temporary, "r") as archive:
                actual = {item.filename: item.file_size for item in archive.infolist()}
            if actual != expected:
                raise StorageError("CBZ verification failed after packaging")
            os.replace(temporary, final)
        finally:
            if old_archive is not None:
                old_archive.close()
            temporary.unlink(missing_ok=True)
        return final

    def verify_page_archive(
        self, book_id: str, expected: dict[str, int]
    ) -> tuple[bool, str | None]:
        archive = self.archive_path(book_id)
        if not archive.is_file():
            return False, "CBZ archive is missing"
        try:
            with zipfile.ZipFile(archive, "r") as handle:
                names = handle.namelist()
                if sorted(names) != sorted(expected):
                    return False, "CBZ entry list does not match the downloaded pages"
                for name, size in expected.items():
                    if handle.getinfo(name).file_size != size:
                        return False, "CBZ entry size does not match the page file"
                bad = handle.testzip()
                if bad is not None:
                    return False, f"CBZ entry failed its integrity check: {bad}"
        except (OSError, zipfile.BadZipFile) as exc:
            return False, f"CBZ archive is not readable: {exc}"
        return True, None

    def _archive_entry_name(self, relative: str) -> str:
        if not relative or Path(relative).is_absolute():
            raise StorageError("Invalid local path")
        name = Path(relative).name
        if not name or name in {".", ".."}:
            raise StorageError("Invalid local path")
        return name

    def page_in_archive(self, book_id: str, relative: str) -> bool:
        archive = self.archive_path(book_id)
        if not archive.is_file():
            return False
        name = self._archive_entry_name(relative)
        try:
            with zipfile.ZipFile(archive, "r") as handle:
                return name in handle.namelist()
        except (OSError, zipfile.BadZipFile):
            return False

    def page_exists(self, book_id: str, relative: str) -> bool:
        path = self.resolve_relative(book_id, relative)
        if path.is_file():
            return True
        return self.page_in_archive(book_id, relative)

    def page_size(self, book_id: str, relative: str) -> int:
        path = self.resolve_relative(book_id, relative)
        if path.is_file():
            return path.stat().st_size
        archive = self.archive_path(book_id)
        name = self._archive_entry_name(relative)
        try:
            with zipfile.ZipFile(archive, "r") as handle:
                return int(handle.getinfo(name).file_size)
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            raise StorageError("Page file is missing") from exc

    def page_sha256(self, book_id: str, relative: str) -> str:
        path = self.resolve_relative(book_id, relative)
        digest = hashlib.sha256()
        if path.is_file():
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        archive = self.archive_path(book_id)
        name = self._archive_entry_name(relative)
        try:
            with zipfile.ZipFile(archive, "r") as handle, handle.open(name) as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            raise StorageError("Page file is missing") from exc
        return digest.hexdigest()

    def read_page_bytes(self, book_id: str, relative: str) -> bytes:
        path = self.resolve_relative(book_id, relative)
        if path.is_file():
            return path.read_bytes()
        archive = self.archive_path(book_id)
        name = self._archive_entry_name(relative)
        try:
            with zipfile.ZipFile(archive, "r") as handle:
                return handle.read(name)
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            raise StorageError("Page file is missing") from exc

    def relative_page_path(self, sequence: int, extension: str) -> str:
        extension = re.sub(r"[^a-z0-9]", "", extension.lower()) or "img"
        return f"pages/{sequence:06d}.{extension}"

    def resolve_relative(self, book_id: str, relative: str) -> Path:
        if not relative or Path(relative).is_absolute():
            raise StorageError("Invalid local path")
        root = self.book_dir(book_id)
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            raise StorageError("Invalid local path")
        return candidate

    def all_book_dirs(self) -> list[Path]:
        if not self.root.exists():
            return []
        return [
            item
            for item in self.root.iterdir()
            if item.is_dir() and BOOK_ID_RE.fullmatch(item.name)
        ]

    def write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def write_manifest_snapshot(self, book_id: str, raw: dict[str, Any]) -> None:
        self.write_json(self.ensure_book_dir(book_id) / "manifest.json", raw)

    def write_book_snapshot(self, book_id: str, payload: dict[str, Any]) -> None:
        self.write_json(self.ensure_book_dir(book_id) / "book.json", payload)

    def write_download_manifest(self, book_id: str, payload: dict[str, Any]) -> None:
        payload = {
            "book_id": book_id,
            "generated_at": datetime.now(UTC).isoformat(),
            **payload,
        }
        self.write_json(self.ensure_book_dir(book_id) / "download-manifest.json", payload)

    def delete_local_copy(self, book_id: str) -> None:
        path = self.book_dir(book_id)
        if path.exists():
            shutil.rmtree(path)

    def delete_downloaded_pages(self, book_id: str) -> None:
        """Remove page images but keep the bibliographic manifest snapshots."""
        book_dir = self.book_dir(book_id)
        pages = book_dir / "pages"
        if pages.exists():
            shutil.rmtree(pages)
        pages.mkdir(parents=True, exist_ok=True)
        self.archive_path(book_id).unlink(missing_ok=True)
        (book_dir / "book.cbz.tmp").unlink(missing_ok=True)
        download_manifest = book_dir / "download-manifest.json"
        if download_manifest.exists():
            download_manifest.unlink(missing_ok=True)

    def cleanup_temporary_files(self) -> int:
        removed = 0
        for book_dir in self.all_book_dirs():
            pages = book_dir / "pages"
            for item in book_dir.iterdir():
                if item.is_file() and (
                    item.name.endswith(".tmp") or item.name.startswith(".cover-")
                ):
                    try:
                        item.unlink()
                        removed += 1
                    except OSError:
                        continue
            for directory in (pages, book_dir / "thumbs"):
                if not directory.exists():
                    continue
                for item in directory.iterdir():
                    if item.is_file() and (
                        item.name.endswith(".part")
                        or item.name.endswith(".tmp")
                        or item.name.startswith(".tmp-")
                    ):
                        try:
                            item.unlink()
                            removed += 1
                        except OSError:
                            continue
        return removed

    def book_size(self, book_id: str) -> int:
        path = self.book_dir(book_id)
        if not path.exists():
            return 0
        total = 0
        for root, _dirs, files in os.walk(path):
            for name in files:
                with contextlib.suppress(OSError):
                    total += (Path(root) / name).stat().st_size
        return total

    def usage(self) -> StorageUsage:
        books_bytes = 0
        book_count = 0
        book_file_count = 0
        for book_dir in self.all_book_dirs():
            book_count += 1
            for root, _dirs, files in os.walk(book_dir):
                for name in files:
                    try:
                        books_bytes += (Path(root) / name).stat().st_size
                        book_file_count += 1
                    except OSError:
                        pass
        data_bytes = _directory_size(self.settings.data_dir)
        config_bytes = _directory_size(self.settings.config_dir)
        database_bytes = 0
        with contextlib.suppress(OSError):
            database_bytes = self.settings.database_path.stat().st_size
        try:
            disk = shutil.disk_usage(self.root)
            free, total = disk.free, disk.total
        except OSError:
            free, total = 0, 0
        return StorageUsage(
            books_bytes=books_bytes,
            data_bytes=data_bytes,
            config_bytes=config_bytes,
            database_bytes=database_bytes,
            book_count=book_count,
            book_file_count=book_file_count,
            free_bytes=free,
            total_bytes=total,
        )


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            with contextlib.suppress(OSError):
                total += (Path(root) / name).stat().st_size
    return total
