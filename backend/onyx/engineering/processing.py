"""Bounded private PDF review; native annotations precede vision extraction."""

import re
from io import BytesIO
from math import hypot
from uuid import UUID

from onyx.engineering.bracket_dimensions import Axis, Bracket
from onyx.engineering.checks import ground_review_highlights, verify_note_replacement
from onyx.engineering.drawing_changes import load_drawing_evidence
from onyx.llm.interfaces import LLM
from onyx.tools.models import CommentReviewResult, DrawingComment, DrawingMarkBox
from onyx.tools.tool_implementations.drawing_review.comment_queue import (
    ExtractedComment,
)
from onyx.tools.tool_implementations.drawing_review.comment_review import (
    verify_sheet_comments,
)
from onyx.tools.tool_implementations.drawing_review.sheet import (
    MAX_SHEET_PAGES,
    _sheet_pages,
)
from onyx.utils.process_isolation import run_in_isolated_process


class ReviewInputError(ValueError):
    pass


def _annotation_box(
    rect: tuple[float, float, float, float],
    crop: tuple[float, float, float, float],
    rotation: int,
) -> DrawingMarkBox | None:
    left, bottom, right, top = crop
    if left >= right or bottom >= top:
        return None
    x0, y0, x1, y1 = rect
    points = [
        ((x0 - left) / (right - left), (top - y1) / (top - bottom)),
        ((x1 - left) / (right - left), (top - y0) / (top - bottom)),
    ]
    if rotation == 90:
        points = [(1 - y, x) for x, y in points]
    elif rotation == 180:
        points = [(1 - x, 1 - y) for x, y in points]
    elif rotation == 270:
        points = [(y, 1 - x) for x, y in points]
    x = max(0, min(px for px, _ in points))
    y = max(0, min(py for _, py in points))
    width = min(1, max(px for px, _ in points)) - x
    height = min(1, max(py for _, py in points)) - y
    if width <= 0 or height <= 0:
        return None
    return DrawingMarkBox(x=x, y=y, width=width, height=height)


def _near_mark(text: DrawingMarkBox, circle: DrawingMarkBox) -> bool:
    x_gap = max(0.0, text.x - circle.x - circle.width, circle.x - text.x - text.width)
    y_gap = max(0.0, text.y - circle.y - circle.height, circle.y - text.y - text.height)
    return 0 < hypot(x_gap, y_gap) <= 0.025


def _numbered_brackets(
    lines: list[DrawingMarkBox], number: DrawingMarkBox
) -> list[Bracket]:
    if len(lines) > 128:
        return []
    brackets: list[Bracket] = []
    for spine in lines:
        if not _near_mark(number, spine):
            continue
        axis: Axis = "vertical" if spine.height > spine.width else "horizontal"
        vertical = axis == "vertical"
        start, length = (spine.y, spine.height) if vertical else (spine.x, spine.width)
        cross, depth = (spine.x, spine.width) if vertical else (spine.y, spine.height)
        number_center = (
            number.y + number.height / 2 if vertical else number.x + number.width / 2
        )
        if (
            length < 0.035
            or length < depth * 4
            or not start <= number_center <= start + length
        ):
            continue
        tips: list[tuple[float, float]] = []
        for point in (start, start + length):
            options = []
            for cap in lines:
                if cap is spine:
                    continue
                along, thickness = (
                    (cap.y, cap.height) if vertical else (cap.x, cap.width)
                )
                across, width = (cap.x, cap.width) if vertical else (cap.y, cap.height)
                if abs(along + thickness / 2 - point) > 0.012 or width <= thickness:
                    continue
                if (
                    not across <= cross + depth + 0.005
                    or across + width < cross - 0.005
                ):
                    continue
                center = cross + depth / 2
                tip = max(
                    (across, across + width), key=lambda value: abs(value - center)
                )
                if abs(tip - center) > 0.035:
                    continue
                options.append(
                    (tip, along + thickness / 2)
                    if vertical
                    else (along + thickness / 2, tip)
                )
            if len(options) != 1:
                break
            tips.append(options[0])
        if len(tips) == 2:
            across_axis = 0 if vertical else 1
            center = cross + depth / 2
            if (tips[0][across_axis] - center) * (tips[1][across_axis] - center) > 0:
                brackets.append(Bracket(axis=axis, tips=(tips[0], tips[1])))
    return brackets


