"""Independent, local PDF change discovery. No model verdicts or CAD measurements.

Align stable ink, compare visible regions, and independently compare native text.
The latter protects small numeric edits from raster noise suppression. Correspondence
is spatial; feature identity and engineering correctness still need review.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from typing import Any, cast

import cv2
import numpy as np
import numpy.typing as npt
import pdfplumber
import pypdfium2 as pdfium
from pdfplumber.page import Page
from pydantic import BaseModel, Field

from onyx.llm.cancellation import AgentCancelled, check_cancelled, current_cancellation
from onyx.tools.models import (
    CommentReviewResult,
    DrawingChange,
    DrawingChangeReview,
    DrawingComment,
    DrawingMarkBox,
)
from onyx.tools.tool_implementations.drawing_review.sheet import MAX_SHEET_PAGES
from onyx.utils.logger import setup_logger
from onyx.utils.process_isolation import run_in_isolated_process

logger = setup_logger()
Image = npt.NDArray[np.uint8]
Transform = npt.NDArray[np.float64]
_MAX_CHANGES = 1000
_MAX_GLYPHS = 30000
_LONG_SIDE = 3200


@dataclass(frozen=True)
class _DimensionReference:
    endpoints: tuple[tuple[float, float], tuple[float, float]]


@dataclass(frozen=True)
class _Label:
    text: str
    box: DrawingMarkBox
    angle: int
    framed: bool = False
    reference: _DimensionReference | None = None


@dataclass(frozen=True)
class _Mapping:
    source: DrawingMarkBox
    matrix: Transform


def _box(x: float, y: float, w: float, h: float) -> DrawingMarkBox:
    left, top = max(0.0, x), max(0.0, y)
    return DrawingMarkBox(
        x=left,
        y=top,
        width=max(0.0, min(1.0, x + w) - left),
        height=max(0.0, min(1.0, y + h) - top),
    )


def _overlap(a: DrawingMarkBox, b: DrawingMarkBox) -> float:
    area = max(0.0, min(a.x + a.width, b.x + b.width) - max(a.x, b.x)) * max(
        0.0, min(a.y + a.height, b.y + b.height) - max(a.y, b.y)
    )
    return area / max(1e-10, min(a.width * a.height, b.width * b.height))


def _inside(a: DrawingMarkBox, b: DrawingMarkBox) -> bool:
    return (
        b.x <= a.x + a.width / 2 <= b.x + b.width
        and b.y <= a.y + a.height / 2 <= b.y + b.height
    )


def _render(document: pdfium.PdfDocument, index: int) -> Image:
    page = document[index]
    try:
        width, height = page.get_size()
        bitmap = page.render(
            scale=min(4.0, _LONG_SIDE / max(width, height)), draw_annots=False
        )
        try:
            return np.asarray(bitmap.to_pil().convert("L"), dtype=np.uint8).copy()
        finally:
            bitmap.close()
    finally:
        page.close()


def _labels(page: Page) -> list[_Label]:
    """Group native glyphs in their own text direction, including angled callouts."""
    crop = page.crop(page.cropbox)
    if len(crop.chars) > _MAX_GLYPHS:
        raise ValueError("Native glyph limit exceeded; this page was not compared.")
    groups: dict[int, list[tuple[float, float, float, dict[str, Any]]]] = {}
    for char in crop.chars:
        text = str(char["text"])
        x0, y0, x1, y1 = (float(char[k]) for k in ("x0", "top", "x1", "bottom"))
        if not text or text.isspace() or x1 <= x0 or y1 <= y0:
            continue
        if (
            x0 < crop.bbox[0]
            or y0 < crop.bbox[1]
            or x1 > crop.bbox[2] + 0.001
            or y1 > crop.bbox[3] + 0.001
        ):
            continue
        if char.get("non_stroking_color") in ((1, 1, 1), (1,), 1):
            continue
        matrix = char["matrix"]
        angle = int(round(math.degrees(math.atan2(-matrix[1], matrix[0]))))
        theta = math.radians(angle)
        dx, dy = math.cos(theta), math.sin(theta)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        along, across = cx * dx + cy * dy, -cx * dy + cy * dx
        size = max(
            1.0,
            x1 - x0,
            y1 - y0,
            float(char["size"]),
            math.hypot(float(matrix[2]), float(matrix[3])),
        )
        groups.setdefault(angle, []).append((across, along, size, char))
    labels: list[_Label] = []
    for angle, glyphs in groups.items():
        lines: list[list[tuple[float, float, float, dict[str, Any]]]] = []
        for glyph in sorted(glyphs, key=lambda g: g[0]):
            if (
                lines
                and abs(glyph[0] - lines[-1][0][0])
                < min(glyph[2], lines[-1][0][2]) * 0.4
            ):
                lines[-1].append(glyph)
            else:
                lines.append([glyph])
        for line in lines:
            words: list[list[tuple[float, float, float, dict[str, Any]]]] = []
            for glyph in sorted(line, key=lambda g: g[1]):
                if (
                    words
                    and glyph[1] - words[-1][-1][1]
                    <= max(glyph[2], words[-1][-1][2]) * 0.95
                ):
                    words[-1].append(glyph)
                else:
                    words.append([glyph])
            for word in words:
                text = "".join(str(g[3]["text"]) for g in word)
                if not re.search(r"\d", text) or len(text) > 96:
                    continue
                x0 = min(float(g[3]["x0"]) for g in word)
                x1 = max(float(g[3]["x1"]) for g in word)
                y0 = min(float(g[3]["top"]) for g in word)
                y1 = max(float(g[3]["bottom"]) for g in word)
                # A short closed frame is structurally different from a nearby dimension.
                margin = max(y1 - y0, x1 - x0) * 0.8
                horizontal = [
                    e
                    for e in crop.edges
                    if e.get("orientation") == "h"
                    and e["x0"] <= x0 + 1
                    and e["x1"] >= x1 - 1
                    and e["x1"] - e["x0"] < 4 * max(x1 - x0, y1 - y0)
                ]
                above = [e for e in horizontal if y0 - margin <= e["top"] <= y0]
                below = [e for e in horizontal if y1 <= e["top"] <= y1 + margin]
                framed = any(
                    any(
                        e.get("orientation") == "v"
                        and abs(e["x0"] - top["x0"]) < 1
                        and e["top"] <= top["top"] + 1
                        and e["bottom"] >= bottom["top"] - 1
                        for e in crop.edges
                    )
                    and any(
                        e.get("orientation") == "v"
                        and abs(e["x0"] - top["x1"]) < 1
                        and e["top"] <= top["top"] + 1
                        and e["bottom"] >= bottom["top"] - 1
                        for e in crop.edges
                    )
                    for top in above
                    for bottom in below
                    if abs(top["x0"] - bottom["x0"]) < 1
                    and abs(top["x1"] - bottom["x1"]) < 1
                )
                labels.append(
                    _Label(
                        text,
                        _box(
                            (x0 - crop.bbox[0]) / crop.width,
                            (y0 - crop.bbox[1]) / crop.height,
                            (x1 - x0) / crop.width,
                            (y1 - y0) / crop.height,
                        ),
                        angle,
                        framed,
                        None if framed else _dimension_reference(crop, x0, y0, x1, y1),
                    )
                )
    return labels


def _dimension_reference(
    page: Page, x0: float, y0: float, x1: float, y1: float
) -> _DimensionReference | None:
    """Trace axis-aligned dimension lines to their extension-line origins.

    Text orientation and dimension-line offset are not feature identifiers.
    Oblique leaders, frames, and uncertain intersections use the local fallback.
    """
    size = min(x1 - x0, y1 - y0)
    tolerance = max(1.0, size * 0.12)
    choices: list[tuple[float, _DimensionReference]] = []
    for vertical in (True, False):
        groups: dict[float, list[tuple[float, float]]] = {}
        cross: list[tuple[float, float, float]] = []
        for edge in page.edges:
            ex0, ey0, ex1, ey1 = (float(edge[k]) for k in ("x0", "top", "x1", "bottom"))
            if vertical:
                normal, start, end = ex0, ey0, ey1
                parallel = abs(ex1 - ex0) < 0.25
                perpendicular = abs(ey1 - ey0) < 0.25
                cross_item = (ey0, ex0, ex1)
            else:
                normal, start, end = ey0, ex0, ex1
                parallel = abs(ey1 - ey0) < 0.25
                perpendicular = abs(ex1 - ex0) < 0.25
                cross_item = (ex0, ey0, ey1)
            if parallel and end - start > 2:
                groups.setdefault(round(normal, 1), []).append((start, end))
            if perpendicular and cross_item[2] - cross_item[1] > max(6, size * 0.35):
                cross.append(cross_item)
        center_normal, center_along = (
            ((x0 + x1) / 2, (y0 + y1) / 2)
            if vertical
            else ((y0 + y1) / 2, (x0 + x1) / 2)
        )
        for normal, segments in groups.items():
            if abs(normal - center_normal) > size * 2:
                continue
            runs: list[list[float]] = []
            for start, end in sorted(segments):
                if runs and start - runs[-1][1] <= size * 2.5:
                    runs[-1][1] = max(runs[-1][1], end)
                else:
                    runs.append([start, end])
            for start, end in runs:
                if end - start < size * 4 or not start <= center_along <= end:
                    continue
                origins: list[tuple[float, float]] = []
                for endpoint in (start, end):
                    hits = []
                    for at, left, right in cross:
                        if (
                            abs(at - endpoint) > tolerance
                            or not left - tolerance <= normal <= right + tolerance
                        ):
                            continue
                        origin = max(
                            (left, right), key=lambda value: abs(value - normal)
                        )
                        if not max(6, size * 0.35) <= abs(origin - normal) <= size * 6:
                            continue
                        hits.append((origin, at))
                    unique = {(round(a, 1), round(b, 1)) for a, b in hits}
                    if len(unique) != 1:
                        break
                    origin, at = next(iter(unique))
                    px, py = (origin, at) if vertical else (at, origin)
                    origins.append(
                        (
                            (px - page.bbox[0]) / page.width,
                            (py - page.bbox[1]) / page.height,
                        )
                    )
                origin_axis = 0 if vertical else 1
                origin_scale = page.width if vertical else page.height
                if (
                    len(origins) == 2
                    and abs(origins[0][origin_axis] - origins[1][origin_axis])
                    * origin_scale
                    <= tolerance
                ):
                    choices.append(
                        (
                            abs(normal - center_normal),
                            _DimensionReference((origins[0], origins[1])),
                        )
                    )
    choices.sort(key=lambda item: item[0])
    if not choices or (len(choices) > 1 and choices[1][0] - choices[0][0] < tolerance):
        return None
    return choices[0][1]


def _same_reference(
    old: _Label, new: _Label, mapping: _Mapping, width: int, height: int
) -> bool:
    if old.reference is None or new.reference is None:
        return False
    source = (
        np.array(
            [[x * width, y * height, 1] for x, y in old.reference.endpoints],
            dtype=np.float64,
        )
        @ mapping.matrix.T
    )
    target = np.array(
        [[x * width, y * height] for x, y in new.reference.endpoints], dtype=np.float64
    )
    return (
        min(
            float(np.linalg.norm(source - target, axis=1).max()),
            float(np.linalg.norm(source - target[::-1], axis=1).max()),
        )
        <= 4
    )


def _estimate(old: Image, new: Image) -> Transform | None:
    detector = cv2.AKAZE.create()
    ko, do = detector.detectAndCompute(old, None)
    kn, dn = detector.detectAndCompute(new, None)
    if do is None or dn is None or len(ko) < 8 or len(kn) < 8:
        return None
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(do, dn, k=2)
    matches = [
        p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.7 * p[1].distance
    ]
    if len(matches) < 10:
        return None
    src = np.asarray([ko[m.queryIdx].pt for m in matches], dtype=np.float32)
    dst = np.asarray([kn[m.trainIdx].pt for m in matches], dtype=np.float32)
    matrix, inliers = cv2.estimateAffinePartial2D(
        src, dst, method=cv2.RANSAC, ransacReprojThreshold=2
    )
    if (
        matrix is None
        or inliers is None
        or int(inliers.sum()) < 10
        or float(inliers.mean()) < 0.35
    ):
        return None
    scale = float(math.hypot(matrix[0, 0], matrix[1, 0]))
    rotation = abs(math.degrees(math.atan2(matrix[1, 0], matrix[0, 0])))
    if abs(scale - 1) > 0.01 or rotation > 3:
        return None
    return np.asarray(matrix, dtype=np.float64)


def _visible_labels(labels: list[_Label], image: Image) -> list[_Label]:
    """Reject native text with no rendered ink, including blanked-out source text."""
    height, width = image.shape
    visible = []
    for label in labels:
        box = label.box
        crop = image[
            max(0, int(box.y * height)) : min(
                height, math.ceil((box.y + box.height) * height)
            ),
            max(0, int(box.x * width)) : min(
                width, math.ceil((box.x + box.width) * width)
            ),
        ]
        if crop.size and np.count_nonzero(crop < 180) >= max(2, crop.size * 0.015):
            visible.append(label)
    return visible


def _warp_box(
    box: DrawingMarkBox, matrix: Transform, width: int, height: int
) -> DrawingMarkBox:
    corners = np.array(
        [
            [box.x * width, box.y * height, 1],
            [(box.x + box.width) * width, box.y * height, 1],
            [box.x * width, (box.y + box.height) * height, 1],
            [(box.x + box.width) * width, (box.y + box.height) * height, 1],
        ],
        dtype=np.float64,
    )
    points = corners @ matrix.T
    x, y = points.min(axis=0)
    right, bottom = points.max(axis=0)
    return _box(
        float(x / width),
        float(y / height),
        float((right - x) / width),
        float((bottom - y) / height),
    )


def _blocks(image: Image) -> list[tuple[int, int, int, int]]:
    ink = (image < 180).astype(np.uint8) * 255
    joined = cv2.dilate(ink, np.ones((13, 13), np.uint8), iterations=2)
    _, _, stats, _ = cv2.connectedComponentsWithStats(joined)
    height, width = image.shape
    return [
        (int(x), int(y), int(w), int(h))
        for x, y, w, h, area in stats[1:]
        if 0.002 * width * height < area < 0.5 * width * height
        and w < 0.9 * width
        and h < 0.9 * height
    ]


def _align(old: Image, new: Image) -> tuple[Image, list[_Mapping], Image, list[str]]:
    height, width = new.shape
    identity = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float64)
    if np.array_equal(old, new):
        return old, [_Mapping(_box(0, 0, 1, 1), identity)], np.full_like(new, 255), []
    matrix = _estimate(old, new)
    if matrix is None:
        # Keep evidence rather than guessing a registration for a sparse or unrelated page.
        return (
            old,
            [],
            np.full_like(new, 255),
            [
                "Page registration could not be verified. Visual differences use supplied page coordinates; text replacements were not inferred."
            ],
        )
    aligned = cast(Image, cv2.warpAffine(old, matrix, (width, height), borderValue=255))
    valid = cv2.warpAffine(
        np.full_like(old, 255),
        matrix,
        (width, height),
        flags=cv2.INTER_NEAREST,
        borderValue=0,
    )
    mappings = [_Mapping(_box(0, 0, 1, 1), matrix)]
    # Align disconnected views only when the best match is distinct and translation-only.
    old_blocks, new_blocks = _blocks(aligned), _blocks(new)
    used: set[int] = set()
    for x, y, w, h in old_blocks:
        if w < 40 or h < 40:
            continue
        candidates: list[tuple[float, int, int, int]] = []
        template = aligned[y : y + h, x : x + w].copy()
        for index, (nx, ny, nw, nh) in enumerate(new_blocks):
            if (
                index in used
                or abs(nw - w) > max(8, w * 0.08)
                or abs(nh - h) > max(8, h * 0.08)
            ):
                continue
            if math.hypot(nx - x, ny - y) > 0.25 * max(width, height):
                continue
            pad = 12
            lx, ly = max(0, nx - pad), max(0, ny - pad)
            region = new[
                ly : min(height, ny + nh + pad), lx : min(width, nx + nw + pad)
            ]
            if region.shape[0] < h or region.shape[1] < w:
                continue
            response = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, point = cv2.minMaxLoc(response)
            candidates.append(
                (float(score), index, lx + point[0] - x, ly + point[1] - y)
            )
        candidates.sort(reverse=True)
        if (
            not candidates
            or candidates[0][0] < 0.97
            or (len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.05)
        ):
            continue
        _, index, dx, dy = candidates[0]
        used.add(index)
        if abs(dx) + abs(dy) < 3:
            continue
        # Avoid erasing overlapping content when reconstructing a moved block.
        source = _box(x / width, y / height, w / width, h / height)
        destination = _box((x + dx) / width, (y + dy) / height, w / width, h / height)
        if any(
            _overlap(
                destination, _box(bx / width, by / height, bw / width, bh / height)
            )
            > 0.05
            for bx, by, bw, bh in old_blocks
            if (bx, by, bw, bh) != (x, y, w, h)
        ):
            continue
        aligned[y : y + h, x : x + w] = 255
        aligned[y + dy : y + dy + h, x + dx : x + dx + w] = template.copy()
        inverse = np.asarray(cv2.invertAffineTransform(matrix), dtype=np.float64)
        original_source = _warp_box(source, inverse, width, height)
        local = matrix.copy()
        local[:, 2] += np.array([dx, dy], dtype=np.float64)
        mappings.append(_Mapping(original_source, local))
    warnings = []
    if np.count_nonzero(valid == 0):
        warnings.append(
            "Registration exposed a page edge. Those pixels remain visual candidates; inspect edge findings."
        )
    return aligned, mappings, np.asarray(valid, dtype=np.uint8), warnings


def _distance(a: DrawingMarkBox, b: DrawingMarkBox, width: int, height: int) -> float:
    return math.hypot(
        (a.x + a.width / 2 - b.x - b.width / 2) * width,
        (a.y + a.height / 2 - b.y - b.height / 2) * height,
    )


class MatchedCallout(BaseModel):
    page: int
    original_text: str
    revised_text: str
    original_box: DrawingMarkBox
    revised_box: DrawingMarkBox


class DrawingEvidence(BaseModel):
    comparison: DrawingChangeReview
    callouts: list[MatchedCallout] = Field(default_factory=list)
    original_labels: dict[int, list[DrawingMarkBox]] = Field(default_factory=dict)


def _native_changes(
    old: list[_Label],
    new: list[_Label],
    mappings: list[_Mapping],
    width: int,
    height: int,
    page: int,
    callouts: list[MatchedCallout],
) -> list[DrawingChange]:
    if not mappings:
        return []
    transformed: list[DrawingMarkBox] = []
    label_mappings: list[_Mapping] = []
    for label in old:
        mapping = next(
            (m for m in reversed(mappings) if _inside(label.box, m.source)), mappings[0]
        )
        transformed.append(_warp_box(label.box, mapping.matrix, width, height))
        label_mappings.append(mapping)
    left, right = set(range(len(old))), set(range(len(new)))
    result: list[DrawingChange] = []
    # Lock unchanged local labels before considering replacements or additions.
    for same in (True, False):
        candidates: dict[tuple[int, int], float] = {}
        for i in left:
            a = old[i]
            box = transformed[i]
            for j in right:
                b = new[j]
                if (a.text == b.text) != same or a.framed != b.framed:
                    continue
                same_reference = _same_reference(a, b, label_mappings[i], width, height)
                if a.reference and b.reference and not same_reference:
                    continue
                angle_distance = abs((a.angle - b.angle + 180) % 360 - 180)
                if not same_reference and not same and angle_distance > 3:
                    continue
                distance = _distance(box, b.box, width, height)
                size = max(
                    box.height * height,
                    box.width * width,
                    b.box.height * height,
                    b.box.width * width,
                )
                if not same_reference and distance > max(8, min(45, size * 0.65)):
                    continue
                candidates[i, j] = distance * 0.001 if same_reference else distance + 5
        for (i, j), distance in sorted(candidates.items(), key=lambda pair: pair[1]):
            if i not in left or j not in right:
                continue
            rivals = [
                d
                for (ii, jj), d in candidates.items()
                if (ii == i or jj == j)
                and (ii, jj) != (i, j)
                and ii in left
                and jj in right
            ]
            if rivals and min(rivals) < distance + 3:
                continue
            left.remove(i)
            right.remove(j)
            if _same_reference(old[i], new[j], label_mappings[i], width, height):
                callouts.append(
                    MatchedCallout(
                        page=page,
                        original_text=old[i].text,
                        revised_text=new[j].text,
                        original_box=old[i].box,
                        revised_box=new[j].box,
                    )
                )
            if not same:
                result.append(
                    DrawingChange(
                        id="",
                        page=page,
                        kind="text_changed",
                        before_text=old[i].text,
                        after_text=new[j].text,
                        original_box=old[i].box,
                        revised_box=new[j].box,
                    )
                )
    result.extend(
        DrawingChange(
            id="",
            page=page,
            kind="text_removed",
            before_text=old[i].text,
            original_box=old[i].box,
            revised_box=transformed[i],
        )
        for i in sorted(left)
    )
    for j in sorted(right):
        # Inverse local transforms provide an original search region, not an old callout.
        mapping = next(
            (
                m
                for m in reversed(mappings)
                if _inside(new[j].box, _warp_box(m.source, m.matrix, width, height))
            ),
            mappings[0],
        )
        old_box = _warp_box(
            new[j].box,
            np.asarray(cv2.invertAffineTransform(mapping.matrix), dtype=np.float64),
            width,
            height,
        )
        result.append(
            DrawingChange(
                id="",
                page=page,
                kind="text_added",
                after_text=new[j].text,
                original_box=old_box,
                revised_box=new[j].box,
            )
        )
    return result


def _visual_changes(
    old: Image, new: Image, mappings: list[_Mapping], page: int
) -> list[DrawingChange]:
    height, width = new.shape
    a = (new < 180).astype(np.uint8)
    b = (old < 180).astype(np.uint8)
    # Native comparisons run independently: a small decimal can survive this tolerance.
    da = cv2.distanceTransform(1 - a, cv2.DIST_L2, 3)
    db = cv2.distanceTransform(1 - b, cv2.DIST_L2, 3)
    diff = (((a > 0) & (db > 1.5)) | ((b > 0) & (da > 1.5))).astype(np.uint8) * 255
    connected = cv2.dilate(diff, np.ones((15, 15), np.uint8))
    _, labels, stats, _ = cv2.connectedComponentsWithStats(connected)
    result = []
    for index, (x, y, w, h, _) in enumerate(stats[1:], 1):
        if (
            np.count_nonzero(
                diff[y : y + h, x : x + w][labels[y : y + h, x : x + w] == index]
            )
            < 3
        ):
            continue
        box = _box(
            float(x / width), float(y / height), float(w / width), float(h / height)
        )
        inverse_box = None
        if mappings:
            mapping = next(
                (
                    m
                    for m in reversed(mappings)
                    if _inside(box, _warp_box(m.source, m.matrix, width, height))
                ),
                mappings[0],
            )
            inverse_box = _warp_box(
                box,
                np.asarray(cv2.invertAffineTransform(mapping.matrix), dtype=np.float64),
                width,
                height,
            )
        result.append(
            DrawingChange(
                id="",
                page=page,
                kind="visual",
                original_box=inverse_box,
                revised_box=box,
            )
        )
    return result


def pair_drawing_pages(
    original: list[Page], revised: list[Page]
) -> tuple[dict[int, int], dict[int, str], dict[int, str]]:
    """Bound identity inspection; do not guess sheet order for unidentified packages."""
    limit = 64
    pattern = re.compile(
        r"\b(?:SHEET|DRAWING(?:\s+(?:NO\.?|NUMBER))?)\s*[:#-]?\s+([A-Z0-9][A-Z0-9._/-]*)",
        re.IGNORECASE,
    )

    def identities(pages: list[Page]) -> dict[int, str | None]:
        result: dict[int, str | None] = {}
        for index, page in enumerate(pages[:limit], 1):
            if len(page.chars) > _MAX_GLYPHS:
                result[index] = None
                continue
            text = page.extract_text() or ""
            identifiers = set(pattern.findall(text.upper()))
            if len(identifiers) == 1:
                result[index] = "sheet:" + next(iter(identifiers))
            elif (
                not identifiers
                and len(text) >= 80
                and len(re.findall(r"[A-Za-z]{3,}", text)) >= 6
            ):
                result[index] = (
                    "text:"
                    + sha256(" ".join(text.upper().split()).encode()).hexdigest()
                )
            else:
                result[index] = None
        return result

    old, new = identities(original), identities(revised)
    pairs: dict[int, int] = {}
    if len(original) == len(revised) == 1 and not (
        old[1]
        and new[1]
        and old[1].startswith("sheet:")
        and new[1].startswith("sheet:")
        and old[1] != new[1]
    ):
        pairs[1] = 1
    else:
        for page, identifier in old.items():
            targets = [n for n, value in new.items() if value == identifier]
            if (
                identifier
                and list(old.values()).count(identifier) == 1
                and len(targets) == 1
            ):
                pairs[page] = targets[0]
    skipped = {
        page: (
            "Sheet identity inspection limit reached."
            if page > limit
            else "Removed sheet."
            if (old.get(page) or "").startswith("sheet:")
            and old[page] not in new.values()
            else "Ambiguous sheet pairing; no reliable unique sheet evidence."
        )
        for page in range(1, len(original) + 1)
        if page not in pairs
    }
    unmatched = {
        page: (
            "Sheet identity inspection limit reached."
            if page > limit
            else "Inserted sheet."
            if (new.get(page) or "").startswith("sheet:")
            and new[page] not in old.values()
            else "Ambiguous sheet pairing; no reliable unique sheet evidence."
        )
        for page in range(1, len(revised) + 1)
        if page not in pairs.values()
    }
    return pairs, skipped, unmatched


def compare_drawing_pdfs(
    original: bytes, revised: bytes, selected_pages: list[int] | None = None
) -> DrawingChangeReview:
    return build_drawing_evidence(original, revised, selected_pages).comparison


def build_drawing_evidence(
    original: bytes, revised: bytes, selected_pages: list[int] | None = None
) -> DrawingEvidence:
    """Read revision evidence once for verification and change reporting."""
    callouts: list[MatchedCallout] = []
    changes: list[DrawingChange] = []
    compared: list[int] = []
    original_labels: dict[int, list[DrawingMarkBox]] = {}
    warnings: list[str] = []
    coverage_incomplete = False
    old_pdf, new_pdf = pdfium.PdfDocument(original), pdfium.PdfDocument(revised)
    try:
        if selected_pages and any(
            page < 1 or page > len(old_pdf) for page in selected_pages
        ):
            return DrawingEvidence(
                comparison=DrawingChangeReview(
                    status="failed",
                    warnings=[
                        "Requested pages are outside the PDF. No change comparison was performed."
                    ],
                )
            )
        with (
            pdfplumber.open(BytesIO(original), unicode_norm="NFKC") as old_text,
            pdfplumber.open(BytesIO(revised), unicode_norm="NFKC") as new_text,
        ):
            pairs, skipped, unmatched = pair_drawing_pages(
                old_text.pages, new_text.pages
            )
            scope = selected_pages or list(range(1, len(old_pdf) + 1))
            skipped = {
                page: reason for page, reason in skipped.items() if page in scope
            }
            for number, target in list(pairs.items()):
                if number not in scope:
                    continue
                if number > MAX_SHEET_PAGES or target > MAX_SHEET_PAGES:
                    skipped[number] = (
                        f"Page limit: Before {number}, After {target} were not checked."
                    )
            for index in range(min(len(old_pdf), MAX_SHEET_PAGES)):
                number = index + 1
                if selected_pages and number not in selected_pages:
                    continue
                target = pairs.get(number)
                if target is None or target > MAX_SHEET_PAGES:
                    continue
                old, new = _render(old_pdf, index), _render(new_pdf, target - 1)
                if old.shape != new.shape:
                    skipped[number] = (
                        "Page sizes differ; local comparison was not performed."
                    )
                    coverage_incomplete = True
                    warnings.append(
                        f"Page {number}: page sizes differ; comparison was not performed."
                    )
                    continue
                aligned, mappings, _, notes = _align(old, new)
                coverage_incomplete = coverage_incomplete or bool(notes)
                warnings.extend(f"Page {number}: {note}" for note in notes)
                before, after = (
                    _visible_labels(_labels(old_text.pages[index]), old),
                    _visible_labels(_labels(new_text.pages[target - 1]), new),
                )
                if not before or not after:
                    warnings.append(
                        f"Page {number}: native numeric text is unavailable in one revision. Using paired visual verification for scans or outlined text."
                    )
                original_labels[number] = [label.box for label in before]
                native = _native_changes(
                    before,
                    after,
                    mappings,
                    new.shape[1],
                    new.shape[0],
                    number,
                    callouts,
                )
                visual = _visual_changes(aligned, new, mappings, number)
                # Keep visual evidence, including geometry around a changed callout.
                changes.extend(
                    c.model_copy(update={"revised_page": target})
                    for c in native + visual
                )
                compared.append(number)
                if len(changes) > _MAX_CHANGES:
                    coverage_incomplete = True
                    warnings.append(
                        f"Change limit {_MAX_CHANGES} exceeded on page {number}; remaining candidates and pages were not returned."
                    )
                    changes = changes[:_MAX_CHANGES]
                    break
    finally:
        old_pdf.close()
        new_pdf.close()
    changes = [c.model_copy(update={"id": f"dc{i}"}) for i, c in enumerate(changes, 1)]
    return DrawingEvidence(
        callouts=callouts,
        original_labels=original_labels,
        comparison=DrawingChangeReview(
            status="partial"
            if coverage_incomplete or skipped or unmatched
            else "complete",
            changes=changes,
            compared_pages=compared,
            page_pairs=pairs,
            skipped_original_pages=skipped,
            unmatched_revised_pages=unmatched,
            warnings=warnings,
        ),
    )


def _associate(
    changes: DrawingChangeReview, comments: list[DrawingComment]
) -> DrawingChangeReview:
    linked = []
    for change in changes.changes:
        ids = []
        for comment in comments:
            if change.page != comment.page:
                continue
            # A spatial link is a candidate, never proof of authorization or resolution.
            if (
                comment.box
                and not comment.page_level
                and change.original_box
                and _overlap(comment.box, change.original_box) > 0.25
            ) or (
                comment.revised_box
                and not comment.revised_page_level
                and change.revised_box
                and _overlap(comment.revised_box, change.revised_box) > 0.25
            ):
                ids.append(comment.id)
        verified = [
            comment.id
            for comment in comments
            if change.id in comment.verified_change_ids
        ]
        linked.append(
            change.model_copy(
                update={
                    "possible_comment_ids": [
                        item for item in ids if item not in verified
                    ],
                    "verified_comment_ids": verified,
                }
            )
        )
    return changes.model_copy(update={"changes": linked})


def attach_drawing_changes(
    result: CommentReviewResult,
    original: bytes,
    revised: bytes,
    selected_pages: list[int] | None = None,
) -> CommentReviewResult:
    """Fail separately; preserve all existing MechVL comment results."""
    check_cancelled()
    try:
        review = run_in_isolated_process(
            compare_drawing_pdfs, original, revised, selected_pages, timeout=120
        )
    except Exception:
        logger.warning("Independent PDF change comparison failed", exc_info=True)
        review = DrawingChangeReview(
            status="failed",
            warnings=[
                "The independent PDF comparison did not finish. Comment results were preserved."
            ],
        )
    check_cancelled()
    return present_drawing_changes(result, review)


def load_drawing_evidence(
    original: bytes, revised: bytes, selected_pages: list[int] | None = None
) -> DrawingEvidence:
    deadline = time.monotonic() + 120
    combined = DrawingEvidence(
        comparison=DrawingChangeReview(status="complete", page_pairs={})
    )
    try:
        pairs, skipped, unmatched, total = run_in_isolated_process(
            _read_page_pairing, original, revised, timeout=30
        )
    except (Exception, AgentCancelled):
        combined.comparison.status = "failed"
        combined.comparison.warnings.append(
            "PDF pairing did not finish; no pages were compared."
        )
        return combined
    scope = selected_pages or list(range(1, total + 1))
    combined.comparison.page_pairs = pairs
    combined.comparison.skipped_original_pages = {
        page: reason for page, reason in skipped.items() if page in scope
    }
    combined.comparison.unmatched_revised_pages = unmatched
    for page in scope:
        target = pairs.get(page)
        if target is None:
            continue
        signal = current_cancellation()
        reason = (
            "cancelled"
            if signal and signal.cancelled
            else "timeout"
            if time.monotonic() >= deadline
            else "page limit"
            if max(page, target) > MAX_SHEET_PAGES
            else None
        )
        if reason:
            combined.comparison.skipped_original_pages[page] = reason
            continue
        try:
            item = run_in_isolated_process(
                build_drawing_evidence,
                original,
                revised,
                [page],
                timeout=min(30, deadline - time.monotonic()),
            )
        except (Exception, AgentCancelled) as error:
            combined.comparison.skipped_original_pages[page] = (
                "cancelled"
                if isinstance(error, AgentCancelled)
                else "PDF comparison failed or timed out"
            )
            continue
        combined.callouts.extend(item.callouts)
        combined.original_labels.update(item.original_labels)
        if page not in item.comparison.compared_pages:
            combined.comparison.skipped_original_pages[page] = (
                "PDF page could not be compared."
            )
        combined.comparison.changes.extend(item.comparison.changes)
        combined.comparison.compared_pages.extend(item.comparison.compared_pages)
        combined.comparison.warnings.extend(item.comparison.warnings)
        if item.comparison.status != "complete":
            combined.comparison.status = "partial"
    if len(combined.comparison.changes) > _MAX_CHANGES:
        combined.comparison.status = "partial"
        combined.comparison.warnings.append(
            "Candidate limit reached; additional differences were not checked."
        )
    combined.comparison.changes = [
        change.model_copy(update={"id": f"dc{index}"})
        for index, change in enumerate(combined.comparison.changes[:_MAX_CHANGES], 1)
    ]
    if combined.comparison.skipped_original_pages or unmatched:
        combined.comparison.status = "partial"
    return combined


def _read_page_pairing(
    original: bytes, revised: bytes
) -> tuple[dict[int, int], dict[int, str], dict[int, str], int]:
    with (
        pdfplumber.open(BytesIO(original)) as old,
        pdfplumber.open(BytesIO(revised)) as new,
    ):
        pairs, skipped, unmatched = pair_drawing_pages(old.pages, new.pages)
        return pairs, skipped, unmatched, len(old.pages)


def present_drawing_changes(
    result: CommentReviewResult, review: DrawingChangeReview
) -> CommentReviewResult:
    review = _associate(review, result.comments)
    lines = [
        "\n## Drawing changes",
        "Printed text correspondence and visual candidates; geometry and design correctness require confirmation. Native review annotations are excluded. Flattened marks may remain. Page pairs use reliable sheet evidence.",
    ]
    for c in review.changes:
        if c.vision_validation != "confirmed":
            continue
        if c.kind == "text_changed":
            evidence = f"Printed text {c.before_text!r} → {c.after_text!r}."
        elif c.kind == "text_removed":
            evidence = f"Printed callout removed: {c.before_text!r}."
        elif c.kind == "text_added":
            evidence = f"Printed callout added: {c.after_text!r}."
        else:
            evidence = "Visual change."
        if c.vision_explanation:
            evidence = f"{evidence} Visual observation: {c.vision_explanation}"
        link = (
            "Possible comment link: " + ", ".join(c.possible_comment_ids)
            if c.possible_comment_ids
            else "No comment link confirmed."
        )
        if c.verified_comment_ids:
            ids = ", ".join(c.verified_comment_ids)
            lines.append(
                f"- Comment evidence for {ids} (already covered above): {evidence}"
            )
            continue
        lines.append(f"- {c.id}, page {c.page}, {c.kind}: {evidence} {link}")
    lines.append(
        f"Comment verification: {result.comment_verification_status}. Change validation: {review.validation_status}."
    )
    lines.append(
        f"Compared Before pages: {review.compared_pages}. Validated Before pages: {review.validated_pages}. Page pairs: {review.page_pairs}."
    )
    if not any(c.vision_validation == "confirmed" for c in review.changes):
        lines.append(
            "No confirmed differences."
            if review.validation_status == "complete"
            and review.status == "complete"
            and result.comment_verification_status == "complete"
            else "Review incomplete; no confirmed differences in completed checks."
        )
    lines.extend(
        f"Before page {page}: {reason}"
        for page, reason in review.skipped_original_pages.items()
    )
    lines.extend(
        f"After page {page}: {reason}"
        for page, reason in review.unmatched_revised_pages.items()
    )
    lines.extend(review.warnings)
    return result.model_copy(
        update={
            "drawing_changes": review,
            "report": result.report + "\n" + "\n".join(lines),
        }
    )
