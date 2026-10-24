from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import wait_until
from tests.helpers import FakeFetcher, attach_fake

MANIFEST_URL = "https://example.org/iiif/book2/manifest"


def import_book(client: TestClient) -> dict:
    preview = client.post("/api/import/preview", json={"manifest_url": MANIFEST_URL})
    assert preview.status_code == 200, preview.text
    token = preview.json()["preview_token"]
    response = client.post(
        "/api/books", json={"manifest_url": MANIFEST_URL, "preview_token": token}
    )
    assert response.status_code == 201, response.text
    return response.json()


def start_job(client: TestClient, book_id: str, quality: str | None = None) -> dict:
    response = client.post(
        f"/api/books/{book_id}/downloads",
        json={"quality": quality} if quality else None,
    )
    assert response.status_code == 200, response.text
    return response.json()


def get_job(client: TestClient, job_id: str) -> dict:
    response = client.get(f"/api/downloads/{job_id}")
    assert response.status_code == 200, response.text
    return response.json()


def wait_for_job(client: TestClient, job_id: str, states: set[str], timeout: float = 20.0) -> dict:
    def check():
        job = get_job(client, job_id)
        return job if job["state"] in states else None

    return wait_until(check, timeout=timeout)


def test_full_download_offline_and_local_reading(client: TestClient) -> None:
    book = import_book(client)
    job = start_job(client, book["id"])
    assert job["state"] == "queued"
    finished = wait_for_job(client, job["id"], {"completed", "failed"})
    assert finished["state"] == "completed", finished
    assert finished["quality"] == "research"
    assert finished["completed_pages"] == 3
    assert finished["failed_pages"] == 0
    assert finished["bytes_downloaded"] > 0

    detail = client.get(f"/api/books/{book['id']}").json()
    assert detail["download_state"] == "offline"
    assert detail["completed_pages"] == 3
    assert detail["downloaded_bytes"] > 0
    assert detail["local_cover_url"] == f"/api/books/{book['id']}/cover"

    canvases = client.get(f"/api/books/{book['id']}/canvases").json()
    assert canvases["download_state"] == "offline"
    assert all(item["local_available"] for item in canvases["items"])
    assert all(item["page_status"] == "complete" for item in canvases["items"])

    page = client.get(f"/api/books/{book['id']}/pages/1")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("image/")
    cover = client.get(f"/api/books/{book['id']}/cover")
    assert cover.status_code == 200

    book_dir = Path(client.app.state.settings.books_dir, book["id"])
    archive_size = (book_dir / "book.cbz").stat().st_size
    assert detail["archive_bytes"] == archive_size
    assert detail["local_storage_bytes"] == archive_size
    manifest = json.loads((book_dir / "download-manifest.json").read_text(encoding="utf-8"))
    assert manifest["book_state"] == "offline"
    assert len(manifest["pages"]) == 3
    assert all(page["status"] == "complete" for page in manifest["pages"])
    assert all(page["local_path"] for page in manifest["pages"])
    assert all(page["sha256"] for page in manifest["pages"])
    assert manifest["archive"] == "book.cbz"
    assert (book_dir / "book.cbz").is_file()
    assert not list((book_dir / "pages").glob("*.part"))
    assert not list((book_dir / "pages").glob("*.jpg"))

    storage = client.get("/api/system/storage").json()
    assert storage["book_count"] == 1
    assert storage["books_bytes"] > 0


def test_download_quality_is_recorded(client: TestClient) -> None:
    book = import_book(client)
    job = start_job(client, book["id"], quality="reading")
    assert job["quality"] == "reading"
    finished = wait_for_job(client, job["id"], {"completed", "failed"})
    assert finished["state"] == "completed", finished
    assert finished["quality"] == "reading"

    book_dir = Path(client.app.state.settings.books_dir, book["id"])
    manifest = json.loads((book_dir / "download-manifest.json").read_text(encoding="utf-8"))
    assert manifest["quality"] == "reading"

    invalid = client.post(
        f"/api/books/{book['id']}/downloads",
        json={"quality": "poster"},
    )
    assert invalid.status_code == 422


