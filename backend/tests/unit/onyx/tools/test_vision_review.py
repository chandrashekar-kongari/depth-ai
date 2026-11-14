import json
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import numpy as np
import pytest
from PIL import Image, ImageDraw
from reportlab.pdfgen.canvas import Canvas

from onyx.agents.tools import ToolInvocation
from onyx.db.models import StoredToolResult
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import (
    AssistantMessage,
    ImageContentPart,
    TextContent,
    TextContentPart,
    ToolResult,
    UserMessage,
)
from onyx.tools.models import CommentReviewResult, ToolContext
from onyx.tools.tool_implementations.drawing_review import vision_review_tool
from onyx.tools.tool_implementations.drawing_review.spans import (
    SheetSpan,
    extract_pdf_spans,
)
from onyx.tools.tool_implementations.drawing_review.vision_diagrams import (
    DetectedView,
    DrawingView,
    ViewBox,
    _assign_spans,
    _has_foreign_core,
    _page_marks,
    _refine_overlapping_views,
    _separate_views,
    _view_owner,
    match_views,
)
from onyx.tools.tool_implementations.drawing_review.vision_review_tool import (
    VisionReviewTool,
)

_MODULE = vision_review_tool.__name__


def test_request_ownership_recovers_wrong_view_indices_from_baseline_coordinates() -> (
    None
):
    from onyx.tools.tool_implementations.drawing_review.vision_diagrams import (
        OriginalRequest,
        OriginalRequests,
        ReviewMark,
        _assign_requests,
    )

    views = [
        DetectedView(
            kind="detail",
            label=f"DETAIL {label}",
            core_bbox=(x, y, x + 0.2, y + 0.15),
            complete_bbox=(x - 0.04, y - 0.06, x + 0.25, y + 0.22),
        )
        for label, x, y in (
            ("A", 0.1, 0.2),
            ("B", 0.5, 0.2),
            ("C", 0.1, 0.55),
            ("D", 0.5, 0.55),
        )
    ]
    header = ReviewMark("header", ViewBox(left=0.02, top=0.03, right=0.32, bottom=0.10))
    spans = [
        SheetSpan(label, 1, "Ø12", x + 0.05, y + 0.05, 0.02, 0.01)
        for label, x, y in (
            ("A", 0.1, 0.2),
            ("B", 0.5, 0.2),
            ("C", 0.1, 0.55),
            ("D", 0.5, 0.55),
        )
    ]
    requests = OriginalRequests(
        requests=[
            OriginalRequest(
                view=1,
                view_label="DETAIL A",
                mark_ids=["header"],
                target=span.span_id,
                requested_value="Ø14",
                baseline_span_ids=[span.span_id],
            )
            for span in spans
        ]
    )
    assigned, unassigned = _assign_requests(requests, [header], spans, views)
    assert not unassigned
    assert [[mark.text for mark in group] for group in assigned] == [
        ["A"],
        ["B"],
        ["C"],
        ["D"],
    ]
    assert all(mark.box.top > 0.1 for group in assigned for mark in group)


def test_colored_reviewer_text_cannot_establish_a_printed_change() -> None:
    from dataclasses import replace

    from onyx.tools.tool_implementations.drawing_review.vision_diagrams import (
        Comparison,
        Finding,
        _locate_findings,
    )

    with Image.new("RGB", (200, 200), "white") as image:
        box = ViewBox(left=0, top=0, right=1, bottom=1)
        old = DrawingView(
            1,
            "detail",
            "D",
            box,
            box,
            (SheetSpan("ink", 1, "Ø14", 0.1, 0.2, 0.03, 0.02, colored=True),),
            (),
            image,
            np.asarray(image.convert("L")),
        )
        new = replace(
            old, spans=(SheetSpan("printed", 1, "Ø12", 0.1, 0.2, 0.03, 0.02),)
        )
        result = _locate_findings(
            Comparison(
                findings=[
                    Finding(
                        category="change",
                        status="changed",
                        title="Removed Ø14",
                        detail="Ø14 to Ø12",
                        original_span_id="ink",
                        revised_span_id="printed",
                    )
                ]
            ),
            old,
            new,
        )
    assert result == []


