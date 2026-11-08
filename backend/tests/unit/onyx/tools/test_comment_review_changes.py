"""Evidence and coverage gates for paired MechVL change discovery."""

import json
import time
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from onyx.llm.cancellation import CancellationSignal, cancellation_scope
from onyx.tools.models import DrawingChange, DrawingMarkBox
from onyx.tools.tool_implementations.drawing_review.comment_review import (
    _validate_drawing_changes,
)
from onyx.tools.tool_implementations.drawing_review.sheet import _SheetPages

_REVIEW = "onyx.tools.tool_implementations.drawing_review.comment_review"
_BOX = DrawingMarkBox(x=0.2, y=0.3, width=0.1, height=0.1)


def _pages(count: int = 1) -> _SheetPages:
    output = BytesIO()
    Image.new("RGB", (400, 300), "white").save(output, format="PNG")
    return _SheetPages([output.getvalue()] * count, [], [], count)


def _observation(confirmed: bool = False, *, visual: bool = False) -> dict[str, object]:
    return {
        "status": "confirmed" if confirmed else "unconfirmed",
        "before_text": "" if visual else "24",
        "after_text": "" if visual else "25",
        "original_box": _BOX.model_dump(),
        "revised_box": _BOX.model_dump(),
        "explanation": "A round hole becomes a slot on the left mounting lug."
        if visual
        else "The lug callout changes from 24 to 25.",
    }


def _response(**observations: object) -> str:
    return json.dumps(
        {"extra1": _observation(), "extra2": _observation(), **observations}
    )


@pytest.mark.parametrize("artifact", [False, True])
def test_geometry_discovery_requires_both_focused_regions(artifact: bool) -> None:
    focused = json.dumps(
        {
            "same_feature": True,
            "visible_difference": True,
            "artifact_or_markup": artifact,
            "before_observation": "Round hole",
            "after_observation": "Elongated slot",
        }
    )
    with patch(
        f"{_REVIEW}._review_invoke",
        side_effect=[_response(extra1=_observation(True, visual=True)), focused],
    ) as invoke:
        result = _validate_drawing_changes(
            MagicMock(),
            [],
            [1],
            set(),
            _pages(),
            _pages(),
            "after.pdf",
            time.monotonic() + 60,
        )
    assert len(result.changes) == (0 if artifact else 1)
    assert result.validation_status == "complete"
    assert invoke.call_count == 2
    messages = invoke.call_args.args[1]
    content = messages[1].content
    assert isinstance(content, list)
    # Focused confirmation receives two crops, in Before/After order.
    assert sum(part.type == "image_url" for part in content) == 2


def test_scanned_text_discovery_stays_out_when_focused_check_times_out() -> None:
    with patch(
        f"{_REVIEW}._review_invoke",
        side_effect=[_response(extra1=_observation(True)), None],
    ):
        result = _validate_drawing_changes(
            MagicMock(),
            [],
            [1],
            set(),
            _pages(),
            _pages(),
            "after.pdf",
            time.monotonic() + 60,
        )
    assert result.changes == []
    assert result.validation_status == "incomplete"
    assert result.validated_pages == []
    assert result.warnings


def test_rotated_unchanged_callout_is_not_a_finding() -> None:
    candidate = DrawingChange(
        id="dc1", page=1, kind="visual", original_box=_BOX, revised_box=_BOX
    )
    rejected = _observation(visual=True)
    rejected["explanation"] = (
        "The same callout is rotated; its feature and value are unchanged."
    )
    with patch(f"{_REVIEW}._review_invoke", return_value=_response(dc1=rejected)):
        result = _validate_drawing_changes(
            MagicMock(),
            [candidate],
            [1],
            set(),
            _pages(),
            _pages(),
            "after.pdf",
            time.monotonic() + 60,
        )
    assert all(change.vision_validation != "confirmed" for change in result.changes)
    assert result.validation_status == "complete"


