"""Versioned document operations shared by the PDF editor and agent tools."""

import math
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class WorkspaceCreate(BaseModel):
    file_ids: list[str] = Field(min_length=1, max_length=2)


class PageGeometry(BaseModel):
    width: float
    height: float
    crop: tuple[float, float, float, float]
    rotation: int


class WorkspaceDocument(BaseModel):
    id: str
    name: str
    sha256: str
    pages: list[PageGeometry]


class Point(BaseModel):
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class Size(BaseModel):
    width: float = Field(gt=0, allow_inf_nan=False)
    height: float = Field(gt=0, allow_inf_nan=False)


class AnnotationRect(BaseModel):
    origin: Point
    size: Size


class Annotation(BaseModel):
    """SDK-native top-left display-page points, paired with immutable page metadata."""

    model_config = ConfigDict(extra="allow")
    id: str = Field(min_length=1, max_length=128)
    pageIndex: int = Field(ge=0, le=999)
    type: int = Field(ge=1, le=28)
    rect: AnnotationRect
    contents: str = Field(default="", max_length=10000)

    @model_validator(mode="after")
    def supported(self) -> "Annotation":
        if self.type not in {1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15}:
            raise ValueError("This annotation type is not editable in the workspace")
        return self


class Anchor(BaseModel):
    page: int = Field(ge=1, le=1000)
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    width: float = Field(gt=0, le=1, allow_inf_nan=False)
    height: float = Field(gt=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def bounded(self) -> "Anchor":
        if self.x + self.width > 1.00001 or self.y + self.height > 1.00001:
            raise ValueError("Anchor extends outside the page")
        return self


class WorkspaceCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    expected_version: int = Field(ge=0)
    action: Literal[
        "upsert_annotation",
        "delete_annotation",
        "set_anchor",
        "calibrate",
        "undo",
        "redo",
    ]
    document_id: str = Field(default="", max_length=256)
    annotation: Annotation | None = None
    annotation_id: str = Field(default="", max_length=128)
    appearance: str | None = Field(default=None, max_length=2800000)
    issue_id: str = Field(default="", max_length=128)
    anchor: Anchor | None = None
    page: int = Field(default=1, ge=1, le=1000)
    units_per_point: float | None = Field(
        default=None, gt=0, le=1e9, allow_inf_nan=False
    )
    unit: Literal["mm", "cm", "m", "in", "ft"] = "mm"


class WorkspaceSnapshot(BaseModel):
    id: UUID
    version: int
    documents: list[WorkspaceDocument]
    state: dict[str, JsonValue]
    can_undo: bool
    can_redo: bool


def validate_annotation(annotation: Annotation, page: PageGeometry) -> None:
    rect = annotation.rect
    if (
        rect.origin.x < -0.5
        or rect.origin.y < -0.5
        or rect.origin.x + rect.size.width > page.width + 0.5
        or rect.origin.y + rect.size.height > page.height + 0.5
    ):
        raise ValueError("Annotation is outside its page")

    # Reject nested NaN/Infinity before JSONB serialization, including path vertices.
    def finite(value: JsonValue) -> None:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Annotation contains a non-finite coordinate")
        if isinstance(value, dict):
            for child in value.values():
                finite(child)
        elif isinstance(value, list):
            for child in value:
                finite(child)

    finite(annotation.model_dump(mode="json"))
