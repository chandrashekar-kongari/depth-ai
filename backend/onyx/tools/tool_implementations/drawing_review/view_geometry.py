"""Geometry used to match drawing views across revisions."""

import re
from dataclasses import dataclass, field
from io import BytesIO

import cv2
import numpy as np
import numpy.typing as npt
import pdfplumber

from onyx.engineering.drawing_changes import dimension_reference
from onyx.tools.tool_implementations.drawing_review.spans import SheetSpan

Ink = npt.NDArray[np.uint8]
Point = tuple[float, float]
Bounds = tuple[float, float, float, float]
_SIZE = 128


@dataclass(frozen=True)
class Stroke:
    points: tuple[Point, ...]
    width: float


@dataclass(frozen=True)
class PageGeometry:
    width: float
    height: float
    strokes: tuple[Stroke, ...]
    dimension_origins: dict[str, tuple[Point, Point]] = field(default_factory=dict)


def extract_page_geometry(
    data: bytes, max_pages: int, spans: tuple[SheetSpan, ...] = ()
) -> dict[int, PageGeometry]:
    pages: dict[int, PageGeometry] = {}
    with pdfplumber.open(BytesIO(data)) as pdf:
        for index, page in enumerate(pdf.pages[:max_pages], 1):
            crop = page.crop(page.cropbox)
            origins: dict[str, tuple[Point, Point]] = {}
            for span in spans:
                if span.page != index or not re.fullmatch(
                    r"[Øø⌀R]?\s*\d+(?:\.\d+)?(?:\s*±\s*\d+(?:\.\d+)?)?", span.text
                ):
                    continue
                reference = dimension_reference(
                    crop,
                    crop.bbox[0] + span.x * crop.width,
                    crop.bbox[1] + span.y * crop.height,
                    crop.bbox[0] + (span.x + span.width) * crop.width,
                    crop.bbox[1] + (span.y + span.height) * crop.height,
                )
                if reference is not None:
                    origins[span.span_id] = reference.endpoints
            strokes: list[Stroke] = []
            for shape in (*crop.lines, *crop.rects, *crop.curves):
                color = shape.get("stroking_color")
                if (
                    not shape.get("stroke")
                    or shape.get("fill")
                    or (shape.get("dash") and shape["dash"][0])
                    or (
                        isinstance(color, tuple)
                        and len(color) == 3
                        and color[0] > max(color[1:]) + 0.25
                    )
                ):
                    continue
                points: list[Point] = []
                for command, *vertices in shape.get("path", ()):
                    if command == "m":
                        if len(points) > 1:
                            strokes.append(
                                Stroke(tuple(points), float(shape["linewidth"]))
                            )
                        points = list(vertices)
                    elif command == "l":
                        points.extend(vertices)
                    elif command == "h" and points:
                        points.append(points[0])
                    elif command == "c" and points:
                        curve = np.asarray([points[-1], *vertices], dtype=np.float64)
                        for t in np.linspace(0, 1, 17)[1:]:
                            u = 1 - t
                            x, y = (
                                np.array([u**3, 3 * u * u * t, 3 * u * t * t, t**3])
                                @ curve
                            )
                            points.append((float(x), float(y)))
                if len(points) > 1:
                    strokes.append(Stroke(tuple(points), float(shape["linewidth"])))
            pages[index] = PageGeometry(
                crop.width,
                crop.height,
                tuple(
                    Stroke(
                        tuple(
                            (x - crop.bbox[0], y - crop.bbox[1])
                            for x, y in stroke.points
                        ),
                        stroke.width,
                    )
                    for stroke in strokes
                ),
                origins,
            )
    return pages