def test_request_inventory_recovers_unassigned_targets_before_comparison() -> None:
    from time import monotonic

    from onyx.tools.tool_implementations.drawing_review import vision_diagrams as vision

    views = [
        DetectedView(
            kind="detail",
            label="DETAIL B",
            core_bbox=(0.4, 0.3, 0.7, 0.6),
            complete_bbox=(0.3, 0.2, 0.8, 0.7),
        )
    ]
    span = SheetSpan("baseline", 1, "10", 0.65, 0.5, 0.02, 0.02)
    initial = vision.OriginalRequests(
        requests=[vision.OriginalRequest(target="Thickness", requested_value="12")]
    )
    repaired = vision.OriginalRequests(
        requests=[
            vision.OriginalRequest(
                target="Thickness",
                requested_value="12",
                view_label="DETAIL B",
                baseline_span_ids=["baseline"],
            )
        ]
    )
    invocation = ToolInvocation(
        call_id="ownership",
        arguments={},
        cancellation=CancellationSignal(),
        update=lambda _: None,
    )
    with (
        Image.new("RGB", (200, 200), "white") as image,
        patch.object(vision, "_ask", side_effect=[initial, repaired]) as ask,
    ):
        assigned, unassigned = vision._mark_inventory(
            image, views, [], [span], Mock(), invocation, monotonic() + 30
        )
    assert ask.call_count == 2
    assert not unassigned
    assert assigned[0][0].baseline_ids == ("baseline",)
    assert assigned[0][0].requested == "12"


def test_unique_native_callout_can_ground_a_model_box() -> None:
    from dataclasses import replace

    from onyx.tools.tool_implementations.drawing_review.vision_diagrams import (
        _evidence_location,
    )

    box = ViewBox(left=0.2, top=0.2, right=0.8, bottom=0.8)
    span = SheetSpan("width", 1, "50", 0.4, 0.5, 0.03, 0.02)
    with Image.new("RGB", (200, 200), "white") as image:
        view = DrawingView(
            1,
            "detail",
            "B",
            box,
            box,
            (span,),
            (),
            image,
            np.asarray(image.convert("L")),
        )
        result = _evidence_location(view, None, [], (0.30, 0.40, 0.40, 0.55))
        assert result.text == "50" and result.span_ids == frozenset({"width"})
        ambiguous = replace(view, spans=(span, replace(span, span_id="second", x=0.42)))
        result = _evidence_location(ambiguous, None, [], (0.30, 0.40, 0.40, 0.55))
        assert result.text is None and not result.span_ids


@pytest.mark.parametrize(
    ("requested", "actual", "expected"),
    [
        ("60", "50", "unresolved"),
        ("35", "30", "unresolved"),
        ("Ø24", "Ø26", "unresolved"),
        ("Ø60", "⌀60", "resolved"),
        ("50 ±0.05", "50 ±0.1", "unresolved"),
        ("60", "", "needs_review"),
    ],
)
def test_numeric_redline_verdict_uses_request_and_observation(
    requested: str, actual: str, expected: str
) -> None:
    from onyx.tools.tool_implementations.drawing_review.vision_diagrams import (
        EvidenceLocation,
        Finding,
        ReviewMark,
        _verify_requested_value,
    )

    box = ViewBox(left=0, top=0, right=1, bottom=1)
    finding = Finding(
        category="comment",
        status="resolved",
        title="Wrong role",
        detail="Model called this resolved.",
    )
    result = _verify_requested_value(
        finding,
        ReviewMark("mark-1", box, "Dimension", requested=requested),
        EvidenceLocation(page=1, box=box, text="50"),
        EvidenceLocation(page=1, box=box, text=actual or None),
    )
    assert result.status == expected


@pytest.mark.parametrize("located", [True, False])
def test_scanned_request_requires_a_located_visual_observation(located: bool) -> None:
    from onyx.tools.tool_implementations.drawing_review.vision_diagrams import (
        EvidenceLocation,
        Finding,
        ReviewMark,
        _verify_requested_value,
    )

    box = ViewBox(left=0.1, top=0.1, right=0.2, bottom=0.2)
    finding = Finding(
        category="comment",
        status="resolved",
        title="Thickness",
        detail="Read visually",
        observed_value="13",
    )
    result = _verify_requested_value(
        finding,
        ReviewMark("mark-1", box, "Thickness", requested="12"),
        EvidenceLocation(page=1, box=box),
        EvidenceLocation(page=1, box=box, localized=located),
        visual_only=True,
    )
    assert result.status == ("unresolved" if located else "needs_review")


