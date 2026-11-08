"""Bounded private PDF review; native annotations precede vision extraction."""

from io import BytesIO
from uuid import UUID

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


def pdf_comments(data: bytes) -> tuple[int, dict[int, list[ExtractedComment]]]:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted:
        raise ReviewInputError("Password-protected PDFs are not supported")
    count = len(reader.pages)
    if count < 1 or count > MAX_SHEET_PAGES:
        raise ReviewInputError(
            f"Each PDF must contain 1–{MAX_SHEET_PAGES} pages. No pages were silently skipped."
        )
    comments: dict[int, list[ExtractedComment]] = {}
    for index, page in enumerate(reader.pages, 1):
        found: list[ExtractedComment] = []
        for reference in page.get("/Annots", []):
            annotation = reference.get_object()
            if annotation.get("/Subtype") in {"/Popup", "/Link", "/Widget"}:
                continue
            content = str(annotation.get("/Contents", "")).strip()
            if content:
                if len(found) >= 40:
                    raise ReviewInputError(
                        "A page has more than 40 comments. Split this review into smaller packages."
                    )
                if len(content) > 4000:
                    raise ReviewInputError(
                        "A PDF comment exceeds the supported text length"
                    )
                box = None
                rect = annotation.get("/Rect")
                if rect and len(rect) == 4:
                    left, bottom, right, top = (float(value) for value in page.cropbox)
                    width, height = right - left, top - bottom
                    x0, y0, x1, y1 = (float(value) for value in rect)
                    points = [
                        ((x0 - left) / width, (top - y1) / height),
                        ((x1 - left) / width, (top - y0) / height),
                    ]
                    rotation = int(page.rotation) % 360
                    if rotation == 90:
                        points = [(1 - y, x) for x, y in points]
                    elif rotation == 180:
                        points = [(1 - x, 1 - y) for x, y in points]
                    elif rotation == 270:
                        points = [(y, 1 - x) for x, y in points]
                    bx, by = (
                        max(0, min(p[0] for p in points)),
                        max(0, min(p[1] for p in points)),
                    )
                    bw, bh = (
                        min(1, max(p[0] for p in points)) - bx,
                        min(1, max(p[1] for p in points)) - by,
                    )
                    if bw > 0 and bh > 0:
                        box = DrawingMarkBox(x=bx, y=by, width=bw, height=bh)
                found.append(ExtractedComment(text=content, request=content, box=box))
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
    old_count, native = run_in_isolated_process(pdf_comments, original, timeout=60)
    new_count, _ = run_in_isolated_process(pdf_comments, revised, timeout=60)
    if old_count != new_count:
        raise ReviewInputError(
            "Sheet counts differ. This pilot requires matching page order and equal page counts."
        )
    old = _sheet_pages(original, original_name)
    new = _sheet_pages(revised, revised_name)
    if old.error or new.error:
        raise ReviewInputError("A PDF could not be rendered")
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
