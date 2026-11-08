"""Native geometry for numbered brackets and printed linear callouts."""

from typing import Literal

from pdfplumber.page import Page
from pydantic import BaseModel

from onyx.tools.models import DrawingMarkBox

Axis = Literal["horizontal", "vertical"]
Point = tuple[float, float]


class Bracket(BaseModel):
    axis: Axis
    tips: tuple[Point, Point]


class ExtensionPair(BaseModel):
    axis: Axis
    ends: tuple[float, float]
    extensions: tuple[tuple[float, float], tuple[float, float]]

    def matches(self, bracket: Bracket, dx: float, dy: float) -> bool:
        if self.axis != bracket.axis:
            return False
        for (x, y), end, (lo, hi) in zip(
            bracket.tips, self.ends, self.extensions, strict=True
        ):
            along, across = (
                (y + dy, x + dx) if self.axis == "vertical" else (x + dx, y + dy)
            )
            if abs(along - end) > 0.006 or not lo - 0.006 <= across <= hi + 0.006:
                return False
        return True


def extension_pairs(page: Page, box: DrawingMarkBox) -> list[ExtensionPair]:
    """Return native dimension lines with a perpendicular extension at each end."""
    crop = page.crop(page.cropbox)
    x = crop.bbox[0] + (box.x + box.width / 2) * crop.width
    y = crop.bbox[1] + (box.y + box.height / 2) * crop.height
    size = min(box.width * crop.width, box.height * crop.height)
    edges = [
        (
            edge.get("orientation"),
            *(float(edge[k]) for k in ("x0", "top", "x1", "bottom")),
        )
        for edge in crop.edges
        if edge.get("orientation") in {"h", "v"}
    ]
    pairs: list[ExtensionPair] = []
    axes: tuple[Axis, Axis] = ("vertical", "horizontal")
    for axis in axes:
        vertical = axis == "vertical"
        lines = [
            (x0, y0, y1) if vertical else (y0, x0, x1)
            for orientation, x0, y0, x1, y1 in edges
            if orientation == ("v" if vertical else "h")
        ]
        cross = [
            (y0, x0, x1) if vertical else (x0, y0, y1)
            for orientation, x0, y0, x1, y1 in edges
            if orientation == ("h" if vertical else "v")
        ]
        normal_center, along_center = (x, y) if vertical else (y, x)
        along_origin, along_size = (
            (crop.bbox[1], crop.height) if vertical else (crop.bbox[0], crop.width)
        )
        cross_origin, cross_size = (
            (crop.bbox[0], crop.width) if vertical else (crop.bbox[1], crop.height)
        )
        for normal, start, end in set(lines):
            if abs(normal - normal_center) > size * 1.5 or end - start < size * 4:
                continue
            if not start <= along_center <= end:
                continue
            extensions = [
                {
                    (lo, hi)
                    for pos, lo, hi in cross
                    if abs(pos - point) <= 1 and lo <= normal <= hi and hi - lo >= 6
                }
                for point in (start, end)
            ]
            if any(len(options) != 1 for options in extensions):
                continue
            (lo1, hi1), (lo2, hi2) = (next(iter(options)) for options in extensions)
            pairs.append(
                ExtensionPair(
                    axis=axis,
                    ends=(
                        (start - along_origin) / along_size,
                        (end - along_origin) / along_size,
                    ),
                    extensions=(
                        (
                            (lo1 - cross_origin) / cross_size,
                            (hi1 - cross_origin) / cross_size,
                        ),
                        (
                            (lo2 - cross_origin) / cross_size,
                            (hi2 - cross_origin) / cross_size,
                        ),
                    ),
                )
            )
    return pairs