def test_tight_crop_retains_boundary_dimensions_and_rejects_shared_reference() -> None:
    from onyx.tools.tool_implementations.drawing_review.view_geometry import (
        PageGeometry,
    )

    views = [
        DetectedView(
            kind="detail",
            core_bbox=(0.12, 0.31, 0.35, 0.50),
            complete_bbox=(0.117, 0.22, 0.35, 0.55),
        ),
        DetectedView(
            kind="detail",
            core_bbox=(0.51, 0.31, 0.73, 0.50),
            complete_bbox=(0.505, 0.22, 0.73, 0.55),
        ),
    ]
    spans = [
        SheetSpan("width", 1, "55", 0.592, 0.531, 0.011, 0.014),
        SheetSpan("height", 1, "12", 0.727, 0.463, 0.010, 0.016),
        SheetSpan("left", 1, "40", 0.459, 0.397, 0.010, 0.016),
        SheetSpan("shared", 1, "80", 0.41, 0.531, 0.010, 0.016),
    ]
    geometry = PageGeometry(
        842,
        595,
        (),
        {
            "width": ((0.5049, 0.506), (0.69, 0.506)),
            "left": ((0.502, 0.31), (0.502, 0.50)),
            "shared": ((0.34, 0.49), (0.51, 0.49)),
        },
    )
    left, right = _assign_spans(spans, views, geometry)
    assert not left
    assert [span.span_id for span in right] == ["width", "height", "left"]


@pytest.mark.parametrize("stacked", [False, True])
def test_view_boundaries_stop_at_drawing_gap(stacked: bool) -> None:
    def orient(
        box: tuple[float, float, float, float],
    ) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = box
        return (y0, x0, y1, x1) if stacked else box

    with Image.new("RGB", (400, 400), "white") as page:
        draw = ImageDraw.Draw(page)
        first = orient((0.1, 0.2, 0.35, 0.7))
        second = orient((0.62, 0.2, 0.85, 0.7))
        for x0, y0, x1, y1 in (first, second):
            draw.rectangle((x0 * 400, y0 * 400, x1 * 400, y1 * 400), outline="black")
        views = _separate_views(
            page,
            [
                DetectedView(
                    kind="detail",
                    core_bbox=first,
                    complete_bbox=orient((0.05, 0.1, 0.7, 0.8)),
                ),
                DetectedView(
                    kind="detail",
                    core_bbox=second,
                    complete_bbox=orient((0.55, 0.1, 0.95, 0.8)),
                ),
            ],
        )
        assert not any(_has_foreign_core(i, views) for i in range(2))
        assert views[0].complete_bbox[3 if stacked else 2] < second[1 if stacked else 0]


def test_tight_view_boundaries_are_rechecked() -> None:
    views = [
        DetectedView(
            kind="detail",
            core_bbox=(0.1, 0.2, 0.45, 0.7),
            complete_bbox=(0.05, 0.1, 0.7, 0.8),
        ),
        DetectedView(
            kind="detail",
            core_bbox=(0.55, 0.2, 0.9, 0.7),
            complete_bbox=(0.5, 0.1, 0.95, 0.8),
        ),
    ]
    refined = [
        views[0].model_copy(update={"complete_bbox": (0.05, 0.1, 0.49, 0.8)}),
        views[1],
    ]
    llm = Mock()
    llm.invoke.return_value = AssistantMessage(
        content=[
            TextContent(
                text=json.dumps({"views": [view.model_dump() for view in refined]})
            )
        ]
    )
    with Image.new("RGB", (400, 400), "black") as page:
        result = _refine_overlapping_views(
            page,
            views,
            llm,
            ToolInvocation(
                call_id="refine",
                arguments={},
                cancellation=CancellationSignal(),
                update=lambda _: None,
            ),
            float("inf"),
        )
    assert llm.invoke.call_count == 1
    assert result == refined