def test_later_timeout_preserves_confirmed_results_and_names_unchecked_page() -> None:
    changes = [
        DrawingChange(
            id=f"dc{page}",
            page=page,
            kind="text_changed",
            before_text="24",
            after_text="25",
            original_box=_BOX,
            revised_box=_BOX,
        )
        for page in (1, 2)
    ]
    with patch(
        f"{_REVIEW}._review_invoke",
        side_effect=[_response(dc1=_observation(True)), None],
    ):
        result = _validate_drawing_changes(
            MagicMock(),
            changes,
            [1, 2],
            set(),
            _pages(2),
            _pages(2),
            "after.pdf",
            time.monotonic() + 60,
        )
    assert result.changes[0].vision_validation == "confirmed"
    assert result.changes[1].vision_validation is None
    assert result.validated_pages == [1]
    assert result.validation_status == "incomplete"
    assert "Before page 2" in result.warnings[0]


def test_cancellation_preserves_earlier_validation() -> None:
    signal = CancellationSignal()

    def invoke(*_args: object, **_kwargs: object) -> str:
        signal.cancel()
        return _response(dc1=_observation(True))

    changes = [
        DrawingChange(
            id=f"dc{page}",
            page=page,
            kind="text_changed",
            before_text="24",
            after_text="25",
            original_box=_BOX,
            revised_box=_BOX,
        )
        for page in (1, 2)
    ]
    with (
        cancellation_scope(signal),
        patch(f"{_REVIEW}._review_invoke", side_effect=invoke),
    ):
        result = _validate_drawing_changes(
            MagicMock(),
            changes,
            [1, 2],
            set(),
            _pages(2),
            _pages(2),
            "after.pdf",
            time.monotonic() + 60,
        )
    assert result.changes[0].vision_validation == "confirmed"
    assert "cancelled" in result.warnings[0]


def test_discovered_geometry_deduplicates_by_feature_and_observation() -> None:
    candidate = DrawingChange(
        id="dc1", page=1, kind="visual", original_box=_BOX, revised_box=_BOX
    )
    proposed = _observation(True, visual=True)
    proposed["explanation"] = "The mounting opening changes shape."
    focused = json.dumps(
        {
            "same_feature": True,
            "visible_difference": True,
            "artifact_or_markup": False,
            "before_observation": "Round hole",
            "after_observation": "Slot",
            "duplicate_change_id": "dc1",
        }
    )
    with patch(
        f"{_REVIEW}._review_invoke",
        side_effect=[
            _response(dc1=_observation(True, visual=True), extra1=proposed),
            focused,
        ],
    ):
        result = _validate_drawing_changes(
            MagicMock(),
            [candidate],
            [1],
            set(),
            _pages(),
            _pages(),
            "after.pdf",
            time.monotonic() + 60,
        )
    assert [change.id for change in result.changes] == ["dc1"]


@pytest.mark.parametrize("supported", [True, False])
def test_new_discovery_links_only_when_target_and_action_are_supported(
    supported: bool,
) -> None:
    from onyx.tools.models import (
        CommentReviewResult,
        CommentVerdict,
        DrawingChangeReview,
        DrawingComment,
    )
    from onyx.tools.tool_implementations.drawing_review.comment_review import (
        _link_discovered_changes,
    )
    from onyx.tools.tool_implementations.drawing_review.spans import SheetSpan

    moved = _BOX.model_copy(update={"x": 0.7})
    comment = DrawingComment(
        id="c1",
        page=1,
        text="missing",
        request="Add the callout between the marked endpoints",
        verdict=CommentVerdict.SOLVED_CORRECT,
        evidence="8",
        remaining="",
        box=_BOX,
        revised_box=moved,
        revised_span_id="value",
        revised_page=1,
    )
    change = DrawingChange(
        id="dc-vision-1-extra1",
        page=1,
        kind="text_added",
        after_text="8",
        original_box=_BOX,
        revised_box=moved,
        vision_validation="confirmed",
    )
    after = _pages()
    after.spans.append(
        SheetSpan("value", 1, "8", moved.x, moved.y, moved.width, moved.height)
    )
    response = json.dumps(
        {
            "same_target": supported,
            "requested_action_supported": supported,
            "before_target_evidence": "Arrow terminates on the two bracket endpoints",
            "requested_action": "Add the absent callout on those endpoints",
            "observed_evidence": "8",
            "change_satisfies_request": supported,
        }
    )
    with patch(f"{_REVIEW}._review_invoke", return_value=response):
        result = _link_discovered_changes(
            CommentReviewResult(status="Done", report="", comments=[comment]),
            DrawingChangeReview(status="complete", changes=[change]),
            _pages(),
            after,
            MagicMock(),
            "after.pdf",
            time.monotonic() + 60,
        )
    assert result.comments[0].verified_change_ids == ([change.id] if supported else [])


