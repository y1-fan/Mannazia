from __future__ import annotations

import hashlib
import json
import sys
import time
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings  # noqa: E402
from app.iiif.fetcher import FetchedFile  # noqa: E402
from app.main import create_app  # noqa: E402


class DemoFetcher:
    def __init__(self, manifests: dict[str, dict], fail_urls: set[str] | None = None) -> None:
        self.manifests = manifests
        self.fail_urls = fail_urls or set()

    async def fetch_json(self, url: str, **kwargs):
        if url in self.manifests:
            return self.manifests[url], url
        if url.endswith("/info.json"):
            return {
                "profile": "level2",
                "width": 2400,
                "height": 3200,
                "formats": ["jpg", "png"],
                "qualities": ["default"],
            }, url
        from app.iiif.fetcher import FetchError

        raise FetchError("not found", code="remote_http_error", status_code=404)

    async def download_to_file(self, url: str, destination: Path, *, max_bytes=None) -> FetchedFile:
        from app.iiif.fetcher import FetchError

        if url in self.fail_urls:
            raise FetchError("Simulated damaged page", code="remote_http_error", status_code=404)
        digest = hashlib.sha1(url.encode()).hexdigest()
        palette = [
            ((246, 239, 226), (60, 50, 36)),
            ((234, 219, 194), (70, 54, 34)),
            ((226, 214, 196), (55, 45, 32)),
            ((242, 232, 213), (66, 52, 38)),
            ((229, 223, 206), (50, 48, 40)),
        ]
        background, ink = palette[int(digest[:2], 16) % len(palette)]
        image = Image.new("RGB", (760, 1080), background)
        draw = ImageDraw.Draw(image)
        draw.rectangle((28, 28, 732, 1052), outline=ink, width=2)
        draw.rectangle((44, 44, 716, 1036), outline=ink, width=1)
        font_big = ImageFont.load_default(size=64)
        font_small = ImageFont.load_default(size=24)
        number = int(digest[2:5], 16) % 30 + 1
        draw.text((90, 120), f"Folio {number}", fill=ink, font=font_big)
        draw.line((90, 230, 670, 230), fill=ink, width=2)
        for index in range(11):
            width = 560 - (int(digest[index * 2 : index * 2 + 2], 16) % 120)
            draw.line((90, 290 + index * 62, 90 + width, 290 + index * 62), fill=ink, width=1)
        draw.text(
            (90, 985),
            "Mannazia demonstration leaf",
            fill=ink,
            font=font_small,
        )
        buffer = BytesIO()
        fmt = "PNG" if url.lower().endswith(".png") else "JPEG"
        image.save(buffer, format=fmt, quality=88)
        payload = buffer.getvalue()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return FetchedFile(
            path=destination,
            content_type="image/png" if fmt == "PNG" else "image/jpeg",
            size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            final_url=url,
        )


def api_wait_job(client: TestClient, job_id: str) -> dict:
    for _ in range(300):
        job = client.get(f"/api/downloads/{job_id}").json()
        if job["state"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.05)
    raise RuntimeError("job did not finish")


def import_book(client: TestClient, url: str, **overrides) -> dict:
    preview = client.post("/api/import/preview", json={"manifest_url": url})
    preview.raise_for_status()
    payload = {
        "manifest_url": url,
        "preview_token": preview.json()["preview_token"],
        **overrides,
    }
    response = client.post("/api/books", json=payload)
    response.raise_for_status()
    return response.json()


def main() -> None:
    fixture_dir = BACKEND_DIR / "tests" / "fixtures"
    v2 = json.loads((fixture_dir / "manifest_v2.json").read_text(encoding="utf-8"))
    v3 = json.loads((fixture_dir / "manifest_v3.json").read_text(encoding="utf-8"))
    v2_copy = json.loads(json.dumps(v2))

    manifests = {
        "https://example.org/iiif/book2/manifest": v3,
        "https://example.org/iiif/book1/manifest": v2,
        "https://example.org/iiif/book1-variant/manifest": v2_copy,
    }
    fail_urls = {
        "https://example.org/iiif/book1/canvas/2/full/2000,/0/default.jpg",
    }
    fetcher = DemoFetcher(manifests, fail_urls)
    settings = Settings(
        config_dir=ROOT / "config",
        data_dir=ROOT / "data",
        books_dir=ROOT / "books",
        frontend_dir=ROOT / "frontend" / "dist",
        log_level="WARNING",
        download_concurrency=2,
        download_max_width=2000,
        download_retries=1,
        download_retry_backoff=0.01,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        app.state.fetcher = fetcher
        app.state.download_manager.fetcher = fetcher
        app.state.image_resolver.fetcher = fetcher

        hours = import_book(
            client,
            "https://example.org/iiif/book2/manifest",
            tags=["book of hours", "illuminated", "france"],
        )
        job = client.post(f"/api/books/{hours['id']}/downloads").json()
        api_wait_job(client, job["id"])
        client.put(
            f"/api/books/{hours['id']}/progress",
            json={"sequence_index": 1},
        )

        codex = import_book(
            client,
            "https://example.org/iiif/book1/manifest",
            tags=["manuscript", "latin"],
        )
        variant = import_book(
            client,
            "https://example.org/iiif/book1-variant/manifest",
            title="The Parchment Codex — study copy",
            tags=["study copy"],
        )
        job = client.post(f"/api/books/{variant['id']}/downloads").json()
        api_wait_job(client, job["id"])

        print("Seeded books:")
        for item in client.get("/api/books").json()["items"]:
            print(f"  {item['id']}  {item['download_state']:12} {item['title']}")
        print(f"  online reference: {codex['id']}")


if __name__ == "__main__":
    main()