def test_same_row_dimensions_and_redlines_belong_to_separate_views() -> None:
    output = BytesIO()
    pdf = Canvas(output, pagesize=(400, 200))
    pdf.drawString(50, 65, "60 ±0.1")
    pdf.drawString(260, 65, "50")
    pdf.showPage()
    pdf.save()
    spans, _ = extract_pdf_spans(output.getvalue(), 1, split_separated_text=True)
    views = [
        DetectedView(
            kind="detail",
            core_bbox=(0.1, 0.2, 0.35, 0.55),
            complete_bbox=(0.05, 0.1, 0.45, 0.8),
        ),
        DetectedView(
            kind="detail",
            core_bbox=(0.6, 0.2, 0.85, 0.55),
            complete_bbox=(0.5, 0.1, 0.95, 0.8),
        ),
    ]
    assert [
        [span.text for span in view] for view in _assign_spans(spans, views, None)
    ] == [["60 ±0.1"], ["50"]]
    with Image.new("RGB", (800, 400), "white") as page:
        draw = ImageDraw.Draw(page)
        for x in (110, 530):
            draw.ellipse((x - 20, 250, x + 25, 278), outline="red", width=3)
        marks = _page_marks(page, [])
    assert len(marks) == 2
    assert {
        _view_owner(
            (m.box.left + m.box.right) / 2, (m.box.top + m.box.bottom) / 2, views
        )
        for m in marks
    } == {0, 1}


def _pdf(page_count: int, label: str = "WIDTH 100") -> bytes:
    output = BytesIO()
    pdf = Canvas(output, pagesize=(200, 200))
    for index in range(page_count):
        if index == page_count - 1:
            pdf.rect(55, 75, 90, 50)
            pdf.line(65, 80, 115, 100)
            pdf.drawString(75, 130, label)
        pdf.showPage()
    pdf.save()
    return output.getvalue()


def _marked_pdf(revised: bool) -> bytes:
    output = BytesIO()
    pdf = Canvas(output, pagesize=(200, 200))
    pdf.rect(65, 70, 75, 50)
    pdf.drawString(76, 130, "55" if revised else "60")
    pdf.drawString(20, 94, "52" if revised else "50")
    pdf.drawString(18, 82, "±0.05" if revised else "±0.1")
    if not revised:
        pdf.setStrokeColorRGB(1, 0, 0)
        pdf.ellipse(11, 76, 61, 108)
    pdf.showPage()
    pdf.save()
    return output.getvalue()


