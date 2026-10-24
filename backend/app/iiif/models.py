from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MetadataEntry(BaseModel):
    label: str
    value: str


class ImageService(BaseModel):
    id: str
    type: str | None = None
    profile: Any = None
    level: str | None = None
    formats: list[str] = Field(default_factory=list)
    qualities: list[str] = Field(default_factory=list)
    sizes: list[dict[str, int]] = Field(default_factory=list)


class ImageResource(BaseModel):
    id: str
    type: str = "Image"
    format: str | None = None
    width: int | None = None
    height: int | None = None
    label: str = ""
    service: ImageService | None = None


class StructureNode(BaseModel):
    id: str | None = None
    label: str = ""
    depth: int = 0
    canvas_ids: list[str] = Field(default_factory=list)


class NormalizedCanvas(BaseModel):
    index: int
    source_id: str | None = None
    label: str = ""
    width: int | None = None
    height: int | None = None
    image: ImageResource | None = None
    other_images: list[ImageResource] = Field(default_factory=list)
    thumbnail_url: str | None = None
    annotations: list[dict[str, Any]] = Field(default_factory=list)
    rendering: list[dict[str, Any]] = Field(default_factory=list)
    unsupported: bool = False
    warnings: list[str] = Field(default_factory=list)


class NormalizedManifest(BaseModel):
    api_version: str
    manifest_id: str
    label: str = ""
    creator: str = ""
    description: str = ""
    language: str = ""
    date: str = ""
    rights: str = ""
    rights_uri: str = ""
    required_statement_label: str = ""
    required_statement_value: str = ""
    thumbnail_url: str | None = None
    homepage: list[dict[str, Any]] = Field(default_factory=list)
    rendering: list[dict[str, Any]] = Field(default_factory=list)
    see_also: list[dict[str, Any]] = Field(default_factory=list)
    provider: str = ""
    metadata: list[MetadataEntry] = Field(default_factory=list)
    structures: list[StructureNode] = Field(default_factory=list)
    canvases: list[NormalizedCanvas] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def image_canvas_count(self) -> int:
        return sum(1 for canvas in self.canvases if canvas.image is not None)


class ParsedManifest(BaseModel):
    normalized: NormalizedManifest
    raw: dict[str, Any]