def test_download_failure_partial_state_and_retry(client: TestClient) -> None:
    fake: FakeFetcher = client.app.state.fetcher
    book = import_book(client)
    fake.fail_urls.add("https://images.example.org/hours/page3.png")

    job = start_job(client, book["id"])
    failed = wait_for_job(client, job["id"], {"completed", "failed"})
    assert failed["state"] == "failed"
    assert failed["completed_pages"] == 2
    assert failed["failed_pages"] == 1
    assert "failed" in (failed["error"] or "").lower()

    detail = client.get(f"/api/books/{book['id']}").json()
    assert detail["download_state"] == "partial"
    canvases = client.get(f"/api/books/{book['id']}/canvases").json()["items"]
    assert canvases[2]["page_status"] == "failed"
    assert canvases[2]["local_available"] is False
    assert client.get(f"/api/books/{book['id']}/pages/3").status_code == 404

    fake.fail_urls.clear()
    retry = client.post(f"/api/downloads/{job['id']}/retry")
    assert retry.status_code == 200, retry.text
    assert retry.json()["state"] == "queued"
    completed = wait_for_job(client, job["id"], {"completed", "failed"})
    assert completed["state"] == "completed"
    assert completed["completed_pages"] == 3
    assert client.get(f"/api/books/{book['id']}").json()["download_state"] == "offline"


def test_first_page_failure_does_not_use_a_later_page_as_cover(client: TestClient) -> None:
    fake: FakeFetcher = client.app.state.fetcher
    book = import_book(client)
    fake.fail_urls.add("https://example.org/iiif/book2/canvas/1/full/2400,/0/default.jpg")
    job = start_job(client, book["id"])
    failed = wait_for_job(client, job["id"], {"completed", "failed"})
    assert failed["state"] == "failed"
    assert failed["completed_pages"] == 2

    detail = client.get(f"/api/books/{book['id']}").json()
    assert detail["download_state"] == "partial"
    assert detail["local_cover_url"] == f"/api/books/{book['id']}/cover"
    assert client.get(f"/api/books/{book['id']}/cover").status_code == 200
    # Other pages are still readable locally.
    assert client.get(f"/api/books/{book['id']}/pages/2").status_code == 200

    fake.fail_urls.clear()
    retry = client.post(f"/api/downloads/{job['id']}/retry")
    assert retry.status_code == 200
    wait_for_job(client, job["id"], {"completed", "failed"})
    detail = client.get(f"/api/books/{book['id']}").json()
    assert detail["local_cover_url"] == f"/api/books/{book['id']}/cover"
    assert client.get(f"/api/books/{book['id']}/cover").status_code == 200


def test_transient_failures_are_retried(client: TestClient) -> None:
    fake: FakeFetcher = client.app.state.fetcher
    book = import_book(client)
    fake.fail_counts = {
        "https://example.org/iiif/book2/canvas/1/full/2400,/0/default.jpg": 1,
        "https://example.org/iiif/book2/canvas/2/full/2400,/0/default.jpg": 1,
        "https://images.example.org/hours/page3.png": 1,
    }
    job = start_job(client, book["id"])
    finished = wait_for_job(client, job["id"], {"completed", "failed"})
    assert finished["state"] == "completed", finished
    assert finished["completed_pages"] == 3
    assert len(fake.download_calls) >= 6


def test_all_pages_failing_marks_error(client: TestClient) -> None:
    fake: FakeFetcher = client.app.state.fetcher
    book = import_book(client)
    fake.fail_all = True
    job = start_job(client, book["id"])
    failed = wait_for_job(client, job["id"], {"completed", "failed"})
    assert failed["state"] == "failed"
    assert failed["completed_pages"] == 0
    assert failed["failed_pages"] == 3
    assert client.get(f"/api/books/{book['id']}").json()["download_state"] == "error"