def test_vision_review_rechecks_marks_and_preserves_clickable_evidence() -> None:
    original_id, revised_id = uuid4(), uuid4()
    tool = VisionReviewTool(1, [], [original_id, revised_id])
    invocation = ToolInvocation(
        call_id="vision",
        arguments={"file_id": str(original_id), "comparison_file_id": str(revised_id)},
        cancellation=CancellationSignal(),
        update=lambda _: None,
    )
    llm = Mock()
    llm.config.model_name = "vision"
    detected = {
        "views": [
            {
                "kind": "front",
                "core_bbox": [0.32, 0.39, 0.71, 0.66],
                "complete_bbox": [0, 0.2, 1, 0.8],
            }
        ]
    }
    changes = {
        "findings": [
            {
                "category": "change",
                "status": "resolved",
                "title": "Top width",
                "detail": "60 to 55",
                "original_span_id": "p1l0",
                "revised_span_id": "p1l0",
            },
            {
                "category": "change",
                "status": "changed",
                "title": "Duplicate height change",
                "detail": "0.1 to 0.05",
                "original_span_ids": ["p1l1", "p1l2"],
                "revised_span_ids": ["p1l1", "p1l2"],
            },
            {
                "category": "change",
                "status": "changed",
                "title": "Height nominal value changed",
                "detail": "50 to 52",
                "original_span_ids": ["p1l1", "p1l2"],
                "revised_span_ids": ["p1l1", "p1l2"],
            },
            {
                "category": "change",
                "status": "changed",
                "title": "Datum added",
                "detail": "A datum was added.",
                "revised_bbox": [0.5, 0.7, 0.55, 0.75],
            },
        ]
    }
    targeted = {
        "findings": [
            {
                "category": "change",
                "status": "resolved",
                "mark_id": "mark-1",
                "title": "Height tolerance corrected",
                "detail": "0.1 to 0.05",
                "original_span_ids": ["p1l1", "p1l2"],
                "revised_span_ids": ["p1l1", "p1l2"],
            },
        ]
    }
    inventory = {
        "requests": [
            {
                "view": 1,
                "mark_ids": ["mark-1"],
                "target": "Height tolerance corrected",
                "requested_value": "±0.05",
                "value_scope": "tolerance",
                "baseline_span_ids": ["p1l1", "p1l2"],
            }
        ]
    }
    llm.invoke.side_effect = [
        AssistantMessage(content=[TextContent(text=json.dumps(reply))])
        for reply in (
            detected,
            inventory,
            detected,
            changes,
            {"findings": []},
            targeted,
        )
    ]
    with (
        patch.object(
            tool._files,
            "load",
            side_effect=[
                (_marked_pdf(False), "before.pdf"),
                (_marked_pdf(True), "after.pdf"),
            ],
        ),
        patch(f"{_MODULE}.get_default_llm_with_vision", return_value=llm),
    ):
        result = tool.run(
            invocation, ToolContext(user_request="Check drawing changes.")
        )

    assert isinstance(result, ToolResult)
    assert isinstance(result.details, CommentReviewResult)
    assert "Duplicate height change" not in result.content
    assert "50 ±0.1” → PDF page 1, “52 ±0.05" in result.content
    [comment] = result.details.comments
    assert comment.verdict == "solved_correct"
    assert comment.box is not None
    assert comment.revised_box is not None
    assert comment.revised_location_verified
    assert result.details.drawing_changes is not None
    width, nominal, datum = result.details.drawing_changes.changes
    assert (width.before_text, width.after_text) == ("60", "55")
    assert width.original_box is not None and width.revised_box is not None
    assert "50 to 52" in nominal.vision_explanation
    assert datum.original_box is None
    assert datum.revised_box is not None
    assert datum.revised_box.y == pytest.approx(0.62)


@pytest.mark.parametrize("original_label", ["WIDTH 120", "WIDTH 100"])
def test_vision_review_compares_rendered_pages(
    monkeypatch: pytest.MonkeyPatch,
    original_label: str,
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[4]))
    original_id, revision_id = uuid4(), uuid4()
    tool = VisionReviewTool(1, [], [original_id, revision_id])
    request = "Review through vision and check the width."
    invocation = ToolInvocation(
        call_id="vision",
        arguments={"file_id": str(original_id), "comparison_file_id": str(revision_id)},
        cancellation=CancellationSignal(),
        update=lambda _: None,
    )
    llm = Mock()
    llm.config.model_name = "configured-vision-model"
    detected = '{"views":[{"kind":"front","label":"FRONT","core_bbox":[0.1,0.1,0.9,0.9],"complete_bbox":[0,0,1,1]}]}'
    changes = '{"findings":[{"category":"change","status":"changed","title":"Width changed","detail":"120 to 100","original_span_id":"p2l0","revised_span_id":"p1l0"}]}'
    single_view = json.dumps(json.loads(detected)["views"][0])
    single_change = json.dumps(json.loads(changes)["findings"][0])
    llm.invoke.side_effect = [
        AssistantMessage(content=[TextContent(text=text)])
        for text in (
            '{"views":[]}',
            detected,
            '{"requests":[]}',
            single_view,
            single_change,
            '{"findings":[]}',
        )
    ]

    with (
        patch.object(
            tool._files,
            "load",
            side_effect=[
                (_pdf(2, original_label), "before.pdf"),
                (_pdf(1), "after.pdf"),
            ],
        ),
        patch(f"{_MODULE}.get_default_llm_with_vision", return_value=llm),
    ):
        result = tool.run(invocation, ToolContext(user_request=request))

    assert isinstance(result, ToolResult)
    assert result.is_error is False
    assert "configured-vision-model" in result.content
    assert "Compared 1 of 1 matched views" in result.content
    assert "FRONT (page 2) → FRONT (page 1)" in result.content
    assert llm.invoke.call_count == 6
    assert isinstance(result.details, CommentReviewResult)
    stored = StoredToolResult(
        tool_name=tool.name,
        tool_call_id=invocation.call_id,
        content=result.content,
        details=result.details,
    )
    restored = StoredToolResult.model_validate_json(stored.model_dump_json())
    assert isinstance(restored.details, CommentReviewResult)
    assert restored.details.drawing_changes is not None
    if original_label == "WIDTH 120":
        assert "120 to 100" in result.content
        change = restored.details.drawing_changes.changes[0]
        assert (change.page, change.revised_page) == (2, 1)
        assert change.revised_box is not None
    else:
        assert "120 to 100" not in result.content
        assert "found no clear changes" in result.content
        assert restored.details.drawing_changes.changes == []
    message = llm.invoke.call_args.args[0].messages[1]
    assert isinstance(message, UserMessage)
    assert isinstance(message.content, list)
    text = [part.text for part in message.content if isinstance(part, TextContentPart)]
    assert text[0] == request
    assert text[1].startswith("Original FRONT (page 2)")
    assert text[2].startswith("Revised FRONT (page 1)")
    images = [part for part in message.content if isinstance(part, ImageContentPart)]
    assert len(images) >= 2
    assert all(
        image.image_url.url.startswith("data:image/png;base64,") for image in images
    )