def pdf_comments(
    data: bytes, *, allow_partial: bool = False
) -> tuple[int, dict[int, list[ExtractedComment]]]:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted:
        raise ReviewInputError("Password-protected PDFs are not supported")
    count = len(reader.pages)
    if count < 1 or (count > MAX_SHEET_PAGES and not allow_partial):
        raise ReviewInputError(
            f"Each PDF must contain 1–{MAX_SHEET_PAGES} pages. No pages were silently skipped."
        )
    comments: dict[int, list[ExtractedComment]] = {}
    for index, page in enumerate(reader.pages[:MAX_SHEET_PAGES], 1):
        found: list[ExtractedComment] = []
        numbers: dict[int, DrawingMarkBox] = {}
        circles: list[DrawingMarkBox] = []
        lines: list[DrawingMarkBox] = []
        crop = tuple(float(page.cropbox[i]) for i in range(4))
        rotation = int(page.rotation) % 360
        for reference in page.get("/Annots", []):
            annotation = reference.get_object()
            if annotation.get("/Subtype") in {"/Popup", "/Link", "/Widget"}:
                continue
            content = str(annotation.get("/Contents", "")).strip()
            rect = annotation.get("/Rect")
            box = (
                _annotation_box(
                    (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])),
                    (crop[0], crop[1], crop[2], crop[3]),
                    rotation,
                )
                if rect and len(rect) == 4
                else None
            )
            if (
                not content
                and box is not None
                and annotation.get("/Subtype") == "/Circle"
            ):
                circles.append(box)
            if (
                not content
                and box is not None
                and annotation.get("/Subtype") == "/Line"
            ):
                lines.append(box)
            if content:
                if len(found) >= 40:
                    raise ReviewInputError(
                        "A page has more than 40 comments. Split this review into smaller packages."
                    )
                if len(content) > 4000:
                    raise ReviewInputError(
                        "A PDF comment exceeds the supported text length"
                    )
                if (
                    box is not None
                    and annotation.get("/Subtype") == "/FreeText"
                    and re.fullmatch(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)", content)
                ):
                    numbers[len(found)] = box
                found.append(ExtractedComment(text=content, request=content, box=box))
        for mark_index, number in numbers.items():
            nearby = [circle for circle in circles if _near_mark(number, circle)]
            if not nearby:
                brackets = _numbered_brackets(lines, number)
                if (
                    len(brackets) == 1
                    and sum(
                        brackets[0] in _numbered_brackets(lines, other)
                        for other in numbers.values()
                    )
                    == 1
                ):
                    found[mark_index] = found[mark_index].model_copy(
                        update={
                            "bracket": brackets[0],
                            "requested_value": found[mark_index].text,
                        }
                    )
                continue
            if len(nearby) != 1:
                continue
            circle = nearby[0]
            if sum(_near_mark(other, circle) for other in numbers.values()) == 1:
                found[mark_index] = found[mark_index].model_copy(
                    update={
                        "target_box": circle,
                        "requested_value": found[mark_index].text,
                    }
                )
        if found:
            comments[index] = found
    return count, comments


def process_pair(
    original: bytes,
    revised: bytes,
    original_name: str,
    revised_name: str,
    review_id: UUID,
    llm: LLM | None,
) -> CommentReviewResult:
    if original == revised:
        raise ReviewInputError(
            "Original and revised PDFs are identical. Upload the revised drawing."
        )
    old = _sheet_pages(original, original_name, draw_annotations=True)
    new = _sheet_pages(revised, revised_name)
    if old.error or new.error:
        raise ReviewInputError("A PDF could not be read or rendered")
    original = old.recovered_pdf or original
    revised = new.recovered_pdf or revised
    old_count, native = run_in_isolated_process(pdf_comments, original, timeout=60)
    new_count, _ = run_in_isolated_process(pdf_comments, revised, timeout=60)
    if old_count != new_count:
        raise ReviewInputError(
            "Sheet counts differ. This pilot requires matching page order and equal page counts."
        )
    original_text = run_in_isolated_process(pdf_texts, original, timeout=60)
    revised_text = run_in_isolated_process(pdf_texts, revised, timeout=60)

    def exact_verifier(comment: DrawingComment) -> DrawingComment | None:
        return verify_note_replacement(
            comment,
            original_text.get(comment.page, ""),
            revised_text.get(comment.page, ""),
        )

    result = verify_sheet_comments(
        old,
        new,
        commented_name=original_name,
        revised_name=revised_name,
        exact_verifier=exact_verifier,
        drawing_evidence=load_drawing_evidence(original, revised),
        revised_text_by_page=revised_text,
        include_extra_issues=False,
        dxf_summary=None,
        llm=llm,
        native_comments=native,
        original_pdf=original,
        commented_sheet_file_id=f"{review_id}/original",
        revised_sheet_file_id=f"{review_id}/revised",
    )

    result = ground_review_highlights(result, new.spans)
    coverage = "Pilot scope: confirmed page order; native annotations take priority. Text checks do not verify geometry. Independent PDF changes have separate coverage and evidence. Flattened markup may appear as a visual change. All findings require engineer decisions."
    return result.model_copy(
        update={"status": coverage, "report": coverage + "\n\n" + result.report}
    )


def pdf_texts(data: bytes) -> dict[int, str]:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    return {
        index: (page.extract_text() or "") for index, page in enumerate(reader.pages, 1)
    }
