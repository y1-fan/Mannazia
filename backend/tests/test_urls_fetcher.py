from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.iiif.fetcher import Fetcher, FetchError
from app.iiif.urls import URLGuard, URLGuardError, is_prohibited_ip, redact_url


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "config_dir": tmp_path / "config",
        "data_dir": tmp_path / "data",
        "books_dir": tmp_path / "books",
        "max_manifest_bytes": 1024,
        "max_image_bytes": 1024,
        "http_timeout": 5,
        "http_connect_timeout": 2,
        "http_proxy": None,
        "max_redirects": 3,
        "download_retry_backoff": 0.01,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.10",
        "172.16.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "fc00::1",
    ],
)
def test_prohibited_ip_ranges(address: str) -> None:
    assert is_prohibited_ip(address) is True


def test_public_ip_is_allowed() -> None:
    assert is_prohibited_ip("93.184.216.34") is False
    assert is_prohibited_ip("2606:2800:220:1:248:1893:25c8:1946") is False


async def test_guard_rejects_private_and_credentialed_urls(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    guard = URLGuard(settings, resolver=lambda host, port: asyncio.sleep(0, result=["10.1.2.3"]))
    with pytest.raises(URLGuardError, match="private") as exc:
        await guard.resolve("https://library.example/manifest.json")
    assert exc.value.code == "blocked_destination"

    public_guard = URLGuard(
        settings, resolver=lambda host, port: asyncio.sleep(0, result=["93.184.216.34"])
    )
    with pytest.raises(URLGuardError, match="credentials"):
        await public_guard.resolve("https://user:pass@library.example/manifest.json")
    with pytest.raises(URLGuardError, match="HTTP and HTTPS"):
        await public_guard.resolve("ftp://library.example/manifest.json")
    with pytest.raises(URLGuardError):
        await public_guard.resolve("javascript:alert(1)")
    with pytest.raises(URLGuardError, match=r"loopback|private"):
        await public_guard.resolve("http://127.0.0.1:8080/manifest.json")
    with pytest.raises(URLGuardError):
        await public_guard.resolve("http://[::1]/manifest.json")


async def test_guard_pins_public_ip_and_preserves_host(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    guard = URLGuard(
        settings, resolver=lambda host, port: asyncio.sleep(0, result=["93.184.216.34"])
    )
    target = await guard.resolve("https://library.example:8443/iiif/book/manifest.json?x=1")
    assert target.ip == "93.184.216.34"
    assert target.host == "library.example"
    assert target.port == 8443
    assert target.host_header == "library.example:8443"
    assert target.connect_url == "https://93.184.216.34:8443/iiif/book/manifest.json?x=1"


async def test_guard_rejects_mixed_dns_answers(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    guard = URLGuard(
        settings,
        resolver=lambda host, port: asyncio.sleep(0, result=["93.184.216.34", "10.0.0.1"]),
    )
    with pytest.raises(URLGuardError, match="private"):
        await guard.resolve("https://library.example/manifest.json")


async def test_guard_explicit_private_host_exception(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, allowed_private_hosts="iiif.lan")
    assert settings.allowed_private_host_set == frozenset({"iiif.lan"})
    guard = URLGuard(settings, resolver=lambda host, port: asyncio.sleep(0, result=["10.0.0.7"]))
    target = await guard.resolve("http://iiif.lan/manifest.json")
    assert target.allowed_private is True
    with pytest.raises(URLGuardError):
        await guard.resolve("http://other.internal/manifest.json")


async def test_guard_allow_private_networks_for_development(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, allow_private_networks=True)
    guard = URLGuard(settings, resolver=lambda host, port: asyncio.sleep(0, result=["127.0.0.1"]))
    target = await guard.resolve("http://localhost:9000/manifest.json")
    assert target.ip == "127.0.0.1"


def test_redact_url() -> None:
    assert redact_url("https://user:pass@example.org/a/b?token=secret#frag") == (
        "https://example.org/a/b"
    )


def json_transport(
    routes: dict[str, httpx.Response], seen: list[httpx.Request]
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        key = (
            str(request.url)
            .replace("https://93.184.216.34", "https://library.example")
            .replace("http://93.184.216.34", "http://library.example")
        )
        return routes[key]

    return httpx.MockTransport(handler)


def public_resolver(host: str, port: int):
    if host in {"internal.example", "localhost"}:
        return asyncio.sleep(0, result=["10.0.0.5"])
    return asyncio.sleep(0, result=["93.184.216.34"])


async def test_fetcher_follows_validated_redirects(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    routes = {
        "https://library.example/manifest.json": httpx.Response(
            302, headers={"location": "/real-manifest.json"}
        ),
        "https://library.example/real-manifest.json": httpx.Response(
            200, json={"type": "Manifest", "items": []}
        ),
    }
    settings = make_settings(tmp_path)
    fetcher = Fetcher(
        settings,
        guard=URLGuard(settings, resolver=public_resolver),
        transport=json_transport(routes, seen),
    )
    try:
        data, final = await fetcher.fetch_json("https://library.example/manifest.json")
    finally:
        await fetcher.aclose()
    assert data["type"] == "Manifest"
    assert final == "https://library.example/real-manifest.json"
    assert len(seen) == 2
    assert seen[0].headers["host"] == "library.example"
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].extensions.get("sni_hostname") == "library.example"


async def test_fetcher_blocks_redirect_to_private_destination(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    routes = {
        "https://library.example/manifest.json": httpx.Response(
            302, headers={"location": "https://internal.example/admin"}
        ),
    }
    settings = make_settings(tmp_path)
    fetcher = Fetcher(
        settings,
        guard=URLGuard(settings, resolver=public_resolver),
        transport=json_transport(routes, seen),
    )
    with pytest.raises(FetchError) as exc:
        await fetcher.fetch_json("https://library.example/manifest.json")
    await fetcher.aclose()
    assert exc.value.code == "blocked_destination"
    assert len(seen) == 1


async def test_fetcher_blocks_https_to_http_downgrade(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    routes = {
        "https://library.example/manifest.json": httpx.Response(
            302, headers={"location": "http://library.example/manifest.json"}
        ),
    }
    settings = make_settings(tmp_path)
    fetcher = Fetcher(
        settings,
        guard=URLGuard(settings, resolver=public_resolver),
        transport=json_transport(routes, seen),
    )
    with pytest.raises(FetchError) as exc:
        await fetcher.fetch_json("https://library.example/manifest.json")
    await fetcher.aclose()
    assert exc.value.code == "insecure_redirect"


async def test_fetcher_enforces_redirect_limit(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    routes = {
        "https://library.example/manifest.json": httpx.Response(
            302, headers={"location": "/again"}
        ),
        "https://library.example/again": httpx.Response(302, headers={"location": "/again"}),
    }
    settings = make_settings(tmp_path, max_redirects=2)
    fetcher = Fetcher(
        settings,
        guard=URLGuard(settings, resolver=public_resolver),
        transport=json_transport(routes, seen),
    )
    with pytest.raises(FetchError) as exc:
        await fetcher.fetch_json("https://library.example/manifest.json")
    await fetcher.aclose()
    assert exc.value.code == "too_many_redirects"


async def test_fetcher_enforces_manifest_size_limit(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    routes = {
        "https://library.example/manifest.json": httpx.Response(
            200, content=b"{" + b" " * 2000 + b"}"
        ),
    }
    settings = make_settings(tmp_path)
    fetcher = Fetcher(
        settings,
        guard=URLGuard(settings, resolver=public_resolver),
        transport=json_transport(routes, seen),
    )
    with pytest.raises(FetchError) as exc:
        await fetcher.fetch_json("https://library.example/manifest.json")
    await fetcher.aclose()
    assert exc.value.code == "response_too_large"


async def test_fetcher_downloads_image_to_temp_file(tmp_path: Path) -> None:
    from PIL import Image

    image_path = tmp_path / "source.png"
    Image.new("RGB", (20, 30), "white").save(image_path, format="PNG")
    payload = image_path.read_bytes()
    seen: list[httpx.Request] = []
    routes = {
        "https://library.example/page.png": httpx.Response(
            200, content=payload, headers={"content-type": "image/png"}
        )
    }
    settings = make_settings(tmp_path, max_image_bytes=100_000)
    fetcher = Fetcher(
        settings,
        guard=URLGuard(settings, resolver=public_resolver),
        transport=json_transport(routes, seen),
    )
    destination = tmp_path / "page.part"
    result = await fetcher.download_to_file("https://library.example/page.png", destination)
    await fetcher.aclose()
    assert result.size == len(payload)
    assert result.content_type == "image/png"
    assert len(result.sha256) == 64
    assert destination.exists()


async def test_fetcher_accepts_octet_stream_when_image_is_valid(tmp_path: Path) -> None:
    from PIL import Image

    image_path = tmp_path / "source.jpg"
    Image.new("RGB", (20, 30), "white").save(image_path, format="JPEG")
    payload = image_path.read_bytes()
    seen: list[httpx.Request] = []
    routes = {
        "https://library.example/page.jpg": httpx.Response(
            200, content=payload, headers={"content-type": "application/octet-stream"}
        )
    }
    settings = make_settings(tmp_path, max_image_bytes=100_000)
    fetcher = Fetcher(
        settings,
        guard=URLGuard(settings, resolver=public_resolver),
        transport=json_transport(routes, seen),
    )
    result = await fetcher.download_to_file(
        "https://library.example/page.jpg", tmp_path / "page.part"
    )
    await fetcher.aclose()
    assert result.content_type == "application/octet-stream"
    assert result.size == len(payload)


async def test_fetcher_rejects_non_image_content_type(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    routes = {
        "https://library.example/page.jpg": httpx.Response(
            200, content=b"<html>nope</html>", headers={"content-type": "text/html"}
        )
    }
    settings = make_settings(tmp_path)
    fetcher = Fetcher(
        settings,
        guard=URLGuard(settings, resolver=public_resolver),
        transport=json_transport(routes, seen),
    )
    destination = tmp_path / "page.part"
    with pytest.raises(FetchError) as exc:
        await fetcher.download_to_file("https://library.example/page.jpg", destination)
    await fetcher.aclose()
    assert exc.value.code == "invalid_content_type"
    assert not destination.exists()


async def test_fetcher_marks_5xx_retryable(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    routes = {"https://library.example/manifest.json": httpx.Response(503)}
    settings = make_settings(tmp_path)
    fetcher = Fetcher(
        settings,
        guard=URLGuard(settings, resolver=public_resolver),
        transport=json_transport(routes, seen),
    )
    with pytest.raises(FetchError) as exc:
        await fetcher.fetch_json("https://library.example/manifest.json")
    await fetcher.aclose()
    assert exc.value.retryable is True
    assert exc.value.status_code == 503


async def test_fetcher_marks_404_non_retryable(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    routes = {"https://library.example/manifest.json": httpx.Response(404)}
    settings = make_settings(tmp_path)
    fetcher = Fetcher(
        settings,
        guard=URLGuard(settings, resolver=public_resolver),
        transport=json_transport(routes, seen),
    )
    with pytest.raises(FetchError) as exc:
        await fetcher.fetch_json("https://library.example/manifest.json")
    await fetcher.aclose()
    assert exc.value.retryable is False
