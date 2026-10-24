from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from app.iiif.models import (
    ImageResource,
    ImageService,
    MetadataEntry,
    NormalizedCanvas,
    NormalizedManifest,
    ParsedManifest,
    StructureNode,
)

PREFERRED_LANGUAGES = (
    "en",
    "none",
    "zh",
    "zh-hans",
    "zh-hant",
    "de",
    "fr",
    "es",
    "it",
    "ja",
    "pt",
    "nl",
    "ru",
    "ar",
)

UNTITLED = "Untitled book"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

CREATOR_LABELS = {
    "creator",
    "creators",
    "author",
    "authors",
    "artist",
    "artists",
    "writer",
    "photographer",
    "illustrator",
    "editor",
    "contributor",
    "contributors",
    "著者",
    "作者",
    "作画",
    "編集",
}
DATE_LABELS = {
    "date",
    "dates",
    "published",
    "publication",
    "publication date",
    "publication/creation",
    "date of publication",
    "issued",
    "created",
    "creation",
    "year",
    "日期",
    "出版日期",
    "出版年",
}
LANGUAGE_LABELS = {"language", "languages", "langue", "sprache", "语言", "語言", "idioma"}


class ManifestParseError(ValueError):
    """Raised when a payload is not a usable IIIF Manifest."""


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _clean_text(value: str) -> str:
    value = _TAG_RE.sub(" ", value)
    value = html.unescape(value)
    return _WS_RE.sub(" ", value).strip()


def localized(value: Any, languages: tuple[str, ...] = PREFERRED_LANGUAGES) -> str:
    """Extract a readable string from an IIIF label/value/language map."""
    if value is None:
        return ""
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [localized(item, languages) for item in value]
        return _clean_text(" ".join(part for part in parts if part))
    if isinstance(value, dict):
        # JSON-LD value object, e.g. {"@value": "...", "@language": "en"}
        if "@value" in value or "value" in value:
            return localized(value.get("@value", value.get("value")), languages)
        by_language: dict[str, Any] = {}
        for key, item in value.items():
            by_language[str(key).lower()] = item
        for language in languages:
            if language in by_language:
                text = localized(by_language[language], languages)
                if text:
                    return text
        for item in by_language.values():
            text = localized(item, languages)
            if text:
                return text
    return ""


def _abs(value: Any, base: str) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return urljoin(base, value)
    except ValueError:
        return value


def _http_url(value: Any, base: str) -> str | None:
    """Resolve an ID and keep only browser-safe HTTP(S) targets."""
    target = _abs(value, base)
    if not target:
        return None
    try:
        scheme = urlsplit(target).scheme.lower()
    except ValueError:
        return None
    return target if scheme in {"http", "https"} else None


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _type_of(item: dict[str, Any]) -> str:
    value = item.get("type", item.get("@type", ""))
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value)


def _profile_strings(profile: Any) -> list[str]:
    result: list[str] = []
    for item in _as_list(profile):
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            result.extend(str(key) for key in item if isinstance(key, str))
    return result


def _extract_level(profile: Any) -> str | None:
    for item in _profile_strings(profile):
        match = re.search(r"level([0-2])(?:\.json)?$", item, re.IGNORECASE)
        if match:
            return f"level{match.group(1)}"
    return None


def _parse_image_service(value: Any, base: str) -> ImageService | None:
    candidates = [item for item in _as_list(value) if isinstance(item, (dict, str))]
    if not candidates:
        return None

    def score(item: dict[str, Any] | str) -> int:
        if isinstance(item, str):
            return 1
        item_type = _type_of(item).lower()
        profile = _profile_strings(item.get("profile", item.get("support")))
        if "imageservice" in item_type:
            return 4
        if any("/image/" in part for part in profile):
            return 3
        if "profile" in item or "support" in item:
            return 2
        return 1

    candidates = sorted(candidates, key=score, reverse=True)
    raw = candidates[0]
    if isinstance(raw, str):
        raw = {"id": raw}
    service_id = raw.get("id") or raw.get("@id")
    if not service_id:
        return None
    service_id = _http_url(str(service_id), base)
    if not service_id:
        return None
    service_id = re.sub(r"/info\.json/?$", "", service_id, flags=re.IGNORECASE)

    profile = raw.get("profile", raw.get("support"))
    formats: list[str] = []
    qualities: list[str] = []
    sizes: list[dict[str, int]] = []
    for container in [raw, *_as_list(profile)]:
        if not isinstance(container, dict):
            continue
        for key, target in (
            ("formats", formats),
            ("extraFormats", formats),
            ("qualities", qualities),
            ("extraQualities", qualities),
        ):
            for item in _as_list(container.get(key)):
                if isinstance(item, str) and item not in target:
                    target.append(item)
        for size in _as_list(container.get("sizes")):
            if isinstance(size, dict):
                width = _int(size.get("width"))
                height = _int(size.get("height"))
                if width and height:
                    sizes.append({"width": width, "height": height})

    return ImageService(
        id=service_id,
        type=_type_of(raw) or None,
        profile=profile,
        level=_extract_level(profile),
        formats=formats,
        qualities=qualities,
        sizes=sizes,
    )


