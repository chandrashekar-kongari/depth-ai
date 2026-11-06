"""Conservative, text-only checks. These never measure drawing geometry."""

import re
from typing import TYPE_CHECKING

from onyx.tools.models import CommentVerdict, DrawingComment

if TYPE_CHECKING:
    from onyx.tools.models import CommentReviewResult
    from onyx.tools.tool_implementations.drawing_review.spans import SheetSpan


# Deliberately require the author to name a note and quote both complete lines.
_NOTE_REPLACEMENT = re.compile(
    r'^Replace note "([^"\n]{1,200})" with "([^"\n]{1,200})"\.?$', re.IGNORECASE
)


def verify_note_replacement(
    comment: DrawingComment, original_text: str, revised_text: str
) -> DrawingComment | None:
    match = _NOTE_REPLACEMENT.fullmatch(comment.text.strip())
    if match is None:
        return None
    old, new = match.groups()
    original_lines = [line.strip() for line in original_text.splitlines()]
    revised_lines = [line.strip() for line in revised_text.splitlines()]
    if old == new or original_lines.count(old) != 1:
        return None
    if revised_lines.count(new) == 1 and old not in revised_lines:
        return comment.model_copy(
            update={
                "verdict": CommentVerdict.SOLVED_CORRECT,
                "evidence": f'Native PDF text check on page {comment.page}: exact note "{new}" is present; old note is absent. This verifies text only.',
                "remaining": "Engineer confirmation is required.",
                "revised_page": comment.page,
                "revised_page_level": True,
            }
        )
    if revised_lines.count(old) == 1 and new not in revised_lines:
        return comment.model_copy(
            update={
                "verdict": CommentVerdict.OPEN,
                "evidence": f'Native PDF text check on page {comment.page}: old note "{old}" remains.',
                "remaining": f'Replace the note with "{new}".',
                "revised_page": comment.page,
                "revised_page_level": True,
            }
        )
    return None


def has_verbatim_evidence(evidence: str, page_text: str) -> bool:
    """Normalize layout whitespace, while retaining signs, units and numeric values."""
    excerpt = " ".join(evidence.strip().strip('"').split())
    source = " ".join(page_text.split())
    if len(excerpt) < 6:
        return False
    for match in re.finditer(re.escape(excerpt), source):
        before = source[match.start() - 1] if match.start() else ""
        after = source[match.end()] if match.end() < len(source) else ""
        if before and before.isalnum() and excerpt[0].isalnum():
            continue
        if after and after.isalnum() and excerpt[-1].isalnum():
            continue
        return True
    return False


def ground_review_highlights(
    result: "CommentReviewResult", spans: list["SheetSpan"]
) -> "CommentReviewResult":
    """A model span ID cannot establish a precise highlight without matching text."""
    from onyx.tools.models import DrawingMarkBox

    by_id = {span.span_id: span for span in spans}
    comments: list[DrawingComment] = []
    for comment in result.comments:
        span = by_id.get(comment.revised_span_id or "")
        if comment.revised_span_id and (
            span is None
            or span.page != comment.revised_page
            or not has_verbatim_evidence(span.text, comment.evidence)
        ):
            comment = comment.model_copy(
                update={
                    "revised_span_id": None,
                    "revised_box": DrawingMarkBox(x=0, y=0, width=1, height=1),
                    "revised_page_level": True,
                }
            )
        comments.append(comment)
    return result.model_copy(update={"comments": comments})
