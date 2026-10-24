from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import wait_until


def test_unsupported_canvas_keeps_book_partial(client: TestClient) -> None:
    preview = client.post(
        "/api/import/preview",
        json={"manifest_url": "https://example.org/iiif/book1/manifest"},
    ).json()
    assert preview["canvas_count"] == 3
    assert preview["image_canvas_count"] == 2
    book = client.post(
        "/api/books",
        json={
            "manifest_url": "https://example.org/iiif/book1/manifest",
            "preview_token": preview["preview_token"],
        },
    ).json()
    assert book["unsupported_canvases"] == 1

    job = client.post(f"/api/books/{book['id']}/downloads").json()
    assert job["total_pages"] == 2

    def finished():
        current = client.get(f"/api/downloads/{job['id']}").json()
        return current if current["state"] in {"completed", "failed"} else None

    result = wait_until(finished, timeout=20)
    assert result["state"] == "completed", result
    assert result["completed_pages"] == 2

    detail = client.get(f"/api/books/{book['id']}").json()
    assert detail["download_state"] == "partial"
    assert detail["unsupported_canvases"] == 1
    canvases = client.get(f"/api/books/{book['id']}/canvases").json()["items"]
    assert canvases[2]["unsupported"] is True
    assert canvases[2]["page_status"] == "unsupported"


def test_openapi_and_health_are_available(client: TestClient) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    schema = client.get("/api/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    for path in [
        "/api/import/preview",
        "/api/books",
        "/api/books/{book_id}",
        "/api/books/{book_id}/canvases",
        "/api/books/{book_id}/progress",
        "/api/books/{book_id}/downloads",
        "/api/downloads",
        "/api/downloads/{job_id}/pause",
        "/api/downloads/{job_id}/resume",
        "/api/downloads/{job_id}/cancel",
        "/api/books/{book_id}/local-copy",
        "/api/system/storage",
    ]:
        assert path in paths, path
    assert client.get("/api/docs").status_code == 200