def _parse_thumbnail(value: Any, base: str) -> str | None:
    for item in _as_list(value):
        if isinstance(item, str):
            resolved = _http_url(item, base)
            if resolved:
                return resolved
            continue
        if not isinstance(item, dict):
            continue
        direct = item.get("id") or item.get("@id")
        if direct:
            resolved = _http_url(str(direct), base)
            if resolved:
                return resolved
            continue
        service = item.get("service")
        service_obj = _parse_image_service(service, base) if service else None
        if service_obj:
            return f"{service_obj.id}/full/400,/0/default.jpg"
    return None


def _link_resources(value: Any, base: str) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for item in _as_list(value):
        if isinstance(item, str):
            target = _http_url(item, base)
            if target:
                links.append({"id": target, "label": "", "format": None, "type": None})
            continue
        if not isinstance(item, dict):
            continue
        target = item.get("id") or item.get("@id")
        if not target:
            continue
        resolved = _http_url(str(target), base)
        if not resolved:
            continue
        links.append(
            {
                "id": resolved,
                "label": localized(item.get("label")),
                "format": item.get("format"),
                "type": _type_of(item) or None,
            }
        )
    return links


def detect_version(data: dict[str, Any]) -> str:
    """Detect Presentation API version from payload structure, not context alone."""
    api_type = _type_of(data).lower()
    if "collection" in api_type:
        raise ManifestParseError(
            "This URL points to a IIIF Collection, not a Manifest. Open one of its items instead."
        )
    if isinstance(data.get("sequences"), list):
        return "2"
    if isinstance(data.get("items"), list) and (
        api_type in {"manifest", "sc:manifest"} or data.get("type") == "Manifest"
    ):
        return "3"
    if api_type in {"sc:manifest"} or ("@type" in data and data.get("@type") == "sc:Manifest"):
        return "2"

    profile = data.get("profile")
    if isinstance(profile, str) and "presentation/2" in profile:
        return "2"

    contexts = " ".join(str(item) for item in _as_list(data.get("@context")))
    if "presentation/3" in contexts:
        return "3"
    if "presentation/2" in contexts:
        return "2"
    raise ManifestParseError(
        "The response is not a recognizable IIIF Presentation API Manifest "
        "(expected Presentation API 2.1 or 3.0)."
    )


