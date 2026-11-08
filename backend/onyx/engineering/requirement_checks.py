"""Verify scoped requirements against shared source evidence."""

from __future__ import annotations

import re
from decimal import Decimal

from onyx.engineering.checks import verify_note_replacement
from onyx.engineering.drawing_changes import DrawingEvidence
from onyx.tools.models import (
    CommentVerdict,
    DrawingComment,
    DrawingMarkBox,
    DrawingRequirementCheck,
)
from onyx.tools.tool_implementations.drawing_review.comment_queue import (
    ExtractedComment,
)
from onyx.tools.tool_implementations.drawing_review.spans import SheetSpan

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)")
_FIELDS = re.compile(
    r"(?i)^(?:add|fill|complete|fix)\s+(?:the\s+)?(?:missing|required)\s+fields\s*:\s*(.+)$"
)
_REQUIRED_FIELDS = re.compile(r"(?i)^required fields\s*:\s*(.+)$")
_VAGUE = re.compile(
    r"(?i)^(?:update|missing|missed|fix missing|fix missed|fix the missing items)[.!]?$"
)


def _covers(box: DrawingMarkBox, target: DrawingMarkBox) -> bool:
    if target.width <= 0 or target.height <= 0:
        return False
    x = max(0, min(box.x + box.width, target.x + target.width) - max(box.x, target.x))
    y = max(0, min(box.y + box.height, target.y + target.height) - max(box.y, target.y))
    return x * y >= target.width * target.height * 0.6


def _span_box(span: SheetSpan) -> DrawingMarkBox:
    return DrawingMarkBox(x=span.x, y=span.y, width=span.width, height=span.height)


def _verify_bracket(
    row: DrawingComment,
    item: ExtractedComment,
    evidence: DrawingEvidence,
    expected: str,
) -> DrawingComment | None:
    if (
        item.bracket is None
        or item.requested_value != expected
        or not _NUMBER.fullmatch(expected)
        or row.box is None
    ):
        return None
    mark = row.box
    matches = [
        dimension
        for dimension in evidence.added_dimensions
        if dimension.page == row.page
        and abs(dimension.original_box.x - mark.x) <= 0.04
        and abs(dimension.original_box.y - mark.y) <= 0.04
        and dimension.extensions.matches(
            item.bracket,
            dimension.revised_box.x - dimension.original_box.x,
            dimension.revised_box.y - dimension.original_box.y,
        )
    ]
    if len(matches) != 1:
        return None
    dimension = matches[0]
    correct = Decimal(dimension.value) == Decimal(expected)
    return row.model_copy(
        update={
            "request": f"Set the bracketed {item.bracket.axis} dimension to {expected}.",
            "verdict": CommentVerdict.SOLVED_CORRECT
            if correct
            else CommentVerdict.OPEN,
            "evidence": f"The revised dimension spans the marked endpoints and reads {dimension.value}.",
            "remaining": ""
            if correct
            else f"The bracket requests {expected}. The revised dimension reads {dimension.value}.",
            "revised_page": row.page,
            "revised_box": dimension.revised_box,
        }
    )


