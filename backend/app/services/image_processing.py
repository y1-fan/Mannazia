from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageOps

PROCESSING_FAILED_WARNING = (
    "Image processing failed for some pages; the original source image was stored instead."
)

TARGET_LONG_EDGE = {
    "reading": 1200,
    "standard": 2000,
    "appreciation": 2800,
}
JPEG_QUALITY = {
    "reading": 70,
    "standard": 80,
    "appreciation": 90,
}


class ImageProcessingError(Exception):
    pass


def process_page_image(path: Path, quality: str) -> None:
    """Resize/re-encode a downloaded page for a quality tier.

    All processed tiers keep colour. The source is replaced only after the
    processed JPEG has been written.
    """
    if quality not in TARGET_LONG_EDGE:
        return
    target = TARGET_LONG_EDGE[quality]
    processed_path = path.with_name(f"{path.name}.processing")
    try:
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened)
            width, height = image.size
            needs_resize = max(width, height) > target

            # Avoid re-encoding a source that already fits the target.
            if quality != "reading" and not needs_resize:
                return

            output = _to_rgb(image)
            if needs_resize:
                output.thumbnail((target, target), Image.Resampling.LANCZOS)
            output.save(
                processed_path,
                format="JPEG",
                quality=JPEG_QUALITY[quality],
                optimize=True,
                progressive=False,
            )
        os.replace(processed_path, path)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        processed_path.unlink(missing_ok=True)
        raise ImageProcessingError(f"Could not process the page image: {exc}") from exc


def _to_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    if image.mode == "L":
        return image.convert("RGB")
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")