class _Normalizer:
    def __init__(self, data: dict[str, Any], manifest_url: str, api_version: str) -> None:
        self.data = data
        self.manifest_url = manifest_url
        self.api_version = api_version
        self.base = _abs(str(data.get("id") or data.get("@id") or manifest_url), manifest_url)
        self.base = self.base or manifest_url
        self.warnings: list[str] = []
        self._warning_set: set[str] = set()

    def warn(self, message: str) -> None:
        if message not in self._warning_set:
            self._warning_set.add(message)
            self.warnings.append(message)

    def run(self) -> NormalizedManifest:
        metadata = self._metadata()
        label = localized(self.data.get("label"))
        if not label:
            label = UNTITLED
            self.warn("The Manifest has no title; a placeholder title was used.")

        summary = localized(self.data.get("summary")) or localized(self.data.get("description"))
        creator = self._creator(metadata)
        language_value = self.data.get("language")
        language = localized(language_value) if language_value else ""
        if not language:
            language = self._metadata_value(metadata, LANGUAGE_LABELS)
        date = localized(self.data.get("navDate")) or self._metadata_value(metadata, DATE_LABELS)

        rights_uri = self.data.get("rights") or self.data.get("license") or ""
        rights_uri = _http_url(str(rights_uri), self.base) or ""

        required_label = ""
        required_value = ""
        required = self.data.get("requiredStatement")
        if required:
            if isinstance(required, dict):
                required_label = localized(required.get("label"))
                required_value = localized(required.get("value"))
            else:
                required_value = localized(required)
        if not required_value and self.data.get("attribution"):
            required_value = localized(self.data.get("attribution"))
            required_label = required_label or "Attribution"

        rights_text = required_value
        if not rights_text:
            for key in ("rights", "license"):
                if self.data.get(key):
                    rights_text = localized(self.data.get(key))
                    break

        provider = self._provider()
        canvases = self._canvases()
        if not canvases:
            raise ManifestParseError("The Manifest contains no Canvas items to read.")
        image_count = sum(1 for canvas in canvases if canvas.image)
        if image_count == 0:
            self.warn(
                "No supported image resources were found. This Manifest may contain audio, "
                "video or annotation-only content."
            )
        elif image_count < len(canvases):
            self.warn(
                f"{len(canvases) - image_count} of {len(canvases)} canvases have no primary "
                "image. A complete offline copy will not be possible for those pages."
            )
        service_count = sum(1 for canvas in canvases if canvas.image and canvas.image.service)
        if image_count and service_count < image_count:
            self.warn(
                f"{image_count - service_count} page image(s) have no IIIF Image API service; "
                "the ordinary image URL will be used."
            )

        structures = self._structures()
        manifest_thumb = _parse_thumbnail(self.data.get("thumbnail"), self.base)
        if not manifest_thumb:
            for canvas in canvases:
                if canvas.thumbnail_url:
                    manifest_thumb = canvas.thumbnail_url
                    break
        if not manifest_thumb:
            for canvas in canvases:
                if canvas.image and canvas.image.service:
                    manifest_thumb = f"{canvas.image.service.id}/full/400,/0/default.jpg"
                    break

        return NormalizedManifest(
            api_version=self.api_version,
            manifest_id=_abs(
                str(self.data.get("id") or self.data.get("@id") or self.manifest_url), self.base
            )
            or self.manifest_url,
            label=label,
            creator=creator,
            description=summary,
            language=language,
            date=date,
            rights=rights_text,
            rights_uri=rights_uri,
            required_statement_label=required_label,
            required_statement_value=required_value,
            thumbnail_url=manifest_thumb,
            homepage=_link_resources(self.data.get("homepage"), self.base),
            rendering=_link_resources(self.data.get("rendering"), self.base),
            see_also=_link_resources(self.data.get("seeAlso"), self.base),
            provider=provider,
            metadata=metadata,
            structures=structures,
            canvases=canvases,
            warnings=self.warnings,
        )

    def _metadata(self) -> list[MetadataEntry]:
        entries: list[MetadataEntry] = []
        for item in _as_list(self.data.get("metadata")):
            if not isinstance(item, dict):
                continue
            label = localized(item.get("label"))
            value = localized(item.get("value"))
            if label or value:
                entries.append(MetadataEntry(label=label, value=value))
        return entries

    def _metadata_value(self, entries: list[MetadataEntry], labels: set[str]) -> str:
        for entry in entries:
            if entry.label.strip().lower() in labels and entry.value:
                return entry.value
        return ""

    def _creator(self, entries: list[MetadataEntry]) -> str:
        values: list[str] = []
        for entry in entries:
            if (
                entry.label.strip().lower() in CREATOR_LABELS
                and entry.value
                and entry.value not in values
            ):
                values.append(entry.value)
        return "; ".join(values)

    def _provider(self) -> str:
        labels: list[str] = []
        for provider in _as_list(self.data.get("provider")):
            if isinstance(provider, dict):
                label = localized(provider.get("label"))
                if label:
                    labels.append(label)
            elif isinstance(provider, str):
                labels.append(_clean_text(provider))
        return "; ".join(dict.fromkeys(labels))

    def _canvases(self) -> list[NormalizedCanvas]:
        if self.api_version == "2":
            sequences = [
                item for item in _as_list(self.data.get("sequences")) if isinstance(item, dict)
            ]
            if len(sequences) > 1:
                self.warn("The Manifest has multiple sequences; only the first is used.")
            canvas_items = []
            if sequences:
                canvas_items = [
                    item
                    for item in _as_list(sequences[0].get("canvases"))
                    if isinstance(item, dict)
                ]
            return [self._canvas_v2(item, index) for index, item in enumerate(canvas_items, 1)]

        items = [item for item in _as_list(self.data.get("items")) if isinstance(item, dict)]
        canvas_items = [item for item in items if _type_of(item).lower() in {"canvas", ""}]
        return [self._canvas_v3(item, index) for index, item in enumerate(canvas_items, 1)]

    def _canvas_v2(self, item: dict[str, Any], index: int) -> NormalizedCanvas:
        canvas = self._canvas_base(item, index)
        images: list[ImageResource] = []
        for image_annotation in _as_list(item.get("images")):
            if not isinstance(image_annotation, dict):
                continue
            resource = image_annotation.get("resource")
            for candidate in _as_list(resource):
                image = self._resource_v2(candidate)
                if image:
                    images.append(image)
        self._apply_images(canvas, images, index)
        canvas.rendering = _link_resources(item.get("rendering"), self.base)
        canvas.annotations = self._other_annotations(item.get("otherContent"))
        canvas.thumbnail_url = _parse_thumbnail(item.get("thumbnail"), self.base)
        return canvas

    def _canvas_v3(self, item: dict[str, Any], index: int) -> NormalizedCanvas:
        canvas = self._canvas_base(item, index)
        images: list[ImageResource] = []
        omitted_pages = 0
        for page in _as_list(item.get("items")):
            if not isinstance(page, dict):
                continue
            annotations = page.get("items")
            if annotations is None and not page.get("id") and not page.get("@id"):
                annotations = [page]
            if annotations is None:
                omitted_pages += 1
                continue
            for annotation in _as_list(annotations):
                if not isinstance(annotation, dict):
                    continue
                motivation = annotation.get("motivation")
                if isinstance(motivation, list):
                    motivation_ok = "painting" in motivation
                else:
                    motivation_ok = motivation in (None, "", "painting")
                if not motivation_ok:
                    continue
                for body in _as_list(annotation.get("body")):
                    images.extend(self._images_from_body(body))
        if omitted_pages:
            self.warn(
                f"{omitted_pages} external AnnotationPage(s) are not embedded in the Manifest; "
                "they were not fetched."
            )
        self._apply_images(canvas, images, index)
        canvas.rendering = _link_resources(item.get("rendering"), self.base)
        canvas.annotations = self._other_annotations(item.get("annotations"))
        canvas.thumbnail_url = _parse_thumbnail(item.get("thumbnail"), self.base)
        return canvas

    def _canvas_base(self, item: dict[str, Any], index: int) -> NormalizedCanvas:
        source_id = item.get("id") or item.get("@id")
        width = _int(item.get("width"))
        height = _int(item.get("height"))
        label = localized(item.get("label")) or f"Page {index}"
        if not source_id:
            self.warn(f"Canvas {index} has no identifier; sequence position will be used.")
        return NormalizedCanvas(
            index=index,
            source_id=_abs(source_id, self.base) if source_id else None,
            label=label,
            width=width,
            height=height,
        )

    def _apply_images(
        self, canvas: NormalizedCanvas, images: list[ImageResource], index: int
    ) -> None:
        if not images:
            canvas.unsupported = True
            self.warn(f"Canvas {index} has no supported painting image.")
            return
        primary_index = next(
            (position for position, image in enumerate(images) if image.service), 0
        )
        primary = images[primary_index]
        others = [image for position, image in enumerate(images) if position != primary_index]
        if others:
            self.warn(
                f"Some canvases contain more than one image resource. Only the primary image of "
                f"each canvas is read or downloaded (first seen on canvas {index})."
            )
        if canvas.width is None:
            canvas.width = primary.width
        if canvas.height is None:
            canvas.height = primary.height
        if canvas.thumbnail_url is None and primary.service:
            canvas.thumbnail_url = f"{primary.service.id}/full/400,/0/default.jpg"
        canvas.image = primary
        canvas.other_images = others
        canvas.unsupported = False

        if not primary.service and primary.format:
            self.warn("Some page images use ordinary image URLs without a IIIF Image API service.")

    def _images_from_body(self, body: Any) -> list[ImageResource]:
        if isinstance(body, str):
            target = _abs(body, self.base)
            if target:
                return [ImageResource(id=target)]
            return []
        if not isinstance(body, dict):
            return []
        body_type = _type_of(body).lower()
        if body_type == "choice":
            images: list[ImageResource] = []
            for item in _as_list(body.get("items")):
                images.extend(self._images_from_body(item))
            return images
        direct = body.get("id") or body.get("@id")
        fmt = body.get("format")
        is_image = (
            "image" in body_type
            or (isinstance(fmt, str) and fmt.lower().startswith("image/"))
            or (body_type in {"", "contentresource"} and bool(direct) and not body.get("service"))
        )
        if not is_image:
            return []
        if not direct:
            service = _parse_image_service(body.get("service"), self.base)
            if service:
                direct = f"{service.id}/full/max/0/default.jpg"
        target = _http_url(direct, self.base) if direct else None
        if not target:
            service = _parse_image_service(body.get("service"), self.base)
            if service:
                target = f"{service.id}/full/max/0/default.jpg"
        if not target:
            return []
        service = _parse_image_service(body.get("service"), self.base)
        return [
            ImageResource(
                id=target,
                type="Image",
                format=fmt if isinstance(fmt, str) else None,
                width=_int(body.get("width")),
                height=_int(body.get("height")),
                label=localized(body.get("label")),
                service=service,
            )
        ]

    def _resource_v2(self, resource: Any) -> ImageResource | None:
        if isinstance(resource, str):
            target = _abs(resource, self.base)
            return ImageResource(id=target) if target else None
        if not isinstance(resource, dict):
            return None
        resource_type = _type_of(resource).lower()
        if resource_type and not any(token in resource_type for token in ("image", "choice")):
            return None
        direct = resource.get("id") or resource.get("@id")
        service = _parse_image_service(resource.get("service"), self.base)
        if not direct and service:
            direct = f"{service.id}/full/max/0/default.jpg"
        target = _http_url(direct, self.base) if direct else None
        if not target and service:
            target = f"{service.id}/full/max/0/default.jpg"
        if not target:
            return None
        return ImageResource(
            id=target,
            type="Image",
            format=resource.get("format") if isinstance(resource.get("format"), str) else None,
            width=_int(resource.get("width")),
            height=_int(resource.get("height")),
            label=localized(resource.get("label")),
            service=service,
        )

    def _other_annotations(self, value: Any) -> list[dict[str, Any]]:
        annotations: list[dict[str, Any]] = []
        for item in _as_list(value)[:50]:
            if isinstance(item, str):
                annotations.append({"id": _abs(item, self.base), "type": None})
            elif isinstance(item, dict):
                annotations.append(
                    {
                        "id": _abs(item.get("id") or item.get("@id"), self.base),
                        "type": _type_of(item) or None,
                        "label": localized(item.get("label")),
                    }
                )
        return annotations

    def _structures(self) -> list[StructureNode]:
        nodes: list[StructureNode] = []
        seen: set[str] = set()

        def canvas_ids(item: dict[str, Any]) -> list[str]:
            ids: list[str] = []
            for child in _as_list(item.get("items")):
                if not isinstance(child, dict):
                    continue
                child_type = _type_of(child).lower()
                target = child.get("id") or child.get("@id")
                if child_type == "canvas" or (
                    target and not child.get("items") and "range" not in child_type
                ):
                    resolved = _abs(target, self.base) if target else None
                    if resolved:
                        ids.append(resolved)
            return ids

        def walk(items: Any, depth: int) -> None:
            for item in _as_list(items):
                if not isinstance(item, dict) or len(nodes) >= 500:
                    continue
                item_type = _type_of(item).lower()
                target = item.get("id") or item.get("@id")
                if item_type and "range" not in item_type and "canvas" in item_type:
                    continue
                if not item.get("items") and "range" not in item_type:
                    continue
                label = localized(item.get("label"))
                if not label and not target:
                    continue
                key = str(target or label)
                if key in seen:
                    continue
                seen.add(key)
                nodes.append(
                    StructureNode(
                        id=_abs(target, self.base) if target else None,
                        label=label,
                        depth=depth,
                        canvas_ids=canvas_ids(item),
                    )
                )
                walk(item.get("items"), depth + 1)

        walk(self.data.get("structures"), 0)
        return nodes


def parse_manifest(data: Any, manifest_url: str) -> ParsedManifest:
    if not isinstance(data, dict):
        raise ManifestParseError("The Manifest response must be a JSON object.")
    version = detect_version(data)
    normalized = _Normalizer(data, manifest_url, version).run()
    return ParsedManifest(normalized=normalized, raw=data)
