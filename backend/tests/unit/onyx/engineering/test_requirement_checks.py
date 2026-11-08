from onyx.engineering.drawing_changes import DrawingEvidence, MatchedCallout
from onyx.engineering.requirement_checks import verify_grounded_request
from onyx.tools.models import (
    CommentVerdict,
    DrawingChange,
    DrawingChangeReview,
    DrawingComment,
    DrawingMarkBox,
)
from onyx.tools.tool_implementations.drawing_review.comment_queue import (
    ExtractedComment,
)
from onyx.tools.tool_implementations.drawing_review.spans import SheetSpan


def box(x: float) -> DrawingMarkBox:
    return DrawingMarkBox(x=x, y=0.2, width=0.1, height=0.04)


def comment(text: str) -> DrawingComment:
    return DrawingComment(
        id="c1",
        page=1,
        text=text,
        request=text,
        verdict=CommentVerdict.UNCLEAR,
        evidence="",
        remaining="",
        box=box(0.2),
    )


def test_uses_marked_dimension_even_when_requested_value_exists_elsewhere() -> None:
    match = MatchedCallout(
        page=1,
        original_text="500",
        revised_text="200",
        original_box=box(0.2),
        revised_box=box(0.3),
    )
    other = match.model_copy(update={"original_box": box(0.6), "revised_box": box(0.7)})
    change = DrawingChange(
        id="dc1",
        page=1,
        kind="text_changed",
        before_text="500",
        after_text="200",
        original_box=match.original_box,
        revised_box=match.revised_box,
    )
    evidence = DrawingEvidence(
        comparison=DrawingChangeReview(status="complete", changes=[change]),
        callouts=[match, other],
        original_labels={1: [match.original_box, other.original_box]},
    )
    item = ExtractedComment(text="200")
    result = verify_grounded_request(comment("200"), item, evidence, [], [], "")
    assert result is not None
    assert result.verdict == CommentVerdict.SOLVED_CORRECT
    assert result.verified_change_ids == ["dc1"]

    evidence.callouts[0] = match.model_copy(update={"revised_text": "190"})
    wrong = verify_grounded_request(comment("200"), item, evidence, [], [], "")
    assert wrong is not None
    assert wrong.verdict == CommentVerdict.SOLVED_INCORRECT
    assert wrong.verified_change_ids == []


def test_grouped_request_requires_all_fields_and_checks_explicit_expected_values() -> (
    None
):
    text = "Add missing fields: Material, Finish=Anodized"
    row = comment(text)
    item = ExtractedComment(text=text)
    evidence = DrawingEvidence(comparison=DrawingChangeReview(status="complete"))
    material = SheetSpan("material", 1, "Material: Aluminum", 0.1, 0.1, 0.2, 0.04)
    finish = SheetSpan("finish", 1, "Finish: Painted", 0.1, 0.2, 0.2, 0.04)
    result = verify_grounded_request(row, item, evidence, [], [material, finish], "")
    assert result is not None
    assert result.verdict == CommentVerdict.OPEN
    assert [check.verdict for check in result.checks] == [
        CommentVerdict.SOLVED_CORRECT,
        CommentVerdict.SOLVED_INCORRECT,
    ]

    vague = verify_grounded_request(
        comment("fix missed"),
        ExtractedComment(text="fix missed"),
        evidence,
        [],
        [material, finish],
        "",
    )
    assert vague is None


def test_fix_missed_checks_scoped_original_field_list() -> None:
    evidence = DrawingEvidence(comparison=DrawingChangeReview(status="complete"))
    row = comment("fix missed").model_copy(
        update={
            "box": DrawingMarkBox(x=0.1, y=0.1, width=0.5, height=0.4),
        }
    )
    original = [
        SheetSpan(
            "required", 1, "Required fields: Material, Finish", 0.2, 0.15, 0.2, 0.03
        ),
        SheetSpan("material", 1, "Material:", 0.2, 0.2, 0.1, 0.03),
        SheetSpan("finish", 1, "Finish:", 0.2, 0.25, 0.1, 0.03),
    ]
    revised = [
        SheetSpan("material2", 1, "Material: Aluminum", 0.2, 0.2, 0.2, 0.03),
        SheetSpan("finish2", 1, "Finish: Anodized", 0.2, 0.25, 0.2, 0.03),
    ]
    result = verify_grounded_request(
        row, ExtractedComment(text="fix missed"), evidence, original, revised, ""
    )
    assert result is not None
    assert result.verdict == CommentVerdict.SOLVED_CORRECT
    assert [check.label for check in result.checks] == ["Material", "Finish"]
