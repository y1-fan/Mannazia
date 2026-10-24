from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import wait_until
from tests.helpers import FakeFetcher, attach_fake

MANIFEST_URL = "https://example.org/iiif/book2/manifest"


def test_import_caches_page_thumbnails_and_serves_them(
    settings: Settings, fake_fetcher: FakeFetcher
) -> None:
    thumbnail_settings = settings.model_copy(update={"page_thumbnails_enabled": True})
    app = create_app(thumbnail_settings)
    with TestClient(app) as client:
        attach_fake(app, fake_fetcher)
        preview = client.post("/api/import/preview", json={"manifest_url": MANIFEST_URL})
        assert preview.status_code == 200, preview.text
        response = client.post(
            "/api/books",
            json={
                "manifest_url": MANIFEST_URL,
                "preview_token": preview.json()["preview_token"],
            },
        )
        assert response.status_code == 201, response.text
        book = response.json()

        def thumbnails_ready() -> bool:
            items = client.get(f"/api/books/{book['id']}/canvases").json()["items"]
            expected = [item for item in items if item["image_service_id"]]
            return bool(expected) and all(item["local_thumbnail_url"] for item in expected)

        wait_until(thumbnails_ready, timeout=10)
        items = client.get(f"/api/books/{book['id']}/canvases").json()["items"]
        local_items = [item for item in items if item["local_thumbnail_url"]]
        assert len(local_items) == 2
        for item in local_items:
            assert Path(
                thumbnail_settings.books_dir, book["id"], "thumbs", f"{item['index']:06d}.jpg"
            ).is_file()
            image = client.get(item["local_thumbnail_url"])
            assert image.status_code == 200
            assert image.headers["content-type"].startswith("image/")

        # A plain image URL without an Image API service has no IIIF thumbnail
        # request and keeps using the remote fallback.
        plain = next(item for item in items if item["index"] == 3)
        assert plain["local_thumbnail_url"] is None
        assert plain["thumbnail_url"] == "https://images.example.org/hours/page3.png"

        assert any(call.endswith("/thumb.jpg") for call in fake_fetcher.download_calls)
        assert any("/full/400,/0/default.jpg" in call for call in fake_fetcher.download_calls)