def test_pause_and_resume(client: TestClient) -> None:
    fake: FakeFetcher = client.app.state.fetcher
    book = import_book(client)
    fake.delay = 0.35
    job = start_job(client, book["id"])

    def check_downloading():
        current = get_job(client, job["id"])
        return current if current["state"] == "downloading" else None

    downloading = wait_until(check_downloading, timeout=10)
    assert downloading["state"] == "downloading"

    paused = client.post(f"/api/downloads/{job['id']}/pause")
    assert paused.status_code == 200, paused.text
    assert paused.json()["state"] == "paused"
    assert client.get(f"/api/books/{book['id']}").json()["download_state"] == "paused"

    resumed = client.post(f"/api/downloads/{job['id']}/resume")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["state"] == "queued"
    finished = wait_for_job(client, job["id"], {"completed", "failed"})
    assert finished["state"] == "completed", finished
    assert client.get(f"/api/books/{book['id']}").json()["download_state"] == "offline"


def test_cancel_keeps_completed_pages_and_allows_new_job(client: TestClient) -> None:
    fake: FakeFetcher = client.app.state.fetcher
    book = import_book(client)
    fake.delay = 0.3
    job = start_job(client, book["id"])
    wait_until(
        lambda: get_job(client, job["id"])["state"] == "downloading",
        timeout=10,
    )
    cancelled = client.post(f"/api/downloads/{job['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "cancelled"
    detail = client.get(f"/api/books/{book['id']}").json()
    assert detail["download_state"] in {"online", "partial"}
    assert detail["active_job"] is None

    fake.delay = 0
    new_job = start_job(client, book["id"])
    finished = wait_for_job(client, new_job["id"], {"completed", "failed"})
    assert finished["state"] == "completed", finished
    assert client.get(f"/api/books/{book['id']}").json()["download_state"] == "offline"


def test_duplicate_active_job_is_rejected(client: TestClient) -> None:
    fake: FakeFetcher = client.app.state.fetcher
    book = import_book(client)
    fake.delay = 0.3
    first = start_job(client, book["id"])
    second = client.post(f"/api/books/{book['id']}/downloads")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "download_already_active"
    client.post(f"/api/downloads/{first['id']}/cancel")


def test_delete_local_copy_keeps_book_record(client: TestClient) -> None:
    book = import_book(client)
    job = start_job(client, book["id"])
    wait_for_job(client, job["id"], {"completed", "failed"})
    book_dir = Path(client.app.state.settings.books_dir, book["id"])
    assert (book_dir / "book.cbz").is_file()
    assert not list((book_dir / "pages").glob("*.jpg"))

    response = client.delete(f"/api/books/{book['id']}/local-copy")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["id"] == book["id"]
    assert detail["download_state"] == "online"
    assert detail["completed_pages"] == 0
    assert detail["latest_job"] is None
    assert detail["archive_bytes"] == 0
    assert detail["local_storage_bytes"] == 0
    assert client.get(f"/api/books/{book['id']}").status_code == 200
    assert client.get(f"/api/books/{book['id']}/pages/1").status_code == 404
    assert not list((book_dir / "pages").glob("*.jpg"))
    assert not (book_dir / "book.cbz").exists()
    assert (book_dir / "manifest.json").exists()
    assert (book_dir / "cover.jpg").exists()
    assert not (book_dir / "download-manifest.json").exists()
    assert client.get("/api/downloads").json()["total"] == 0

    new_job = start_job(client, book["id"])
    finished = wait_for_job(client, new_job["id"], {"completed", "failed"})
    assert finished["state"] == "completed"
    assert client.get(f"/api/books/{book['id']}").json()["download_state"] == "offline"


def test_delete_local_copy_preserves_a_cached_cover(client: TestClient) -> None:
    book = import_book(client)
    job = start_job(client, book["id"])
    wait_for_job(client, job["id"], {"completed", "failed"})
    book_dir = Path(client.app.state.settings.books_dir, book["id"])
    for cover in book_dir.glob("cover.*"):
        cover.unlink()

    response = client.delete(f"/api/books/{book['id']}/local-copy")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["download_state"] == "online"
    assert detail["local_cover_url"] == f"/api/books/{book['id']}/cover"
    assert (book_dir / "cover.jpg").is_file()
    assert client.get(f"/api/books/{book['id']}/cover").status_code == 200


def test_interrupted_download_recovers_after_restart(
    settings: Settings, fake_fetcher: FakeFetcher
) -> None:
    app1 = create_app(settings)
    with TestClient(app1) as client1:
        attach_fake(app1, fake_fetcher)
        book = import_book(client1)
        job = start_job(client1, book["id"])
        wait_for_job(client1, job["id"], {"completed", "failed"})
        with app1.state.db.session() as session:
            from app.models import DownloadJob, PageResource

            db_job = session.get(DownloadJob, job["id"])
            db_job.state = "downloading"
            db_job.completed_at = None
            page = session.query(PageResource).first()
            page.status = "downloading"

    app2 = create_app(settings)
    with TestClient(app2) as client2:
        attach_fake(app2, fake_fetcher)
        recovered = get_job(client2, job["id"])
        assert recovered["state"] == "paused"
        assert "interrupted" in (recovered["error"] or "").lower()
        detail = client2.get(f"/api/books/{book['id']}").json()
        assert detail["download_state"] == "paused"

        resumed = client2.post(f"/api/downloads/{job['id']}/resume")
        assert resumed.status_code == 200, resumed.text
        finished = wait_for_job(client2, job["id"], {"completed", "failed"})
        assert finished["state"] == "completed", finished
        assert client2.get(f"/api/books/{book['id']}").json()["download_state"] == "offline"


def test_missing_or_corrupt_local_file_is_detected_on_restart(
    settings: Settings, fake_fetcher: FakeFetcher
) -> None:
    app1 = create_app(settings)
    with TestClient(app1) as client1:
        attach_fake(app1, fake_fetcher)
        book = import_book(client1)
        job = start_job(client1, book["id"])
        wait_for_job(client1, job["id"], {"completed", "failed"})
        archive = Path(settings.books_dir, book["id"], "book.cbz")
        assert archive.is_file()
        with zipfile.ZipFile(archive, "r") as source:
            entries = [(item.filename, source.read(item.filename)) for item in source.infolist()]
        assert len(entries) == 3
        temporary = archive.with_suffix(".tmp")
        with zipfile.ZipFile(temporary, "w") as target:
            for name, payload in entries:
                if name != entries[1][0]:
                    target.writestr(name, payload)
        temporary.replace(archive)

    app2 = create_app(settings)
    with TestClient(app2) as client2:
        attach_fake(app2, fake_fetcher)
        detail = client2.get(f"/api/books/{book['id']}").json()
        assert detail["download_state"] == "partial"
        assert detail["completed_pages"] == 2
        canvases = client2.get(f"/api/books/{book['id']}/canvases").json()["items"]
        missing = [item for item in canvases if not item["local_available"]]
        assert len(missing) == 1
        assert missing[0]["page_status"] == "failed"

        new_job = start_job(client2, book["id"])
        finished = wait_for_job(client2, new_job["id"], {"completed", "failed"})
        assert finished["state"] == "completed", finished
        assert client2.get(f"/api/books/{book['id']}").json()["download_state"] == "offline"


def test_delete_book_during_download_stops_and_cleans_files(client: TestClient) -> None:
    fake: FakeFetcher = client.app.state.fetcher
    book = import_book(client)
    fake.delay = 0.3
    job = start_job(client, book["id"])
    wait_until(lambda: get_job(client, job["id"])["state"] == "downloading", timeout=10)
    book_dir = Path(client.app.state.settings.books_dir, book["id"])
    assert book_dir.exists()

    response = client.delete(f"/api/books/{book['id']}")
    assert response.status_code == 204
    assert client.get(f"/api/books/{book['id']}").status_code == 404
    assert not book_dir.exists()
    assert client.get("/api/downloads").json()["total"] == 0


def test_download_validation_rejects_invalid_image(tmp_path: Path) -> None:
    from app.services.downloads import DownloadValidationError, validate_image_file

    not_an_image = tmp_path / "fake.jpg"
    not_an_image.write_bytes(b"this is definitely not a jpeg")
    with pytest.raises(DownloadValidationError):
        validate_image_file(not_an_image)
