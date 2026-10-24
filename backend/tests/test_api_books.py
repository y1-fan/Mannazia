from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.helpers import FakeFetcher, attach_fake

MANIFEST_URL = "https://example.org/iiif/book2/manifest"


def preview(client: TestClient, url: str = MANIFEST_URL) -> dict:
    response = client.post("/api/import/preview", json={"manifest_url": url})
    assert response.status_code == 200, response.text
    return response.json()


def import_book(client: TestClient, url: str = MANIFEST_URL, **overrides) -> dict:
    data = preview(client, url)
    payload = {
        "manifest_url": url,
        "preview_token": data["preview_token"],
        **overrides,
    }
    response = client.post("/api/books", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_preview_presentation_v3(client: TestClient) -> None:
    data = preview(client)
    assert data["api_version"] == "3"
    assert data["title"] == "The Book of Hours"
    assert data["creator"] == "Example Atelier"
    assert data["canvas_count"] == 3
    assert data["image_canvas_count"] == 3
    assert data["rights_uri"] == "https://example.org/rights/inc"
    assert data["required_statement"]["value"].startswith("Image courtesy")
    assert data["thumbnail_url"] == "https://example.org/iiif/book2/canvas/1/thumb.jpg"
    assert data["preview_token"]
    assert data["duplicate_of"] is None
    assert any("more than one image" in warning for warning in data["warnings"])


def test_preview_presentation_v2(client: TestClient) -> None:
    data = preview(client, "https://example.org/iiif/book1/manifest")
    assert data["api_version"] == "2"
    assert data["title"] == "The Parchment Codex"
    assert data["canvas_count"] == 3
    assert data["image_canvas_count"] == 2


def test_import_and_duplicate_detection(client: TestClient) -> None:
    book = import_book(client, title="My Hours")
    assert book["title"] == "My Hours"
    assert book["download_state"] == "online"
    assert book["total_canvases"] == 3
    assert book["total_pages"] == 3
    assert book["thumbnail_url"] == "https://example.org/iiif/book2/canvas/1/thumb.jpg"
    assert book["local_cover_url"] == f"/api/books/{book['id']}/cover"
    assert Path(client.app.state.settings.books_dir, book["id"], "cover.jpg").exists()
    assert any(
        "/full/1200,/0/default.jpg" in call for call in client.app.state.fetcher.download_calls
    )
    # Caching a cover is not a page download and must not change the book state.
    assert book["download_state"] == "online"
    assert book["completed_pages"] == 0
    assert Path(client.app.state.settings.books_dir, book["id"], "manifest.json").exists()
    assert Path(client.app.state.settings.books_dir, book["id"], "book.json").exists()

    again = client.post(
        "/api/books",
        json={"manifest_url": MANIFEST_URL, "title": "Duplicate"},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "duplicate_book"
    assert again.json()["error"]["details"]["book_id"] == book["id"]

    duplicate_preview = preview(client)
    assert duplicate_preview["duplicate_of"] == book["id"]
    assert duplicate_preview["preview_token"] is None

    listing = client.get("/api/books").json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == book["id"]


def test_import_uses_manifest_url_canonicalization(client: TestClient) -> None:
    book = import_book(client, MANIFEST_URL + "#page=1")
    assert book["manifest_url"] == MANIFEST_URL
    response = client.post("/api/import/preview", json={"manifest_url": MANIFEST_URL + "#other"})
    assert response.json()["duplicate_of"] == book["id"]


def test_import_caches_cover_but_import_survives_cover_failure(client: TestClient) -> None:
    fake: FakeFetcher = client.app.state.fetcher
    fake.fail_urls.add("https://example.org/iiif/book2/canvas/1/full/1200,/0/default.jpg")
    book = import_book(client, title="Coverless")
    assert book["download_state"] == "online"
    assert book["local_cover_url"] is None
    assert any("Cover image" in warning for warning in book["warnings"])
    assert not Path(client.app.state.settings.books_dir, book["id"], "cover.jpg").exists()
    assert client.get(f"/api/books/{book['id']}/cover").status_code == 404


def test_edit_metadata_and_tags(client: TestClient) -> None:
    book = import_book(client)
    response = client.patch(
        f"/api/books/{book['id']}",
        json={
            "title": "Edited Hours",
            "creator": "A. Scribe",
            "description": "A new description",
            "language": "Latin",
            "date": "1500",
            "rights": "Permission required",
            "rights_uri": "https://example.org/rights/edited",
            "tags": ["prayer", "prayer", "illuminated"],
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["title"] == "Edited Hours"
    assert updated["creator"] == "A. Scribe"
    assert updated["tags"] == ["prayer", "illuminated"]
    assert updated["rights"] == "Permission required"

    listing = client.get("/api/books", params={"query": "Edited"}).json()
    assert listing["total"] == 1
    listing = client.get("/api/books", params={"tag": "illuminated"}).json()
    assert listing["total"] == 1
    listing = client.get("/api/books", params={"query": "MS 7"}).json()
    assert listing["total"] == 1
    listing = client.get("/api/books", params={"query": "Example Library"}).json()
    assert listing["total"] == 1
    listing = client.get("/api/books", params={"query": "Latin"}).json()
    assert listing["total"] == 1


def test_list_filters_states_and_errors(client: TestClient) -> None:
    import_book(client)
    assert client.get("/api/books", params={"state": "online"}).json()["total"] == 1
    assert client.get("/api/books", params={"state": "offline"}).json()["total"] == 0
    bad = client.get("/api/books", params={"state": "nonsense"})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "invalid_state"


def test_reading_progress_persists_by_source_canvas(client: TestClient) -> None:
    book = import_book(client)
    canvases = client.get(f"/api/books/{book['id']}/canvases").json()["items"]
    assert len(canvases) == 3
    assert canvases[0]["source_id"] == "https://example.org/iiif/book2/canvas/1"

    response = client.put(
        f"/api/books/{book['id']}/progress",
        json={
            "source_canvas_id": "https://example.org/iiif/book2/canvas/2",
            "sequence_index": 0,
        },
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["sequence_index"] == 1
    assert saved["source_canvas_id"] == "https://example.org/iiif/book2/canvas/2"

    progress = client.get(f"/api/books/{book['id']}/progress").json()
    assert progress["sequence_index"] == 1
    assert progress["canvas_id"] == canvases[1]["id"]

    bad = client.put(
        f"/api/books/{book['id']}/progress",
        json={"sequence_index": 99},
    )
    assert bad.status_code == 400


def test_api_error_shapes(client: TestClient) -> None:
    missing = client.get("/api/books/doesnotexist")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "book_not_found"

    invalid = client.post("/api/import/preview", json={"manifest_url": ""})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert invalid.json()["error"]["details"]["errors"]

    unknown = client.get("/api/books", params={"limit": 999})
    assert unknown.status_code == 422

    traversal = client.get("/api/books/%2E%2E%2F%2E%2E%2Fetc/pages/1")
    assert traversal.status_code in {404, 422}


def test_book_survives_application_restart(settings: Settings, fake_fetcher: FakeFetcher) -> None:
    app1 = create_app(settings)
    with TestClient(app1) as client1:
        attach_fake(app1, fake_fetcher)
        book = import_book(client1)
        client1.put(f"/api/books/{book['id']}/progress", json={"sequence_index": 2})

    app2 = create_app(settings)
    with TestClient(app2) as client2:
        attach_fake(app2, fake_fetcher)
        listing = client2.get("/api/books").json()
        assert listing["total"] == 1
        assert listing["items"][0]["id"] == book["id"]
        progress = client2.get(f"/api/books/{book['id']}/progress").json()
        assert progress["sequence_index"] == 2


def test_startup_backfills_legacy_cover_records(
    settings: Settings, fake_fetcher: FakeFetcher
) -> None:
    app1 = create_app(settings)
    with TestClient(app1) as client1:
        attach_fake(app1, fake_fetcher)
        book = import_book(client1)
        with app1.state.db.session() as session:
            from app.models import Book

            model = session.get(Book, book["id"])
            extra = json.loads(model.extra_json)
            extra.pop("cover_sequence", None)
            model.extra_json = json.dumps(extra)
            model.thumbnail_url = "https://example.org/iiif/book2/thumb.jpg"

    app2 = create_app(settings)
    with TestClient(app2) as client2:
        attach_fake(app2, fake_fetcher)
        restored = client2.get(f"/api/books/{book['id']}").json()
        assert restored["thumbnail_url"] == "https://example.org/iiif/book2/canvas/1/thumb.jpg"
        with app2.state.db.session() as session:
            from app.models import Book

            model = session.get(Book, book["id"])
            extra = json.loads(model.extra_json)
            assert extra["cover_sequence"] == 1
            assert extra["source_thumbnail_url"] == "https://example.org/iiif/book2/thumb.jpg"


def test_page_routes_do_not_serve_remote_files(client: TestClient) -> None:
    book = import_book(client)
    response = client.get(f"/api/books/{book['id']}/pages/1")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "page_not_local"
    # The cover is cached separately at import, but pages are still remote.
    cover = client.get(f"/api/books/{book['id']}/cover")
    assert cover.status_code == 200
    assert cover.headers["content-type"].startswith("image/")


def test_delete_book_removes_record_and_files(client: TestClient) -> None:
    book = import_book(client)
    book_dir = Path(client.app.state.settings.books_dir, book["id"])
    assert book_dir.exists()
    response = client.delete(f"/api/books/{book['id']}")
    assert response.status_code == 204
    assert client.get(f"/api/books/{book['id']}").status_code == 404
    assert not book_dir.exists()
