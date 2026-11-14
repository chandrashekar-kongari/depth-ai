"""Text spans and page boxes for a plotted sheet.

A box is a fraction of the page. The origin is the top left.
The model chooses a span id. It does not choose coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pdfplumber.page import CroppedPage, FilteredPage

from onyx.utils.logger import setup_logger

logger = setup_logger()

_MAX_SPANS_PER_PAGE = 4096
_MAX_SPAN_CHARS = 80
_PAGE_BOX = (0.0, 0.0, 1.0, 1.0)


@dataclass(frozen=True)
class SheetSpan:
    span_id: str
    page: int
    text: str
    x: float
    y: float
    width: float
    height: float
    colored: bool = False


def page_box() -> tuple[float, float, float, float]:
    return _PAGE_BOX


def box_from_pdf(
    left: float,
    bottom: float,
    right: float,
    top: float,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float] | None:
    """Convert a PDF box (origin bottom left) to a top-left page fraction."""
    if page_width <= 0 or page_height <= 0:
        return None
    width = (right - left) / page_width
    height = (top - bottom) / page_height
    if width <= 0.001 or height <= 0.001:
        return None
    x = _clamp(left / page_width)
    y = _clamp((page_height - top) / page_height)
    return (x, y, min(_clamp(width), 1.0 - x), min(_clamp(height), 1.0 - y))


def spans_from_chars(
    page: int,
    chars: list[tuple[str, float, float, float, float]],
    page_width: float,
    page_height: float,
) -> tuple[list[SheetSpan], bool]:
    """Group characters into words. Each char box is in PDF space."""
    words: list[tuple[str, float, float, float, float]] = []
    buffer: list[str] = []
    bounds: list[float] | None = None

    def flush() -> None:
        nonlocal bounds
        if bounds is None:
            buffer.clear()
            return
        text = "".join(buffer).strip()
        buffer.clear()
        box = box_from_pdf(
            bounds[0], bounds[1], bounds[2], bounds[3], page_width, page_height
        )
        bounds = None
        if text and box is not None:
            words.append((text[:_MAX_SPAN_CHARS], *box))

    for text, left, bottom, right, top in chars:
        if not text or text.isspace():
            flush()
            continue
        if bounds is not None and _starts_new_word(bounds, left, bottom, right, top):
            flush()
        if bounds is None:
            bounds = [left, bottom, right, top]
        else:
            bounds[0] = min(bounds[0], left)
            bounds[1] = min(bounds[1], bottom)
            bounds[2] = max(bounds[2], right)
            bounds[3] = max(bounds[3], top)
        buffer.append(text)
    flush()

    truncated = len(words) > _MAX_SPANS_PER_PAGE
    spans = [
        SheetSpan(
            span_id=f"p{page}s{index}",
            page=page,
            text=text,
            x=x,
            y=y,
            width=width,
            height=height,
        )
        for index, (text, x, y, width, height) in enumerate(words[:_MAX_SPANS_PER_PAGE])
    ]
    return spans, truncated


class _PdfTextPage(Protocol):
    def count_chars(self) -> int: ...

    def get_text_range(
        self, index: int = 0, count: int = -1, errors: str = "ignore"
    ) -> str: ...

    def get_charbox(
        self, index: int, loose: bool = False
    ) -> tuple[float, float, float, float]: ...

    def close(self) -> None: ...


class _PdfPage(Protocol):
    def get_size(self) -> tuple[float, float]: ...

    def get_textpage(self) -> _PdfTextPage: ...


def extract_page_spans(
    page: _PdfPage, page_number: int
) -> tuple[list[SheetSpan], bool]:
    """Read word boxes from one pdfium page. A failure returns no spans."""
    width, height = page.get_size()
    textpage = page.get_textpage()
    try:
        chars: list[tuple[str, float, float, float, float]] = []
        count = textpage.count_chars()
        for index in range(count):
            text = textpage.get_text_range(index, 1)
            if not text:
                continue
            left, bottom, right, top = textpage.get_charbox(index)
            chars.append(
                (str(text), float(left), float(bottom), float(right), float(top))
            )
    except Exception:
        logger.warning("Sheet text spans could not be read on page %s", page_number)
        return [], False
    finally:
        textpage.close()
    return spans_from_chars(page_number, chars, float(width), float(height))


def _starts_new_word(
    bounds: list[float], left: float, bottom: float, right: float, top: float
) -> bool:
    char_width = max(right - left, 0.1)
    char_height = max(top - bottom, 0.1)
    gap = left - bounds[2]
    if gap > char_width * 0.6:
        return True
    return bottom < bounds[1] - char_height * 0.5


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _split_text_lines(page: CroppedPage | FilteredPage) -> list[dict[str, Any]]:
    from pdfplumber.utils import extract_text

    lines: list[dict[str, Any]] = []
    for line in page.extract_text_lines(return_chars=True):
        chars = sorted(line["chars"], key=lambda char: char["x0"])
        if not chars:
            continue
        group = [chars[0]]
        for char in chars[1:]:
            previous = group[-1]
            gap = float(char["x0"]) - float(previous["x1"])
            height = max(float(char["height"]), float(previous["height"]))
            if gap > max(3.0, 1.25 * height):
                lines.append(_span_from_group(group, extract_text(group)))
                group = []
            group.append(char)
        lines.append(
            line
            if len(group) == len(chars)
            else _span_from_group(group, extract_text(group))
        )
    return lines


def _span_from_group(chars: list[dict[str, Any]], text: str) -> dict[str, Any]:
    return {
        "text": text,
        "x0": min(char["x0"] for char in chars),
        "x1": max(char["x1"] for char in chars),
        "top": min(char["top"] for char in chars),
        "bottom": max(char["bottom"] for char in chars),
        "chars": chars,
    }


def _is_colored_text(line: dict[str, Any]) -> bool:
    colors = [char.get("non_stroking_color") for char in line.get("chars", [])]
    return bool(colors) and all(
        isinstance(color, (list, tuple))
        and len(color) == 3
        and max(color) - min(color) >= 0.2
        for color in colors
    )


def extract_pdf_spans(
    data: bytes, max_pages: int, *, split_separated_text: bool = False
) -> tuple[list[SheetSpan], list[int]]:
    """Index native text lines with library geometry, including crop and rotation."""
    from io import BytesIO

    import pdfplumber

    spans: list[SheetSpan] = []
    truncated: list[int] = []
    with pdfplumber.open(BytesIO(data), unicode_norm="NFKC") as document:
        for number, page in enumerate(document.pages[:max_pages], 1):
            crop = page.crop(page.cropbox)
            upright = crop.filter(lambda obj: obj.get("upright", True))
            lines = (
                _split_text_lines(upright)
                if split_separated_text
                else upright.extract_text_lines(return_chars=False)
            )
            for positive, direction in ((True, "btt"), (False, "ttb")):
                rotated = crop.filter(
                    lambda obj, positive=positive: (
                        obj.get("object_type") == "char"
                        and not obj.get("upright", True)
                        and (obj["matrix"][1] >= 0) == positive
                    )
                )
                lines.extend(
                    rotated.extract_words(
                        line_dir_rotated="ltr",
                        char_dir_rotated=direction,
                        return_chars=split_separated_text,
                    )
                )
            if len(lines) > _MAX_SPANS_PER_PAGE or any(
                len(str(line["text"])) > 400 for line in lines
            ):
                truncated.append(number)
            for index, line in enumerate(lines[:_MAX_SPANS_PER_PAGE]):
                x, y = (
                    (float(line["x0"]) - crop.bbox[0]) / crop.width,
                    (float(line["top"]) - crop.bbox[1]) / crop.height,
                )
                width, height = (
                    (float(line["x1"]) - float(line["x0"])) / crop.width,
                    (float(line["bottom"]) - float(line["top"])) / crop.height,
                )
                if (
                    min(x, y) < 0
                    or min(width, height) <= 0
                    or x + width > 1.00001
                    or y + height > 1.00001
                ):
                    continue
                spans.append(
                    SheetSpan(
                        span_id=f"p{number}l{index}",
                        page=number,
                        text=str(line["text"])[:400],
                        x=x,
                        y=y,
                        width=width,
                        height=height,
                        colored=_is_colored_text(line),
                    )
                )
    return spans, truncated