@pytest.mark.parametrize("missing_model", [True, False])
def test_vision_review_requires_a_model_and_allowed_file(missing_model: bool) -> None:
    tool = VisionReviewTool(1, [], [])
    invocation = ToolInvocation(
        call_id="vision",
        arguments={"file_id": str(uuid4())},
        cancellation=CancellationSignal(),
        update=lambda _: None,
    )
    llm = Mock()
    with (
        patch(
            f"{_MODULE}.get_default_llm_with_vision",
            return_value=None if missing_model else llm,
        ),
        patch(
            "onyx.tools.tool_implementations.drawing_review.files.get_session_with_current_tenant"
        ),
        patch(
            "onyx.tools.tool_implementations.drawing_review.files.get_file_id_by_user_file_id",
            return_value=None,
        ),
    ):
        result = tool.run(invocation, ToolContext())
    assert isinstance(result, ToolResult)
    assert result.is_error
    assert (
        "requires a Captioning LLM" if missing_model else "is not available"
    ) in result.content
    llm.invoke.assert_not_called()


def test_vision_pdf_render_skips_native_text_extraction() -> None:
    with patch(
        "onyx.tools.tool_implementations.drawing_review.sheet.extract_pdf_spans",
        side_effect=AssertionError("Vision-only rendering must skip native text"),
    ):
        pages, total, spans, truncated = vision_review_tool.render_pdf_pngs(
            _pdf(1), 1, extract_spans=False
        )
    assert len(pages) == total == 1
    assert spans == truncated == []


def test_duplicate_views_require_distinguishing_identifiers() -> None:
    geometry = np.full((100, 100), 255, dtype=np.uint8)
    geometry[15:85, 20:25] = 0
    geometry[80:85, 20:85] = 0
    box = ViewBox(left=0, top=0, right=1, bottom=1)

    def view(page: int, label: str) -> DrawingView:
        return DrawingView(
            page=page,
            kind="detail",
            label=label,
            core=box,
            complete=box,
            spans=(),
            comments=(),
            crop=Image.fromarray(geometry),
            geometry=geometry,
        )

    named = match_views([view(1, "A"), view(1, "B")], [view(3, "B"), view(2, "A")])
    assert named.pairs == [(0, 1), (1, 0)]
    unnamed = match_views([view(1, ""), view(1, "")], [view(3, ""), view(2, "")])
    assert unnamed.pairs == []
    assert unnamed.ambiguous_original == unnamed.ambiguous_revised == {0, 1}


def test_openrouter_vision_policy_disables_reasoning() -> None:
    policy = vision_review_tool._vision_request_policy(None, "openrouter")
    assert policy.model_kwargs["extra_body"] == {"reasoning": {"enabled": False}}


