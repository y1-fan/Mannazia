from __future__ import annotations

from typing import Final, Literal

DownloadQuality = Literal["reading", "standard", "appreciation", "research"]

DEFAULT_DOWNLOAD_QUALITY: Final[DownloadQuality] = "research"

# Width caps used for the IIIF request; the downloader also applies a
# quality-specific long-edge target locally.
QUALITY_MAX_WIDTH: Final[dict[str, int]] = {
    "reading": 1200,
    "standard": 2000,
    "appreciation": 2800,
    "research": 0,
}


def normalize_quality(value: str | None) -> DownloadQuality:
    if value in QUALITY_MAX_WIDTH:
        return value  # type: ignore[return-value]
    return DEFAULT_DOWNLOAD_QUALITY


def effective_max_width(quality: str | None, configured_cap: int) -> int:
    """Resolve a quality tier.

    Research always requests the maximum available size. The administrator cap
    applies to the three resized tiers so it cannot silently downgrade Research.
    """
    normalized = normalize_quality(quality)
    if normalized == "research":
        return 0
    tier_cap = QUALITY_MAX_WIDTH[normalized]
    if configured_cap > 0:
        return min(tier_cap, configured_cap)
    return tier_cap
