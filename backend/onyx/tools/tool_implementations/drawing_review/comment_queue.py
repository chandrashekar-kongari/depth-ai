"""Turn review comments into a queue of verdicts.

A number in a comment is not a measurement. The DXF section stays separate.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, ValidationError

from onyx.tools.models import (
    CommentReviewResult,
    CommentVerdict,
    DrawingComment,
    DrawingExtraIssue,
    DrawingMarkBox,
)
from onyx.tools.tool_implementations.drawing_review.spans import SheetSpan, page_box

_MAX_COMMENTS_PER_PAGE = 40
_MAX_EXTRA_ISSUES = 8
_NO_DXF = "No optional DXF was attached. CAD geometry measurements were not checked. PDF comment verification does not require DXF."
_NOT_A_MEASUREMENT = "Comment text is not a measurement."

_EXTRACT_PROMPT = """
You read review comments on one page of a mechanical drawing.
Comments are clouds, balloons, redlines, and notes.
Return JSON only. The shape is {"comments":[...]}.
Each comment has text, request, and span_id.
text is the comment as written.
request is the change the comment asks for.
span_id is an id from the span list, or null.
A number in a comment is not a measurement.
Do not invent a comment.
The review does not certify the drawing.
""".strip()

_VERDICT_PROMPT = """
You check one review comment against the new drawing page.
Return JSON only. The shape is {"status","evidence","remaining","span_id"}.
status is open, solved_correct, solved_incorrect, or unclear.
open: the new page does not show the requested change. remaining says what must change.
solved_correct: the new page shows the requested change and the change matches the comment.
solved_incorrect: the new page changed that area, but the change does not match the comment. remaining says what is wrong.
unclear: the page does not show enough to decide.
evidence is visible text on the new page.
span_id is an id from the new page span list, or null.
A number in the comment is not a measurement.
If a DXF measured section is present, use a DXF dimension entity for a dimension.
Do not replace a DXF dimension entity with sheet text.
Do not claim the drawing meets ASME, ISO, or a company standard.
The review does not certify the drawing.
""".strip()

_EXTRA_PROMPT = """
You list problems on this new drawing page that the comments do not ask for.
Return JSON only. The shape is {"issues":[...]}.
Each issue has title, detail, and span_id.
Keep the list short. Return no issues when the page has none.
Do not repeat a comment.
A number on the sheet is visible text, not a measurement.
Do not claim the drawing meets ASME, ISO, or a company standard.
The review does not certify the drawing.
""".strip()


class ExtractedComment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    request: str = ""
    span_id: str | None = None
    box: DrawingMarkBox | None = None


class VerdictDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: CommentVerdict
    evidence: str = ""
    remaining: str = ""
    span_id: str | None = None


class ExtraIssueDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    detail: str = ""
    span_id: str | None = None


def extract_prompt() -> str:
    return _EXTRACT_PROMPT


def verdict_prompt() -> str:
    return _VERDICT_PROMPT


def extra_prompt() -> str:
    return _EXTRA_PROMPT


def parse_json_object(text: str) -> dict[str, object]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        fence = raw.rfind("```")
        if fence >= 0:
            raw = raw[:fence]
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Comment JSON is missing.")
    payload = json.loads(raw[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Comment JSON is missing.")
    return payload


def parse_extracted_comments(text: str) -> list[ExtractedComment]:
    raw_items = parse_json_object(text).get("comments", [])
    if not isinstance(raw_items, list):
        raise ValueError("Comment JSON is missing.")
    items: list[ExtractedComment] = []
    for raw_item in raw_items:
        try:
            item = ExtractedComment.model_validate(raw_item)
        except ValidationError:
            continue
        if item.text.strip():
            items.append(item)
    return items


def parse_verdict(text: str) -> VerdictDraft:
    return VerdictDraft.model_validate(parse_json_object(text))


def parse_extra_issues(text: str) -> list[ExtraIssueDraft]:
    raw_items = parse_json_object(text).get("issues", [])
    if not isinstance(raw_items, list):
        raise ValueError("Comment JSON is missing.")
    items: list[ExtraIssueDraft] = []
    for raw_item in raw_items:
        try:
            item = ExtraIssueDraft.model_validate(raw_item)
        except ValidationError:
            continue
        if item.title.strip():
            items.append(item)
    return items


def comment_from_extraction(
    item: ExtractedComment,
    *,
    comment_id: str,
    page: int,
    spans: dict[str, SheetSpan],
) -> DrawingComment:
    box, page_level, span_id = _mark(item.span_id, spans, page)
    if item.box is not None:
        box, page_level = item.box, False
    request = item.request.strip() or item.text.strip()
    return DrawingComment(
        id=comment_id,
        page=page,
        text=item.text.strip()[:400],
        request=request[:400],
        verdict=CommentVerdict.UNCLEAR,
        evidence="visible text: none",
        remaining="This comment was not checked.",
        span_id=span_id,
        box=box,
        page_level=page_level,
    )


def unclear_comment(
    *,
    comment_id: str,
    page: int,
    text: str,
    request: str,
    remaining: str,
    spans: dict[str, SheetSpan] | None = None,
    span_id: str | None = None,
) -> DrawingComment:
    box, page_level, resolved = _mark(span_id, spans or {}, page)
    return DrawingComment(
        id=comment_id,
        page=page,
        text=text[:400],
        request=request[:400],
        verdict=CommentVerdict.UNCLEAR,
        evidence="visible text: none",
        remaining=remaining[:400],
        span_id=resolved,
        box=box,
        page_level=page_level,
    )


def paired_page(
    page: int, revised_page_count: int, reviewed_revised_pages: int
) -> int | None:
    """Return the new-sheet page, or None when that page was not reviewed."""
    if page < 1 or page > revised_page_count or page > reviewed_revised_pages:
        return None
    return page


def apply_verdict(
    comment: DrawingComment,
    draft: VerdictDraft,
    revised_spans: dict[str, SheetSpan],
    *,
    revised_page: int,
    dxf_attached: bool,
) -> DrawingComment:
    remaining = draft.remaining.strip()
    if draft.status is CommentVerdict.OPEN and not remaining:
        remaining = "The requested change is not on the new sheet."
    elif draft.status is CommentVerdict.SOLVED_INCORRECT and not remaining:
        remaining = "The change does not match the comment."
    elif draft.status is CommentVerdict.UNCLEAR and not remaining:
        remaining = "The pages do not show enough to decide."
    box, page_level, span_id = _mark(draft.span_id, revised_spans, revised_page)
    return comment.model_copy(
        update={
            "verdict": draft.status,
            "evidence": label_comment_evidence(
                draft.evidence, dxf_attached=dxf_attached
            ),
            "remaining": remaining[:400],
            "revised_page": revised_page,
            "revised_span_id": span_id,
            "revised_box": box,
            "revised_page_level": page_level,
        }
    )


def extra_issue_from_draft(
    item: ExtraIssueDraft,
    *,
    issue_id: str,
    page: int,
    spans: dict[str, SheetSpan],
) -> DrawingExtraIssue:
    box, page_level, span_id = _mark(item.span_id, spans, page)
    return DrawingExtraIssue(
        id=issue_id,
        page=page,
        title=item.title.strip()[:160],
        detail=item.detail.strip()[:400],
        span_id=span_id,
        box=box,
        page_level=page_level,
    )


def label_comment_evidence(evidence: str, *, dxf_attached: bool) -> str:
    """Keep comment and sheet text out of the measured section."""
    text = evidence.strip() or "none"
    if dxf_attached and text.startswith("DXF dimension"):
        return text[:300]
    if text.lower().startswith("visible text"):
        return text[:300]
    return f"visible text: {text}"[:300]


def take_page_comments(
    items: list[ExtractedComment],
) -> tuple[list[ExtractedComment], bool]:
    if len(items) <= _MAX_COMMENTS_PER_PAGE:
        return items, False
    return items[:_MAX_COMMENTS_PER_PAGE], True


def cap_extra_issues(issues: list[DrawingExtraIssue]) -> list[DrawingExtraIssue]:
    return issues[:_MAX_EXTRA_ISSUES]


def format_comment_report(
    comments: list[DrawingComment],
    extra_issues: list[DrawingExtraIssue],
    *,
    commented_name: str,
    revised_name: str,
    dxf_summary: str | None,
    skipped_note: str | None,
) -> str:
    lines = [
        "## comments",
        f"Marked sheet: {commented_name}",
        f"New sheet: {revised_name}",
        _NOT_A_MEASUREMENT,
        "The review does not certify the drawing.",
    ]
    if skipped_note:
        lines.append(skipped_note)
    if not comments:
        lines.append("No comments were checked.")
    else:
        lines.append("### queue")
        lines.extend(
            f"- {item.id} {item.verdict.value}: {item.text} "
            f"Request: {item.request} Evidence: {item.evidence}. "
            f"Remaining: {item.remaining} Page {item.page}."
            for item in comments
        )
    if extra_issues:
        lines.append("### other issues")
        lines.extend(
            f"- {item.id}: {item.title} {item.detail} Page {item.page}."
            for item in extra_issues
        )
    lines.append("## measured")
    lines.append(dxf_summary.strip() if dxf_summary else _NO_DXF)
    return "\n".join(lines)


def empty_result(
    *,
    status: str,
    report: str,
    commented_sheet_file_id: str | None,
    commented_sheet_filename: str | None,
    revised_sheet_file_id: str | None,
    revised_sheet_filename: str | None,
    commented_page_count: int = 0,
    revised_page_count: int = 0,
) -> CommentReviewResult:
    return CommentReviewResult(
        status=status,
        report=report,
        commented_sheet_file_id=commented_sheet_file_id,
        commented_sheet_filename=commented_sheet_filename,
        revised_sheet_file_id=revised_sheet_file_id,
        revised_sheet_filename=revised_sheet_filename,
        commented_page_count=commented_page_count,
        revised_page_count=revised_page_count,
    )


def _mark(
    span_id: str | None,
    spans: dict[str, SheetSpan],
    page: int,
) -> tuple[DrawingMarkBox, bool, str | None]:
    raw_id = span_id.strip() if span_id else None
    span = spans.get(raw_id) if raw_id else None
    if span is None or span.page != page:
        x, y, width, height = page_box()
        return DrawingMarkBox(x=x, y=y, width=width, height=height), True, None
    return (
        DrawingMarkBox(x=span.x, y=span.y, width=span.width, height=span.height),
        False,
        span.span_id,
    )