@pytest.mark.parametrize(
    "verdict, malformed_first, expected_calls",
    [
        ("same_view", False, 6),
        ("same_view", True, 7),
        ("uncertain", False, 4),
        ("different_view", False, 4),
        ("invalid", True, 5),
    ],
)
def test_low_similarity_requires_vision_confirmation(
    verdict: str, malformed_first: bool, expected_calls: int
) -> None:
    from time import monotonic

    from onyx.tools.tool_implementations.drawing_review import vision_diagrams
    from onyx.tools.tool_implementations.drawing_review.vision_diagrams import (
        DiagramDocument,
        compare_document_views,
    )

    image = Image.new("RGB", (200, 200), "white")
    buffer = BytesIO()
    image.save(buffer, "PNG")
    original = DiagramDocument(
        "original.pdf",
        [buffer.getvalue()],
        1,
        [SheetSpan("p1l0", 1, "DWG NO. TEST-15", 0.1, 0.9, 0.4, 0.04)],
        {},
    )
    revised = DiagramDocument(
        "revised.pdf",
        [buffer.getvalue()],
        1,
        [SheetSpan("p1l0", 1, "DWG NO. TEST-16", 0.1, 0.9, 0.4, 0.04)],
        {},
    )
    llm = Mock()
    llm.config.model_name = "vision"
    detection = '{"views":[{"kind":"front","core_bbox":[0.1,0.1,0.8,0.8],"complete_bbox":[0,0,1,1]}]}'
    llm.invoke.side_effect = [
        AssistantMessage(content=[TextContent(text=value)])
        for value in (
            detection,
            '{"requests":[]}',
            detection.replace('"front"', '"section"'),
            *(['{"match": true}'] if malformed_first else []),
            json.dumps(
                {
                    "verdict": verdict,
                    "evidence": "Checked the arrangement of the features.",
                }
            ),
            '{"findings":[]}',
            '{"findings":[]}',
        )
    ]
    invocation = ToolInvocation(
        call_id="vision",
        arguments={},
        cancellation=CancellationSignal(),
        update=lambda _: None,
    )
    with patch.object(vision_diagrams, "aligned_similarity", return_value=0.52):
        review = compare_document_views(
            original, revised, llm, "", invocation, monotonic() + 30
        )
    assert review.compared == int(verdict == "same_view")
    assert llm.invoke.call_count == expected_calls
    if malformed_first:
        retry = llm.invoke.call_args_list[4].args[0]
        assert retry.options.structured_response_format["type"] == "json_schema"
    if verdict == "uncertain":
        assert "Ambiguous match" in review.content
    elif verdict == "different_view":
        assert "Unmatched view" in review.content
    elif verdict == "invalid":
        assert "Match verification failed" in review.content
        assert "Ambiguous match" not in review.content


def test_pdf_outlines_match_with_loose_crop_and_conflicting_view_types() -> None:
    from onyx.tools.tool_implementations.drawing_review.vision_diagrams import (
        DetectedView,
        _make_view,
    )

    def view(
        shape: str, kind: str, core: tuple[float, float, float, float]
    ) -> DrawingView:
        output = BytesIO()
        pdf = Canvas(output, pagesize=(220, 220))
        pdf.setLineWidth(2)
        if shape == "rectangle":
            pdf.rect(45, 70, 110, 60)
        else:
            pdf.circle(100, 100, 45)
        pdf.setStrokeColorRGB(1, 0, 0)
        pdf.rect(30, 44, 155, 117)
        pdf.drawString(40, 35, "DWG NO. SAMPLE-1")
        pdf.save()
        document = vision_review_tool._preprocess_pdf(output.getvalue(), "test.pdf")
        with Image.open(BytesIO(document.pages[0])) as image:
            return _make_view(
                1,
                image,
                DetectedView(
                    kind=kind, core_bbox=core, complete_bbox=(0.1, 0.2, 0.91, 0.83)
                ),
                document.spans,
                [],
                document.page_geometry[1],
            )

    original = view("rectangle", "section", (0.15, 0.23, 0.82, 0.72))
    revised = view("rectangle", "front", (0.26, 0.39, 0.65, 0.62))
    unrelated = view("circle", "front", (0.22, 0.32, 0.72, 0.76))
    assert original.vector_shape is not None
    assert revised.vector_shape is not None
    assert unrelated.vector_shape is not None
    assert match_views([original], [unrelated, revised]).pairs == [(0, 1)]
    rejected = match_views([original], [unrelated])
    assert rejected.pairs == [] and rejected.candidates == ()
