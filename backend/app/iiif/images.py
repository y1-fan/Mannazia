from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.iiif.fetcher import Fetcher, FetchError

logger = logging.getLogger(__name__)


@dataclass
class ImageRequest:
    url: str
    note: str = ""
    level: str | None = None
    used_service: bool = False


def _level_from_profile(profile: Any) -> str | None:
    import re

    for item in profile if isinstance(profile, list) else [profile]:
        if isinstance(item, str):
            match = re.search(r"level([0-2])(?:\.json)?$", item, re.IGNORECASE)
            if match:
                return f"level{match.group(1)}"
    return None


def _supported_formats(info: dict[str, Any]) -> list[str]:
    formats: list[str] = []
    for key in ("extraFormats", "formats"):
        value = info.get(key)
        if isinstance(value, list):
            formats.extend(str(item).lower() for item in value if isinstance(item, str))
    profile = info.get("profile")
    if isinstance(profile, list):
        for item in profile:
            if isinstance(item, dict) and isinstance(item.get("formats"), list):
                formats.extend(str(fmt).lower() for fmt in item["formats"])
    return list(dict.fromkeys(formats))


def _supported_qualities(info: dict[str, Any]) -> list[str]:
    qualities: list[str] = []
    for key in ("extraQualities", "qualities"):
        value = info.get(key)
        if isinstance(value, list):
            qualities.extend(str(item).lower() for item in value if isinstance(item, str))
    profile = info.get("profile")
    if isinstance(profile, list):
        for item in profile:
            if isinstance(item, dict) and isinstance(item.get("qualities"), list):
                qualities.extend(str(q).lower() for q in item["qualities"])
    return list(dict.fromkeys(qualities))


def _image_api_version(info: dict[str, Any]) -> int | None:
    """Return the advertised Image API major version, when it is unambiguous."""
    service_type = str(info.get("type") or "")
    if "ImageService3" in service_type:
        return 3
    if "ImageService2" in service_type:
        return 2
    profile = info.get("profile")
    values: list[str] = []
    if isinstance(profile, str):
        values.append(profile)
    elif isinstance(profile, list):
        values.extend(item for item in profile if isinstance(item, str))
    context = info.get("@context")
    if isinstance(context, str):
        values.append(context)
    for value in values:
        if "/image/3/" in value:
            return 3
        if "/image/2/" in value:
            return 2
    return None


def _full_size_token(info: dict[str, Any]) -> str:
    # Image API 3 calls the native size "max"; Image API 2 calls it "full".
    # Unknown profiles keep the historical "max" fallback.
    return "full" if _image_api_version(info) == 2 else "max"


def _dimensions(
    info: dict[str, Any] | None, width: int | None, height: int | None
) -> tuple[int | None, int | None]:
    if info:
        info_width = info.get("width")
        info_height = info.get("height")
        if isinstance(info_width, int) and info_width > 0:
            width = info_width
        if isinstance(info_height, int) and info_height > 0:
            height = info_height
    return width, height


def derive_image_request_url(
    service_id: str,
    info: dict[str, Any] | None,
    *,
    canvas_width: int | None,
    canvas_height: int | None,
    max_width: int,
    preferred_format: str = "jpg",
) -> ImageRequest:
    """Build a conservative IIIF Image API URL from advertised capabilities."""
    base = service_id.rstrip("/")
    info = info or {}
    profile = info.get("profile")
    level = _level_from_profile(profile)
    if not level:
        level = _level_from_profile(info.get("support"))
    formats = _supported_formats(info)
    qualities = _supported_qualities(info)
    native_width, _native_height = _dimensions(info, canvas_width, canvas_height)

    chosen_format = preferred_format.lower()
    if formats and chosen_format not in formats:
        chosen_format = "jpg" if "jpg" in formats else formats[0]
    chosen_quality = "default"
    if qualities and "default" not in qualities:
        chosen_quality = (
            "native"
            if "native" in qualities
            else ("color" if "color" in qualities else qualities[0])
        )

    note = ""
    full_size = _full_size_token(info)
    if level == "level0":
        size = full_size
        note = (
            "The image service advertises Image API level 0, which supports only maximum-size "
            "requests. This page will be downloaded at its native resolution."
        )
    elif level in {"level1", "level2"}:
        if native_width and max_width > 0:
            target = min(native_width, max_width)
            size = f"{target},"
            if target >= native_width:
                size = full_size
        elif native_width:
            # The configured width is unlimited: ask for the native width explicitly.
            size = f"{native_width},"
        elif max_width > 0:
            size = f"!{max_width},{max_width}"
        else:
            size = full_size
    else:
        # Unknown capability profile: the maximum-size token is the only size
        # guaranteed by every Image API level. We deliberately avoid inventing a
        # size expression.
        size = full_size
        note = (
            "The image service did not advertise a compliance level; a maximum-size request "
            "was used for compatibility."
        )
    url = f"{base}/full/{size}/0/{chosen_quality}.{chosen_format}"
    return ImageRequest(url=url, note=note, level=level, used_service=True)


class ImageServiceResolver:
    def __init__(self, settings: Settings, fetcher: Fetcher) -> None:
        self.settings = settings
        self.fetcher = fetcher
        self._cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
        self._success_ttl = 6 * 60 * 60
        self._failure_ttl = 5 * 60

    async def get_info(self, service_id: str) -> dict[str, Any] | None:
        now = time.monotonic()
        cached = self._cache.get(service_id)
        if cached and cached[0] > now:
            return cached[1]
        url = f"{service_id.rstrip('/')}/info.json"
        try:
            data, _ = await self.fetcher.fetch_json(
                url,
                max_bytes=self.settings.max_info_bytes,
                accept="application/json, application/ld+json, */*",
            )
        except FetchError as exc:
            logger.warning("Could not load image service info (%s): %s", exc.code, exc.message)
            self._cache[service_id] = (now + self._failure_ttl, None)
            return None
        if not isinstance(data, dict):
            self._cache[service_id] = (now + self._failure_ttl, None)
            return None
        self._cache[service_id] = (now + self._success_ttl, data)
        return data

    async def request_for(
        self,
        *,
        image_url: str | None,
        service_id: str | None,
        service_json: dict[str, Any] | None,
        canvas_width: int | None,
        canvas_height: int | None,
        max_width: int | None = None,
    ) -> ImageRequest:
        width_cap = self.settings.download_max_width if max_width is None else max_width
        if not service_id:
            if not image_url:
                raise ValueError("Canvas has neither an image URL nor an image service")
            return ImageRequest(url=image_url, note="Ordinary image URL; no Image API service.")
        info = await self.get_info(service_id)
        if info is not None:
            return derive_image_request_url(
                service_id,
                info,
                canvas_width=canvas_width,
                canvas_height=canvas_height,
                max_width=width_cap,
                preferred_format=self.settings.download_image_format,
            )
        if image_url:
            return ImageRequest(
                url=image_url,
                note=(
                    "The Image API info.json could not be read; the manifest's image URL was "
                    "used instead."
                ),
                used_service=False,
            )
        return derive_image_request_url(
            service_id,
            service_json or {},
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            max_width=width_cap,
            preferred_format=self.settings.download_image_format,
        )

    def clear(self) -> None:
        self._cache.clear()