def verify_grounded_request(
    row: DrawingComment,
    item: ExtractedComment,
    evidence: DrawingEvidence,
    original_spans: list[SheetSpan],
    revised_spans: list[SheetSpan],
    user_request: str,
) -> DrawingComment | None:
    note = verify_note_replacement(
        row,
        "\n".join(span.text for span in original_spans),
        "\n".join(span.text for span in revised_spans),
    )
    if note is not None:
        return note
    expected = (item.requested_value or item.text).strip()
    if _NUMBER.fullmatch(item.text.strip()) and item.text.strip() != expected:
        return None
    bracket_result = _verify_bracket(row, item, evidence, expected)
    if bracket_result is not None:
        return bracket_result
    target_box = item.target_box or (row.box if not row.page_level else None)
    if (
        (item.target_box is not None or not item.ambiguity)
        and len(expected) <= 96
        and _NUMBER.fullmatch(expected)
        and expected in _NUMBER.findall(item.text)
        and target_box is not None
    ):
        candidates = [
            match
            for match in evidence.callouts
            if match.page == row.page and _covers(target_box, match.original_box)
        ]
        marked_labels = [
            box
            for box in evidence.original_labels.get(row.page, [])
            if _covers(target_box, box)
        ]
        if len(candidates) == 1 and marked_labels == [candidates[0].original_box]:
            match = candidates[0]
            if _NUMBER.fullmatch(match.original_text) and _NUMBER.fullmatch(
                match.revised_text
            ):
                correct = Decimal(match.revised_text) == Decimal(expected)
                changed = Decimal(match.original_text) != Decimal(match.revised_text)
                verdict = (
                    CommentVerdict.SOLVED_CORRECT
                    if correct
                    else (
                        CommentVerdict.SOLVED_INCORRECT
                        if changed
                        else CommentVerdict.OPEN
                    )
                )
                links = (
                    [
                        change.id
                        for change in evidence.comparison.changes
                        if change.page == row.page
                        and change.kind == "text_changed"
                        and change.original_box == match.original_box
                        and change.revised_box == match.revised_box
                    ]
                    if correct
                    else []
                )
                return row.model_copy(
                    update={
                        "verdict": verdict,
                        "request": (
                            f"Change the marked dimension from {match.original_text} to {expected}."
                            if item.target_box is not None
                            else row.request
                        ),
                        "evidence": f"Requested {expected}. Found {match.revised_text} on the corresponding dimension (original: {match.original_text}).",
                        "remaining": ""
                        if correct
                        else f"The reviewer requested {expected}. The matching dimension on the revised sheet shows {match.revised_text}.",
                        "revised_page": row.page,
                        "revised_box": match.revised_box,
                        "revised_location_verified": True,
                        "verified_change_ids": links,
                    }
                )

    explicit = _FIELDS.fullmatch(item.text.strip())
    vague = _VAGUE.fullmatch(item.text.strip())
    # Scope comes from original evidence or the user's checklist, never from revised additions.
    checklist = explicit
    if vague and row.box and not row.page_level:
        checklist = _FIELDS.fullmatch(user_request.strip())
        if checklist is None:
            declarations = [
                match
                for span in original_spans
                if span.page == row.page
                and _covers(row.box, _span_box(span))
                and (match := _REQUIRED_FIELDS.fullmatch(span.text.strip()))
            ]
            if len(declarations) == 1:
                checklist = declarations[0]
    if checklist:
        fields = {}
        for entry in re.split(r"[,;]", checklist[1]):
            name, separator, value = entry.partition("=")
            name, value = name.strip(), value.strip()
            if (
                not re.fullmatch(r"[\w /-]{1,64}", name)
                or (separator and not value)
                or name.casefold() in fields
            ):
                return None
            fields[name.casefold()] = (name, value)
        if 1 <= len(fields) <= 20:
            checks = [
                _check_field(
                    name,
                    value,
                    row,
                    original_spans,
                    revised_spans,
                    scoped=explicit is None,
                )
                for name, value in fields.values()
            ]
            passed = sum(
                check.verdict == CommentVerdict.SOLVED_CORRECT for check in checks
            )
            verdict = (
                CommentVerdict.SOLVED_CORRECT
                if passed == len(checks)
                else (
                    CommentVerdict.OPEN
                    if any(
                        check.verdict
                        in {CommentVerdict.OPEN, CommentVerdict.SOLVED_INCORRECT}
                        for check in checks
                    )
                    else CommentVerdict.UNCLEAR
                )
            )
            return row.model_copy(
                update={
                    "verdict": verdict,
                    "checks": checks,
                    "evidence": f"{passed} of {len(checks)} required fields verified.",
                    "remaining": " ".join(
                        f"{check.label}: {check.evidence}"
                        for check in checks
                        if check.verdict != CommentVerdict.SOLVED_CORRECT
                    ),
                    "revised_page": row.page,
                    "revised_page_level": True,
                }
            )
    # An unresolved structured check leaves the paired visual check available.
    return None


def _check_field(
    name: str,
    expected: str,
    row: DrawingComment,
    original: list[SheetSpan],
    revised: list[SheetSpan],
    *,
    scoped: bool,
) -> DrawingRequirementCheck:
    pattern = re.compile(rf"^\s*{re.escape(name)}\s*:\s*(.*?)\s*$", re.IGNORECASE)
    old_matches = [
        span
        for span in original
        if span.page == row.page
        and pattern.fullmatch(span.text)
        and (not scoped or (row.box is not None and _covers(row.box, _span_box(span))))
    ]
    if len(old_matches) > 1 or (scoped and not old_matches):
        return DrawingRequirementCheck(
            label=name,
            verdict=CommentVerdict.UNCLEAR,
            evidence="The marked field could not be uniquely identified.",
        )
    matches = [
        (span, match)
        for span in revised
        if span.page == row.page and (match := pattern.fullmatch(span.text))
    ]
    if len(matches) != 1:
        return DrawingRequirementCheck(
            label=name,
            verdict=CommentVerdict.UNCLEAR,
            evidence="No unique revised field was verified.",
        )
    if old_matches:
        old = old_matches[0]
        new = matches[0][0]
        # Without a qualified table matcher, a scoped field must stay at its local position.
        if abs(old.x - new.x) > 0.015 or abs(old.y - new.y) > 0.015:
            return DrawingRequirementCheck(
                label=name,
                verdict=CommentVerdict.UNCLEAR,
                evidence="The revised field could not be matched to the marked location.",
            )
    value = matches[0][1][1].strip()
    if not value or re.fullmatch(r"[-–—]+", value):
        return DrawingRequirementCheck(
            label=name,
            verdict=CommentVerdict.OPEN,
            evidence="The revised field is blank.",
        )
    if expected and " ".join(value.split()) != " ".join(expected.split()):
        return DrawingRequirementCheck(
            label=name,
            verdict=CommentVerdict.SOLVED_INCORRECT,
            evidence=f"Expected {expected}. Found {value}.",
        )
    return DrawingRequirementCheck(
        label=name,
        verdict=CommentVerdict.SOLVED_CORRECT,
        evidence=f"Revised field: {value}",
    )
