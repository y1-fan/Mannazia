from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.services.storage import MIME_BY_FORMAT

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
MAX_PIXELS = 300_000_000

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class DownloadValidationError(Exception):
    pass


def validate_image_file(path: Path) -> tuple[str, str, int, int]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image_format = (image.format or "").upper()
            width, height = image.size
            image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise DownloadValidationError(f"The downloaded file is not a valid image: {exc}") from exc
    if image_format not in ALLOWED_FORMATS:
        raise DownloadValidationError(
            f"Unsupported image format '{image_format or 'unknown'}'. Supported browser formats "
            "are JPEG, PNG, WebP and GIF."
        )
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise DownloadValidationError("The image dimensions are invalid or unreasonably large.")
    mime = MIME_BY_FORMAT.get(image_format)
    if not mime:
        raise DownloadValidationError("Unsupported image format.")
    return image_format, mime, width, height
