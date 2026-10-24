from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.state import verify_local_files
from app.services.storage import Storage, StorageError, validate_book_id


def test_book_id_validation_rejects_traversal() -> None:
    for bad in ["../etc", "..", "abc/def", "..\\windows", "A" * 32, "0" * 31]:
        with pytest.raises(StorageError):
            validate_book_id(bad)
    assert validate_book_id("0123456789abcdef0123456789abcdef") == (
        "0123456789abcdef0123456789abcdef"
    )


def test_relative_paths_cannot_escape_book_directory(tmp_path: Path) -> None:
    from app.config import Settings

    settings = Settings(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        books_dir=tmp_path / "books",
    )
    storage = Storage(settings)
    book_id = "0123456789abcdef0123456789abcdef"
    storage.ensure_book_dir(book_id)
    for bad in ["../secret", "../../etc/passwd", "/etc/passwd", "pages/../../x"]:
        with pytest.raises(StorageError):
            storage.resolve_relative(book_id, bad)
    good = storage.resolve_relative(book_id, "pages/000001.jpg")
    assert good.is_relative_to(storage.book_dir(book_id))


def test_delete_downloaded_pages_keeps_manifest_snapshots(tmp_path: Path) -> None:
    from app.config import Settings

    settings = Settings(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        books_dir=tmp_path / "books",
    )
    storage = Storage(settings)
    book_id = "0123456789abcdef0123456789abcdef"
    book_dir = storage.ensure_book_dir(book_id)
    storage.write_manifest_snapshot(book_id, {"type": "Manifest"})
    storage.write_book_snapshot(book_id, {"title": "x"})
    storage.write_download_manifest(book_id, {"pages": []})
    (book_dir / "pages" / "000001.jpg").write_bytes(b"image")
    storage.delete_downloaded_pages(book_id)
    assert not (book_dir / "pages" / "000001.jpg").exists()
    assert (book_dir / "manifest.json").exists()
    assert (book_dir / "book.json").exists()
    assert not (book_dir / "download-manifest.json").exists()


def test_storage_usage_counts_files(tmp_path: Path) -> None:
    from app.config import Settings

    settings = Settings(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        books_dir=tmp_path / "books",
    )
    settings.ensure_directories()
    storage = Storage(settings)
    book_id = "0123456789abcdef0123456789abcdef"
    storage.ensure_book_dir(book_id)
    (storage.book_dir(book_id) / "manifest.json").write_text("{}", encoding="utf-8")
    usage = storage.usage()
    assert usage.book_count == 1
    assert usage.book_file_count >= 1
    assert usage.books_bytes >= 2
    assert usage.total_bytes > 0


def test_checksum_corruption_is_detected(client: TestClient) -> None:
    preview = client.post(
        "/api/import/preview",
        json={"manifest_url": "https://example.org/iiif/book2/manifest"},
    ).json()
    book = client.post(
        "/api/books",
        json={
            "manifest_url": "https://example.org/iiif/book2/manifest",
            "preview_token": preview["preview_token"],
        },
    ).json()
    job = client.post(f"/api/books/{book['id']}/downloads").json()
    import time

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        current = client.get(f"/api/downloads/{job['id']}").json()
        if current["state"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert current["state"] == "completed"

    storage: Storage = client.app.state.storage
    with client.app.state.db.session() as session:
        from app.models import Book, PageResource

        model = session.get(Book, book["id"])
        page = session.query(PageResource).first()
        archive = storage.archive_path(model.id)
        assert archive.is_file()
        with zipfile.ZipFile(archive, "r") as source:
            entries = [(item.filename, source.read(item.filename)) for item in source.infolist()]
        name, original = next(
            (item_name, payload)
            for item_name, payload in entries
            if Path(item_name).name == Path(page.local_path).name
        )
        tampered = bytearray(original)
        tampered[-1] = tampered[-1] ^ 0xFF
        temporary = archive.with_suffix(".tmp")
        with zipfile.ZipFile(temporary, "w") as target:
            for item_name, payload in entries:
                target.writestr(item_name, bytes(tampered) if item_name == name else payload)
        temporary.replace(archive)
        assert storage.page_size(model.id, page.local_path) == page.file_size

        ok, missing = verify_local_files(session, model, storage)
        assert ok is False
        assert missing == 1
        assert page.status == "failed"
        assert "checksum" in (page.error or "").lower()
