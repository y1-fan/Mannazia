from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from app.iiif.fetcher import FetchedFile, FetchError


def image_bytes(
    fmt: str = "JPEG", size: tuple[int, int] = (80, 120), color: str = "#efe6d4"
) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


@dataclass
class FakeFetcher:
    manifests: dict[str, dict[str, Any]] = field(default_factory=dict)
    fail_counts: dict[str, int] = field(default_factory=dict)
    fail_urls: set[str] = field(default_factory=set)
    fail_all: bool = False
    delay: float = 0.0
    fetch_calls: list[str] = field(default_factory=list)
    download_calls: list[str] = field(default_factory=list)
    info_payload: dict[str, Any] = field(
        default_factory=lambda: {
            "profile": "level2",
            "width": 2400,
            "height": 3200,
            "formats": ["jpg", "png"],
            "qualities": ["default", "bitonal"],
        }
    )
    closed: bool = False

    async def fetch_json(self, url: str, **kwargs: Any) -> tuple[Any, str]:
        import asyncio

        self.fetch_calls.append(url)
        if self.delay:
            await asyncio.sleep(self.delay)
        if url in self.manifests:
            return self.manifests[url], url
        if url.endswith("/info.json"):
            return self.info_payload, url
        raise FetchError(
            f"Simulated missing remote resource: {url}",
            code="remote_http_error",
            retryable=False,
            status_code=404,
        )

    async def download_to_file(
        self, url: str, destination: Path, *, max_bytes: int | None = None
    ) -> FetchedFile:
        import asyncio

        self.download_calls.append(url)
        if self.delay:
            await asyncio.sleep(self.delay)
        if url in self.fail_urls or self.fail_all:
            raise FetchError(
                "Simulated permanent image failure.",
                code="remote_http_error",
                retryable=False,
                status_code=404,
            )
        remaining = self.fail_counts.get(url, 0)
        if remaining:
            self.fail_counts[url] = remaining - 1
            raise FetchError(
                "Simulated transient image failure.",
                code="remote_http_error",
                retryable=True,
                status_code=503,
            )
        payload = image_bytes("PNG" if url.lower().endswith(".png") else "JPEG")
        if max_bytes and len(payload) > max_bytes:
            raise FetchError("Too large", code="response_too_large")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return FetchedFile(
            path=destination,
            content_type="image/png" if url.lower().endswith(".png") else "image/jpeg",
            size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            final_url=url,
        )

    async def aclose(self) -> None:
        self.closed = True


def attach_fake(app: Any, fake: FakeFetcher) -> None:
    app.state.fetcher = fake
    app.state.download_manager.fetcher = fake
    app.state.image_resolver.fetcher = fake
    app.state.thumbnail_manager.fetcher = fake
