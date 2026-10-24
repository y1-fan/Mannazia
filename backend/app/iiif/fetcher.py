from __future__ import annotations

import hashlib
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import Settings
from app.iiif.urls import ResolvedTarget, URLGuard, URLGuardError, redact_url

REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class FetchError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "fetch_failed",
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


@dataclass
class FetchedFile:
    path: Path
    content_type: str
    size: int
    sha256: str
    final_url: str
    declared_size: int | None = None


def _content_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _is_retryable_status(status: int) -> bool:
    return status in {408, 425, 429} or 500 <= status <= 599


class Fetcher:
    """SSRF-conscious HTTP client with pinned DNS destinations and manual redirects."""

    def __init__(
        self,
        settings: Settings,
        *,
        guard: URLGuard | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.guard = guard or URLGuard(settings)
        timeout = httpx.Timeout(
            settings.http_timeout,
            connect=settings.http_connect_timeout,
            read=settings.http_timeout,
            write=settings.http_timeout,
            pool=settings.http_connect_timeout,
        )
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers={"User-Agent": settings.user_agent, "Accept-Encoding": "identity"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @asynccontextmanager
    async def _open(
        self, url: str, *, accept: str, extra_headers: dict[str, str] | None = None
    ) -> AsyncIterator[tuple[httpx.Response, ResolvedTarget, str]]:
        current_url = url
        for hop in range(self.settings.max_redirects + 1):
            try:
                target = await self.guard.resolve(current_url)
            except URLGuardError as exc:
                raise FetchError(exc.message, code=exc.code) from exc

            headers = {
                "Accept": accept,
                "Host": target.host_header,
                "User-Agent": self.settings.user_agent,
                "Accept-Encoding": "identity",
            }
            if extra_headers:
                headers.update(extra_headers)
            request = self._client.build_request(
                "GET",
                target.connect_url,
                headers=headers,
                extensions={"sni_hostname": target.host},
            )
            try:
                response = await self._client.send(request, stream=True)
            except httpx.TimeoutException as exc:
                raise FetchError(
                    f"The request to {redact_url(current_url)} timed out.", retryable=True
                ) from exc
            except httpx.HTTPError as exc:
                raise FetchError(
                    f"Could not reach {redact_url(current_url)}: {type(exc).__name__}.",
                    retryable=True,
                ) from exc

            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise FetchError(
                        "The remote server returned a redirect without a Location header.",
                        code="invalid_redirect",
                    )
                if hop >= self.settings.max_redirects:
                    raise FetchError(
                        "The remote server redirected too many times.",
                        code="too_many_redirects",
                    )
                next_url = urljoin(current_url, location)
                old_scheme = urlsplit(current_url).scheme.lower()
                new_scheme = urlsplit(next_url).scheme.lower()
                if old_scheme == "https" and new_scheme == "http":
                    raise FetchError(
                        "A redirect attempted to downgrade a secure HTTPS connection to HTTP.",
                        code="insecure_redirect",
                    )
                current_url = next_url
                continue

            if response.status_code >= 400:
                await response.aclose()
                raise FetchError(
                    f"The remote server returned HTTP {response.status_code} for "
                    f"{redact_url(current_url)}.",
                    code="remote_http_error",
                    retryable=_is_retryable_status(response.status_code),
                    status_code=response.status_code,
                )
            if not 200 <= response.status_code < 300:
                await response.aclose()
                raise FetchError(
                    f"The remote server returned an unexpected HTTP {response.status_code}.",
                    code="remote_http_error",
                    status_code=response.status_code,
                )

            try:
                yield response, target, current_url
            finally:
                await response.aclose()
            return

    async def _read_limited(self, response: httpx.Response, max_bytes: int) -> bytes:
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise FetchError(
                "The remote response is larger than the configured limit.",
                code="response_too_large",
            )
        chunks: list[bytes] = []
        total = 0
        try:
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise FetchError(
                        "The remote response is larger than the configured limit.",
                        code="response_too_large",
                    )
                chunks.append(chunk)
        except httpx.TimeoutException as exc:
            raise FetchError(
                "The remote response timed out while downloading.", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise FetchError(
                f"The remote response was interrupted ({type(exc).__name__}).", retryable=True
            ) from exc
        return b"".join(chunks)

    async def fetch_json(
        self,
        url: str,
        *,
        max_bytes: int | None = None,
        accept: str = "application/json, application/ld+json",
    ) -> tuple[Any, str]:
        limit = max_bytes or self.settings.max_manifest_bytes
        async with self._open(url, accept=accept) as (response, _target, final_url):
            body = await self._read_limited(response, limit)
        try:
            data = json.loads(body.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise FetchError(
                "The remote response was not valid JSON. It may not be an IIIF Manifest.",
                code="invalid_json",
            ) from exc
        return data, final_url

    async def fetch_bytes(
        self,
        url: str,
        *,
        max_bytes: int,
        accept: str = "*/*",
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[bytes, str, str]:
        async with self._open(url, accept=accept, extra_headers=extra_headers) as (
            response,
            _target,
            final_url,
        ):
            content_type = _content_type(response)
            body = await self._read_limited(response, max_bytes)
        return body, content_type, final_url

    async def download_to_file(
        self, url: str, destination: Path, *, max_bytes: int | None = None
    ) -> FetchedFile:
        limit = max_bytes or self.settings.max_image_bytes
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        total = 0
        declared: int | None = None
        content_type = ""
        final_url = url
        try:
            async with self._open(url, accept="image/*") as (response, _target, resolved_url):
                final_url = resolved_url
                content_type = _content_type(response)
                if not (
                    content_type.startswith("image/")
                    or content_type in {"application/octet-stream", "binary/octet-stream"}
                ):
                    raise FetchError(
                        "The downloaded resource is not an image "
                        f"(content type: {content_type or 'missing'}).",
                        code="invalid_content_type",
                    )
                declared_header = response.headers.get("content-length")
                if declared_header and declared_header.isdigit():
                    declared = int(declared_header)
                    if declared > limit:
                        raise FetchError(
                            "The image is larger than the configured download limit.",
                            code="response_too_large",
                        )
                with destination.open("wb") as handle:
                    try:
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > limit:
                                raise FetchError(
                                    "The image is larger than the configured download limit.",
                                    code="response_too_large",
                                )
                            digest.update(chunk)
                            handle.write(chunk)
                    except httpx.TimeoutException as exc:
                        raise FetchError("The image download timed out.", retryable=True) from exc
                    except httpx.HTTPError as exc:
                        raise FetchError(
                            f"The image download was interrupted ({type(exc).__name__}).",
                            retryable=True,
                        ) from exc
                    handle.flush()
                    os.fsync(handle.fileno())
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        if total == 0:
            destination.unlink(missing_ok=True)
            raise FetchError("The remote image was empty.", code="empty_image", retryable=True)
        return FetchedFile(
            path=destination,
            content_type=content_type,
            size=total,
            sha256=digest.hexdigest(),
            final_url=final_url,
            declared_size=declared,
        )


async def fetch_json(url: str, settings: Settings) -> tuple[Any, str]:
    fetcher = Fetcher(settings)
    try:
        return await fetcher.fetch_json(url)
    finally:
        await fetcher.aclose()