def view_strokes(page: PageGeometry, core: Bounds, complete: Bounds) -> Ink | None:
    left, top, right, bottom = core
    margin = 0.03
    bounds = (
        min(complete[0], left) - margin,
        min(complete[1], top) - margin,
        max(complete[2], right) + margin,
        max(complete[3], bottom) + margin,
    )
    selected: list[Stroke] = []
    nearby: list[Stroke] = []
    for stroke in page.strokes:
        xs, ys = zip(*stroke.points, strict=True)
        x0, x1 = min(xs) / page.width, max(xs) / page.width
        y0, y1 = min(ys) / page.height, max(ys) / page.height
        if (x1 - x0) >= 0.8 or (y1 - y0) >= 0.8:
            continue
        if (
            bounds[0] <= (x0 + x1) / 2 <= bounds[2]
            and bounds[1] <= (y0 + y1) / 2 <= bounds[3]
        ):
            nearby.append(stroke)
            if x0 <= right and x1 >= left and y0 <= bottom and y1 >= top:
                selected.append(stroke)
    if not selected:
        return None
    # Include adjacent outline segments past the detected core.
    heavy = max(stroke.width for stroke in selected)
    outlines = [stroke for stroke in nearby if stroke.width >= heavy * 0.8]
    points = np.asarray([point for stroke in outlines for point in stroke.points])
    start = points.min(axis=0)
    extent = points.max(axis=0) - start
    if min(extent) <= 3:
        return None
    scale = (_SIZE - 12) / max(extent)
    center = (_SIZE - extent * scale) / 2
    mask = np.zeros((_SIZE, _SIZE), dtype=np.uint8)
    for stroke in outlines:
        coords = np.rint((np.asarray(stroke.points) - start) * scale + center).astype(
            np.int32
        )
        cv2.polylines(mask, [coords], False, 1, 2)
    return mask


def raster_shape(geometry: Ink) -> Ink:
    y, x = np.nonzero(geometry < 185)
    canvas = np.zeros((_SIZE, _SIZE), dtype=np.uint8)
    if len(x) < 20:
        return canvas
    ink = geometry[y.min() : y.max() + 1, x.min() : x.max() + 1] < 185
    height, width = ink.shape
    scale = (_SIZE - 12) / max(height, width)
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    resized = cv2.resize(ink.astype(np.uint8) * 255, size, interpolation=cv2.INTER_AREA)
    left, top = (_SIZE - size[0]) // 2, (_SIZE - size[1]) // 2
    canvas[top : top + size[1], left : left + size[0]] = resized > 20
    return canvas


def _outline_turns(ink: Ink) -> npt.NDArray[np.float32] | None:
    contours, _ = cv2.findContours(ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    outline = max(contours, key=cv2.contourArea)
    _, _, width, height = cv2.boundingRect(outline)
    if cv2.contourArea(outline) < 0.3 * width * height:
        return None
    simplified = cv2.approxPolyDP(outline, 0.018 * cv2.arcLength(outline, True), True)
    perimeter = cv2.arcLength(simplified, True)
    if perimeter == 0:
        return None
    points = simplified.reshape(-1, 2).astype(np.float32)
    # Normalize edge directions relative to the previous edge. Dimensions may change.
    edges = np.roll(points, -1, axis=0) - points
    angles = np.arctan2(edges[:, 1], edges[:, 0])
    turns = (angles - np.roll(angles, 1) + np.pi) % (2 * np.pi) - np.pi
    return turns.astype(np.float32)


def aligned_similarity(original: Ink, revised: Ink) -> float:
    """Measure bidirectional overlap after centering, uniform scaling and rotation."""
    if not original.any() or not revised.any():
        return 0.0
    kernel = np.ones((7, 7), dtype=np.uint8)
    near_original = cv2.dilate(original, kernel)
    scores: list[float] = []
    for quarter_turn in range(4):
        rotated = np.ascontiguousarray(np.rot90(revised, quarter_turn))
        near_revised = cv2.dilate(rotated, kernel)
        forward = float((near_original * rotated).sum() / rotated.sum())
        reverse = float((near_revised * original).sum() / original.sum())
        scores.append(min(forward, reverse))
    return max(scores)


def outline_correspondence(original: Ink, revised: Ink) -> bool:
    """Find the same boundary structure even after a change in aspect ratio."""
    old, new = _outline_turns(original), _outline_turns(revised)
    if old is None or new is None:
        return False
    return len(old) == len(new) and any(
        np.max(np.abs(old - np.roll(new, offset))) <= 0.24 for offset in range(len(new))
    )
