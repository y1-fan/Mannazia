from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.services.image_processing import process_page_image


def make_image(
    path: Path, size: tuple[int, int], color: str = "#f4efe2", mode: str = "RGB"
) -> None:
    Image.new(mode, size, color).save(path, format="JPEG")


def test_reading_resizes_to_long_edge_and_keeps_color(tmp_path: Path) -> None:
    path = tmp_path / "page.jpg"
    make_image(path, (2400, 3200), color="#d22b2b")

    process_page_image(path, "reading")

    with Image.open(path) as image:
        assert image.mode == "RGB"
        assert max(image.size) == 1200
        assert image.format == "JPEG"


def test_standard_resizes_to_its_long_edge(tmp_path: Path) -> None:
    path = tmp_path / "page.jpg"
    make_image(path, (3000, 4000))

    process_page_image(path, "standard")

    with Image.open(path) as image:
        assert image.mode == "RGB"
        assert max(image.size) == 2000


def test_small_jpeg_is_not_reencoded_for_standard(tmp_path: Path) -> None:
    path = tmp_path / "small.jpg"
    make_image(path, (800, 1200))
    original = path.read_bytes()

    process_page_image(path, "standard")

    assert path.read_bytes() == original


def test_small_image_is_not_upscaled_for_appreciation(tmp_path: Path) -> None:
    path = tmp_path / "small.jpg"
    make_image(path, (900, 1300))
    original = path.read_bytes()

    process_page_image(path, "appreciation")

    assert path.read_bytes() == original


def test_appreciation_resizes_to_its_long_edge(tmp_path: Path) -> None:
    path = tmp_path / "large.jpg"
    make_image(path, (4000, 3000))

    process_page_image(path, "appreciation")

    with Image.open(path) as image:
        assert max(image.size) == 2800
