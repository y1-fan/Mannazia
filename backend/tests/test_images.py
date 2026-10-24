from __future__ import annotations

from app.iiif.images import ImageServiceResolver, derive_image_request_url


def info(profile: str, width: int, **kwargs):
    data = {
        "id": "https://example.org/iiif/img",
        "type": "ImageService3",
        "profile": profile,
        "width": width,
        "height": width,
    }
    data.update(kwargs)
    return data


def test_level2_requests_capped_width() -> None:
    request = derive_image_request_url(
        "https://example.org/iiif/img",
        info("level2", 4000),
        canvas_width=4000,
        canvas_height=4000,
        max_width=2000,
    )
    assert request.url == "https://example.org/iiif/img/full/2000,/0/default.jpg"
    assert request.level == "level2"
    assert request.used_service is True


def test_native_size_smaller_than_cap_uses_max() -> None:
    request = derive_image_request_url(
        "https://example.org/iiif/img",
        info("level2", 1500),
        canvas_width=None,
        canvas_height=None,
        max_width=2000,
    )
    assert request.url.endswith("/full/max/0/default.jpg")


def test_level1_without_dimensions_uses_bounded_size() -> None:
    request = derive_image_request_url(
        "https://example.org/iiif/img",
        {"profile": "level1"},
        canvas_width=None,
        canvas_height=None,
        max_width=1600,
    )
    assert request.url.endswith("/full/!1600,1600/0/default.jpg")


def test_unlimited_width_requests_native_resolution() -> None:
    request = derive_image_request_url(
        "https://example.org/iiif/img",
        info("level2", 4000),
        canvas_width=4000,
        canvas_height=4000,
        max_width=0,
    )
    assert request.url == "https://example.org/iiif/img/full/4000,/0/default.jpg"


def test_level0_uses_max_and_documents_limitation() -> None:
    request = derive_image_request_url(
        "https://example.org/iiif/img",
        info("level0", 5000),
        canvas_width=5000,
        canvas_height=5000,
        max_width=1000,
    )
    assert request.url.endswith("/full/max/0/default.jpg")
    assert "level 0" in request.note


def test_v2_level0_uses_full_size_token() -> None:
    request = derive_image_request_url(
        "https://example.org/iiif/img",
        {
            "type": "ImageService2",
            "profile": "http://iiif.io/api/image/2/level0.json",
            "width": 5000,
        },
        canvas_width=5000,
        canvas_height=5000,
        max_width=0,
    )
    assert request.url.endswith("/full/full/0/default.jpg")


def test_unknown_profile_uses_conservative_max() -> None:
    request = derive_image_request_url(
        "https://example.org/iiif/img",
        {"width": 3000},
        canvas_width=3000,
        canvas_height=3000,
        max_width=1000,
    )
    assert request.url.endswith("/full/max/0/default.jpg")
    assert "did not advertise" in request.note


def test_format_and_quality_fallbacks() -> None:
    request = derive_image_request_url(
        "https://example.org/iiif/img",
        {
            "id": "https://example.org/iiif/img",
            "type": "ImageService3",
            "width": 3000,
            "height": 3000,
            "profile": [
                "http://iiif.io/api/image/2/level2.json",
                {
                    "formats": ["png"],
                    "qualities": ["native", "color"],
                },
            ],
        },
        canvas_width=3000,
        canvas_height=3000,
        max_width=1000,
        preferred_format="webp",
    )
    assert request.url.endswith("/full/1000,/0/native.png")


def test_v2_profile_level_detection() -> None:
    request = derive_image_request_url(
        "https://example.org/iiif/img",
        {
            "width": 3000,
            "height": 2000,
            "profile": ["http://iiif.io/api/image/2/level1.json", {"formats": ["jpg"]}],
        },
        canvas_width=3000,
        canvas_height=2000,
        max_width=1200,
    )
    assert request.url.endswith("/full/1200,/0/default.jpg")


class StubFetcher:
    def __init__(self, payload=None, fail=False):
        self.payload = payload
        self.fail = fail
        self.calls = []

    async def fetch_json(self, url, **kwargs):
        self.calls.append(url)
        if self.fail:
            from app.iiif.fetcher import FetchError

            raise FetchError("gone", code="remote_http_error", status_code=404)
        return self.payload, url


async def test_resolver_fetches_info_and_caches(tmp_path) -> None:
    from app.config import Settings

    settings = Settings(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        books_dir=tmp_path / "books",
        download_max_width=800,
    )
    fetcher = StubFetcher({"profile": "level2", "width": 2000, "height": 3000, "formats": ["jpg"]})
    resolver = ImageServiceResolver(settings, fetcher)  # type: ignore[arg-type]
    first = await resolver.request_for(
        image_url="https://example.org/iiif/img/full/max/0/default.jpg",
        service_id="https://example.org/iiif/img",
        service_json=None,
        canvas_width=2000,
        canvas_height=3000,
    )
    second = await resolver.request_for(
        image_url="https://example.org/iiif/img/full/max/0/default.jpg",
        service_id="https://example.org/iiif/img",
        service_json=None,
        canvas_width=2000,
        canvas_height=3000,
    )
    assert first.url == "https://example.org/iiif/img/full/800,/0/default.jpg"
    assert second.url == first.url
    assert fetcher.calls == ["https://example.org/iiif/img/info.json"]


async def test_resolver_falls_back_to_recorded_image_url(tmp_path) -> None:
    from app.config import Settings

    settings = Settings(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        books_dir=tmp_path / "books",
    )
    fetcher = StubFetcher(fail=True)
    resolver = ImageServiceResolver(settings, fetcher)  # type: ignore[arg-type]
    request = await resolver.request_for(
        image_url="https://example.org/original.jpg",
        service_id="https://example.org/iiif/img",
        service_json=None,
        canvas_width=100,
        canvas_height=100,
    )
    assert request.url == "https://example.org/original.jpg"
    assert request.used_service is False


async def test_resolver_uses_stored_service_profile_when_info_fails(tmp_path) -> None:
    from app.config import Settings

    settings = Settings(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        books_dir=tmp_path / "books",
        download_max_width=600,
    )
    fetcher = StubFetcher(fail=True)
    resolver = ImageServiceResolver(settings, fetcher)  # type: ignore[arg-type]
    request = await resolver.request_for(
        image_url=None,
        service_id="https://example.org/iiif/img",
        service_json={"profile": "level2", "width": 2000},
        canvas_width=2000,
        canvas_height=3000,
    )
    assert request.url == "https://example.org/iiif/img/full/600,/0/default.jpg"