def test_same_pdf_pair_is_claimed_once_per_tool_instance() -> None:
    from onyx.tools.models import ToolCallException
    from onyx.tools.tool_implementations.drawing_review.comment_review_tool import (
        CommentReviewTool,
    )

    tool = CommentReviewTool(1, [], [])
    tool._claim_pair(b"before", b"after")
    with pytest.raises(ToolCallException, match="already reviewed"):
        tool._claim_pair(b"after", b"before")
    # A new turn builds new tools; no review result or claim is cached across turns.
    CommentReviewTool(1, [], [])._claim_pair(b"before", b"after")


@pytest.mark.parametrize("name", ["sheet.png", "sheet.jpg", "sheet.webp", "part.dxf"])
def test_comment_review_rejects_non_pdf_inputs(name: str) -> None:
    from onyx.tools.models import ToolCallException
    from onyx.tools.tool_implementations.drawing_review.comment_review_tool import (
        CommentReviewTool,
    )

    tool = CommentReviewTool(1, [], [])
    with (
        patch.object(tool, "_load_original", return_value=(b"data", name)),
        pytest.raises(ToolCallException),
    ):
        tool._load_sheet("file", "commented")


def test_comment_verification_uses_reordered_after_page() -> None:
    from onyx.engineering.drawing_changes import DrawingEvidence
    from onyx.tools.models import (
        CommentVerdict,
        DrawingChangeReview,
        DrawingReviewBrief,
    )
    from onyx.tools.tool_implementations.drawing_review.comment_queue import (
        ExtractedComment,
        VerdictDraft,
    )
    from onyx.tools.tool_implementations.drawing_review.comment_review import (
        verify_sheet_comments,
    )
    from onyx.tools.tool_implementations.drawing_review.spans import SheetSpan

    after = _pages(2)
    after.spans.append(SheetSpan("correct", 2, "FINISH: ground", 0.2, 0.3, 0.2, 0.1))
    with (
        patch(
            f"{_REVIEW}._extract_page",
            return_value=(
                [
                    ExtractedComment(
                        text="Set finish to ground", request="Set finish to ground"
                    )
                ],
                False,
            ),
        ),
        patch(
            f"{_REVIEW}._judge_comment",
            return_value=VerdictDraft(
                status=CommentVerdict.SOLVED_CORRECT,
                evidence="FINISH: ground",
                span_id="correct",
            ),
        ) as judge,
        patch(
            f"{_REVIEW}._validate_drawing_changes",
            return_value=DrawingChangeReview(
                status="complete", validation_status="complete", validated_pages=[1]
            ),
        ),
    ):
        result = verify_sheet_comments(
            _pages(2),
            after,
            commented_name="before.pdf",
            revised_name="after.pdf",
            dxf_summary=None,
            llm=MagicMock(),
            brief=DrawingReviewBrief(original_pages=[1]),
            drawing_evidence=DrawingEvidence(
                comparison=DrawingChangeReview(
                    status="complete", compared_pages=[1], page_pairs={1: 2, 2: 1}
                )
            ),
        )
    assert result.comments[0].revised_page == 2
    assert judge.call_args.kwargs["page_number"] == 2
    assert result.comment_verified_pages == [1]
