from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.iiif.normalize import (
    ManifestParseError,
    detect_version,
    localized,
    parse_manifest,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parses_presentation_v2_manifest() -> None:
    parsed = parse_manifest(load("manifest_v2.json"), "https://example.org/iiif/book1/manifest")
    m = parsed.normalized
    assert m.api_version == "2"
    assert m.label == "The Parchment Codex"
    assert m.creator == "Anonymous scribe"
    assert "<b>" not in m.description
    assert m.description == "A digitized medieval miscellany."
    assert m.language == "Latin"
    assert m.date.startswith("1420")
    assert m.rights_uri == "https://example.org/rights/cc-by-4.0"
    assert "Digitized by the Example Library" in m.rights
    assert m.thumbnail_url == "https://example.org/iiif/book1/thumb/default.jpg"
    assert m.manifest_id == "https://example.org/iiif/book1/manifest"
    assert len(m.canvases) == 3
    assert m.image_canvas_count == 2
    assert m.warnings

    first = m.canvases[0]
    assert first.index == 1
    assert first.label == "Frontispiece"
    assert first.width == 2000
    assert first.image is not None
    assert first.image.service is not None
    assert first.image.service.id == "https://example.org/iiif/book1/canvas/1"
    assert first.image.service.level == "level2"
    assert first.thumbnail_url == "https://example.org/iiif/book1/canvas/1/thumb.jpg"

    second = m.canvases[1]
    assert second.image.service is not None
    assert second.image.service.level == "level1"
    assert "jpg" in second.image.service.formats
    assert len(second.other_images) == 1
    assert second.other_images[0].service is None

    third = m.canvases[2]
    assert third.image is None
    assert third.unsupported is True

    assert m.structures
    assert m.structures[0].label == "Contents"
    assert m.structures[0].depth == 0
    assert m.structures[1].label == "Chapter I"
    assert m.structures[1].depth == 1
    assert m.structures[1].canvas_ids == [
        "https://example.org/iiif/book1/canvas/1",
        "https://example.org/iiif/book1/canvas/2",
    ]
    assert m.rendering[0]["id"] == "https://example.org/download/book1.pdf"
    assert m.see_also[0]["id"] == "https://example.org/data/book1.xml"


def test_parses_presentation_v3_manifest() -> None:
    parsed = parse_manifest(load("manifest_v3.json"), "https://example.org/iiif/book2/manifest")
    m = parsed.normalized
    assert m.api_version == "3"
    assert m.label == "The Book of Hours"
    assert m.creator == "Example Atelier"
    assert m.description == "A luminous fifteenth-century book of hours."
    assert m.language == "Latin; French"
    assert m.date.startswith("1450")
    assert m.rights_uri == "https://example.org/rights/inc"
    assert m.required_statement_value.startswith("Image courtesy")
    assert m.provider == "Example Library"
    assert m.thumbnail_url == "https://example.org/iiif/book2/thumb.jpg"
    assert m.homepage[0]["id"] == "https://example.org/collections/book2"
    assert len(m.canvases) == 3

    first = m.canvases[0]
    assert first.image is not None
    assert first.image.service is not None
    assert first.image.service.level == "level2"
    assert first.image.service.id == "https://example.org/iiif/book2/canvas/1"
    assert first.annotations[0]["id"].endswith("/annotations/page1")

    second = m.canvases[1]
    assert second.image is not None
    assert second.image.service is not None
    assert second.image.service.level == "level1"
    assert len(second.other_images) == 1
    assert second.other_images[0].id == "https://images.example.org/hours/page2.jpg"

    third = m.canvases[2]
    assert third.image is not None
    assert third.image.service is None
    assert third.image.id == "https://images.example.org/hours/page3.png"

    assert any("ordinary image URLs" in warning for warning in m.warnings)
    assert any("more than one image" in warning for warning in m.warnings)
    assert m.structures[0].label == "Contents"
    assert m.structures[1].label == "Prayers"
    assert m.structures[1].canvas_ids == [
        "https://example.org/iiif/book2/canvas/1",
        "https://example.org/iiif/book2/canvas/2",
    ]


def test_missing_metadata_gets_fallbacks() -> None:
    data = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": "https://example.org/minimal/manifest",
        "type": "Manifest",
        "items": [
            {
                "id": "https://example.org/minimal/canvas/1",
                "type": "Canvas",
                "width": 100,
                "height": 200,
                "items": [
                    {
                        "type": "AnnotationPage",
                        "items": [
                            {
                                "type": "Annotation",
                                "motivation": "painting",
                                "body": {
                                    "id": "https://example.org/minimal/page.jpg",
                                    "type": "Image",
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }
    m = parse_manifest(data, "https://example.org/minimal/manifest").normalized
    assert m.label == "Untitled book"
    assert m.creator == ""
    assert m.canvases[0].label == "Page 1"
    assert any("no title" in warning for warning in m.warnings)
    assert any("ordinary image" in warning for warning in m.warnings)


def test_invalid_manifests_produce_useful_errors() -> None:
    with pytest.raises(ManifestParseError, match="JSON object"):
        parse_manifest([], "https://example.org/x")
    with pytest.raises(ManifestParseError, match="Collection"):
        parse_manifest(
            {"type": "Collection", "items": []},
            "https://example.org/collection",
        )
    with pytest.raises(ManifestParseError, match="no Canvas"):
        parse_manifest(
            {
                "type": "Manifest",
                "id": "https://example.org/empty",
                "items": [],
            },
            "https://example.org/empty",
        )
    with pytest.raises(ManifestParseError, match="recognizable"):
        parse_manifest({"foo": "bar"}, "https://example.org/unknown")


def test_version_detection_prefers_payload_structure() -> None:
    v3_with_v2_context = {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "type": "Manifest",
        "items": [],
    }
    assert detect_version(v3_with_v2_context) == "3"
    v2_with_v3_context = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "@type": "sc:Manifest",
        "sequences": [{"canvases": []}],
    }
    assert detect_version(v2_with_v3_context) == "2"


def test_localized_language_maps() -> None:
    assert localized({"en": ["A"], "fr": ["B"]}) == "A"
    assert localized({"fr": ["B"], "none": ["C"]}) == "C"
    assert localized({"zh": ["中文"]}) == "中文"
    assert localized([{"@value": "One", "@language": "en"}]) == "One"
    assert localized("A <em>clean</em>   title") == "A clean title"


def test_contributors_and_publication_metadata_are_used() -> None:
    data = {
        "type": "Manifest",
        "id": "https://example.org/m",
        "metadata": [
            {"label": {"en": ["Contributors"]}, "value": {"en": ["Bolle, Fritz"]}},
            {"label": {"en": ["Publication/creation"]}, "value": {"en": ["1951"]}},
        ],
        "items": [
            {
                "id": "https://example.org/c1",
                "type": "Canvas",
                "items": [
                    {
                        "type": "AnnotationPage",
                        "items": [
                            {
                                "type": "Annotation",
                                "motivation": "painting",
                                "body": {"id": "https://example.org/p.jpg", "type": "Image"},
                            }
                        ],
                    }
                ],
            }
        ],
    }
    m = parse_manifest(data, "https://example.org/m").normalized
    assert m.creator == "Bolle, Fritz"
    assert m.date == "1951"


def test_external_annotation_pages_are_reported_not_crashed() -> None:
    data = {
        "type": "Manifest",
        "id": "https://example.org/m",
        "items": [
            {
                "id": "https://example.org/c1",
                "type": "Canvas",
                "label": "One",
                "items": [{"id": "https://example.org/ap1", "type": "AnnotationPage"}],
            }
        ],
    }
    m = parse_manifest(data, "https://example.org/m").normalized
    assert m.canvases[0].unsupported is True
    assert any("external AnnotationPage" in warning for warning in m.warnings)


def test_unsafe_links_are_not_kept() -> None:
    data = {
        "type": "Manifest",
        "id": "https://example.org/m",
        "rights": "javascript:alert(1)",
        "rightsUri": "javascript:alert(1)",
        "thumbnail": "javascript:alert(1)",
        "rendering": [{"id": "javascript:alert(1)", "label": "bad"}],
        "items": [
            {
                "id": "https://example.org/c1",
                "type": "Canvas",
                "items": [
                    {
                        "type": "AnnotationPage",
                        "items": [
                            {
                                "type": "Annotation",
                                "motivation": "painting",
                                "body": {"id": "javascript:alert(1)", "type": "Image"},
                            }
                        ],
                    }
                ],
            }
        ],
    }
    m = parse_manifest(data, "https://example.org/m").normalized
    assert m.rights_uri == ""
    assert m.rendering == []
    assert m.thumbnail_url is None
    assert m.canvases[0].unsupported is True


def test_relative_image_urls_are_resolved() -> None:
    data = {
        "type": "Manifest",
        "id": "https://example.org/iiif/m",
        "items": [
            {
                "id": "canvas/1",
                "type": "Canvas",
                "items": [
                    {
                        "type": "AnnotationPage",
                        "items": [
                            {
                                "type": "Annotation",
                                "motivation": "painting",
                                "body": {"id": "page.jpg", "type": "Image"},
                            }
                        ],
                    }
                ],
            }
        ],
    }
    m = parse_manifest(data, "https://example.org/iiif/m").normalized
    assert m.canvases[0].source_id == "https://example.org/iiif/canvas/1"
    assert m.canvases[0].image is not None
    assert m.canvases[0].image.id == "https://example.org/iiif/page.jpg"
