from __future__ import annotations

from app.iiif.models import ImageResource, NormalizedCanvas
from app.services.covers import choose_cover, cover_url


def canvas(index: int, label: str, **overrides) -> NormalizedCanvas:
    return NormalizedCanvas(
        index=index,
        label=label,
        image=ImageResource(id=f"https://example.org/{index}.jpg"),
        thumbnail_url=f"https://example.org/{index}-thumb.jpg",
        **overrides,
    )


def test_first_readable_canvas_is_the_default_cover() -> None:
    first = canvas(1, "1")
    second = canvas(2, "2")
    selected = choose_cover([first, second])
    assert selected is first
    assert cover_url(selected) == "https://example.org/1-thumb.jpg"


def test_labelled_front_cover_wins_over_scan_targets() -> None:
    target = canvas(1, "Colour target")
    cover = canvas(2, "Front cover")
    selected = choose_cover([target, cover])
    assert selected is cover


def test_back_cover_is_not_chosen_as_front_cover() -> None:
    back = canvas(1, "Back cover")
    first_page = canvas(2, "Page 1")
    selected = choose_cover([back, first_page])
    assert selected is first_page


def test_canvas_without_an_image_is_skipped() -> None:
    without_image = NormalizedCanvas(index=1, label="Cover", image=None)
    page = canvas(2, "Page 1")
    selected = choose_cover([without_image, page])
    assert selected is page
