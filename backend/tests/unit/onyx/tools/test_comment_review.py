import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import JsonValue

from onyx.agents.tools import ToolInvocation
from onyx.chat.prompt_utils import prepare_prompt
from onyx.file_store.models import ExtractedContextFiles, FileToolMetadata
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import UserMessage
from onyx.tools.models import (
    CommentReviewResult,
    CommentVerdict,
    ToolCallException,
    ToolContext,
)
from onyx.tools.tool_implementations.drawing_review.comment_queue import (
    ExtractedComment,
    VerdictDraft,
    apply_verdict,
    comment_from_extraction,
    format_comment_report,
    parse_extracted_comments,
)
from onyx.tools.tool_implementations.drawing_review.comment_review import (
    verify_sheet_comments,
)
from onyx.tools.tool_implementations.drawing_review.comment_review_tool import (
    CommentReviewTool,
)
from onyx.tools.tool_implementations.drawing_review.sheet import _SheetPages
from onyx.tools.tool_implementations.drawing_review.spans import SheetSpan

_REVIEW = "onyx.tools.tool_implementations.drawing_review.comment_review"
_TOOL = "onyx.tools.tool_implementations.drawing_review.comment_review_tool"


def _llm(texts: list[str]) -> MagicMock:
    llm = MagicMock()
    llm.invoke.side_effect = [MagicMock(text=text) for text in texts]
    return llm


def _invocation(arguments: dict[str, JsonValue]) -> ToolInvocation:
    return ToolInvocation(
        call_id="comments",
        arguments=arguments,
        cancellation=CancellationSignal(),
        update=lambda _progress: None,
    )


def _pages(count: int, total: int | None = None) -> _SheetPages:
    return _SheetPages(
        pages=[b"page"] * count,
        spans=[],
        truncated_pages=[],
        total=count if total is None else total,
    )


def _comment(text: str, request: str) -> str:
    return json.dumps(
        {"comments": [{"text": text, "request": request, "span_id": None}]}
    )


def _verdict(status: str, evidence: str, remaining: str) -> str:
    return json.dumps(
        {
            "status": status,
            "evidence": evidence,
            "remaining": remaining,
            "span_id": None,
        }
    )


def test_every_parsed_comment_becomes_one_queue_row() -> None:
    raw = json.dumps(
        {
            "comments": [
                {"text": "Move the hole.", "request": "Move the hole."},
                {"text": "Add the note.", "request": "Add the note."},
                {"text": "Fix the revision.", "request": "Fix the revision."},
            ]
        }
    )
    assert len(parse_extracted_comments(raw)) == 3


def test_verdicts_name_a_correct_fix_a_wrong_fix_and_an_open_change() -> None:
    llm = _llm(
        [
            json.dumps(
                {
                    "comments": [
                        {
                            "text": "Move the hole.",
                            "request": "Move the hole to 12 mm.",
                        },
                        {"text": "Add the note.", "request": "Add the finish note."},
                        {"text": "Fix the revision.", "request": "Set revision B."},
                    ]
                }
            ),
            _verdict("solved_correct", "hole at 12 mm", ""),
            _verdict(
                "solved_incorrect", "hole at 10 mm", "The hole is 10 mm, not 12 mm."
            ),
            _verdict("open", "revision A", "Set revision B."),
            json.dumps({"issues": []}),
        ]
    )
    with patch(
        f"{_REVIEW}.prepare_image_bytes", return_value="data:image/png;base64,aa"
    ):
        result = verify_sheet_comments(
            _pages(1),
            _pages(1),
            commented_name="marked.pdf",
            revised_name="new.pdf",
            dxf_summary=None,
            llm=llm,
        )

    assert isinstance(result, CommentReviewResult)
    assert [item.verdict for item in result.comments] == [
        CommentVerdict.SOLVED_CORRECT,
        CommentVerdict.SOLVED_INCORRECT,
        CommentVerdict.OPEN,
    ]
    assert result.comments[1].remaining == "The hole is 10 mm, not 12 mm."
    assert result.comments[2].remaining == "Set revision B."
    assert llm.invoke.call_count == 4


def test_comment_text_is_not_a_measurement() -> None:
    span = SheetSpan("p1s0", 1, "25.4", 0.1, 0.2, 0.2, 0.05)
    comment = comment_from_extraction(
        ExtractedComment(text="Change 25.4 to 30", request="Change 25.4 to 30"),
        comment_id="c1",
        page=1,
        spans={"p1s0": span},
    )
    judged = apply_verdict(
        comment,
        VerdictDraft(
            status=CommentVerdict.OPEN, evidence="25.4", remaining="Change it to 30."
        ),
        {},
        revised_page=1,
        dxf_attached=True,
    )
    dxf_summary = "## measured\nmeasurement=25.4"
    report = format_comment_report(
        [judged],
        [],
        commented_name="marked.pdf",
        revised_name="new.pdf",
        dxf_summary=dxf_summary,
        skipped_note=None,
    )

    assert judged.evidence.startswith("visible text:")
    assert "Comment text is not a measurement." in report
    assert report.split("## measured", 1)[1].strip() == dxf_summary


def test_unpaired_comments_are_unclear_when_page_counts_differ() -> None:
    llm = _llm(
        [
            _comment("Move the hole.", "Move the hole."),
            _verdict("solved_correct", "moved", ""),
            _comment("Add the note.", "Add the note."),
            json.dumps({"issues": []}),
        ]
    )
    with patch(
        f"{_REVIEW}.prepare_image_bytes", return_value="data:image/png;base64,aa"
    ):
        result = verify_sheet_comments(
            _pages(2),
            _pages(1),
            commented_name="marked.pdf",
            revised_name="new.pdf",
            dxf_summary=None,
            llm=llm,
        )

    assert result.comments[0].verdict is CommentVerdict.SOLVED_CORRECT
    assert result.comments[1].verdict is CommentVerdict.UNCLEAR
    assert "no matching page" in result.comments[1].remaining
    assert llm.invoke.call_count == 3


def test_missing_sheet_tells_the_model_which_file_to_pass() -> None:
    tool = CommentReviewTool(tool_id=8, user_file_ids=[], chat_file_ids=[])
    with pytest.raises(ToolCallException) as caught:
        tool._run(invocation=_invocation({}), context=ToolContext())
    message = caught.value.llm_facing_message
    assert "commented_sheet_file_id" in message
    assert "revised_sheet_file_id" in message


def test_reversed_pdf_roles_are_reported_after_visual_discovery() -> None:
    tool = CommentReviewTool(tool_id=8, user_file_ids=[], chat_file_ids=[])
    original_id, revised_id = str(uuid4()), str(uuid4())
    with (
        patch.object(
            tool,
            "_load_sheet",
            side_effect=[(b"corrected", "RevB.pdf"), (b"comments", "RevA.pdf")],
        ),
        patch(f"{_TOOL}._sheet_pages", return_value=_pages(1)),
        patch(
            f"{_TOOL}.run_in_isolated_process",
            side_effect=[
                (1, {}),
                {1: "drawing text"},
                (1, {1: [ExtractedComment(text="Fix hole", request="Fix hole")]}),
            ],
        ),
        patch(f"{_TOOL}.get_default_llm_with_vision") as model,
        patch(
            f"{_TOOL}.verify_sheet_comments",
            return_value=CommentReviewResult(status="empty", report="empty"),
        ),
        patch(
            f"{_TOOL}.ground_review_highlights",
            side_effect=lambda result, _spans: result,
        ),
        pytest.raises(ToolCallException) as caught,
    ):
        tool._run(
            invocation=_invocation(
                {
                    "commented_sheet_file_id": original_id,
                    "revised_sheet_file_id": revised_id,
                }
            ),
            context=ToolContext(),
        )
    assert f"commented_sheet_file_id='{revised_id}'" in caught.value.llm_facing_message
    assert f"revised_sheet_file_id='{original_id}'" in caught.value.llm_facing_message
    assert "no DXF" in caught.value.llm_facing_message
    model.assert_called_once()


def test_empty_visual_review_is_not_returned_as_success() -> None:
    tool = CommentReviewTool(tool_id=8, user_file_ids=[], chat_file_ids=[])
    empty = CommentReviewResult(status="Processed 0 comments", report="empty")
    with (
        patch.object(tool, "_load_sheet", return_value=(b"image", "sheet.png")),
        patch(f"{_TOOL}._sheet_pages", return_value=_pages(1)),
        patch(f"{_TOOL}.get_default_llm_with_vision", return_value=MagicMock()),
        patch(f"{_TOOL}.verify_sheet_comments", return_value=empty),
        patch(f"{_TOOL}.ground_review_highlights", return_value=empty),
        pytest.raises(ToolCallException) as caught,
    ):
        tool._run(
            invocation=_invocation(
                {
                    "commented_sheet_file_id": str(uuid4()),
                    "revised_sheet_file_id": str(uuid4()),
                }
            ),
            context=ToolContext(),
        )
    assert "No review was completed" in caught.value.llm_facing_message
    assert "does not require DXF" in caught.value.llm_facing_message


def test_a_dxf_is_not_accepted_as_a_sheet() -> None:
    tool = CommentReviewTool(tool_id=8, user_file_ids=[], chat_file_ids=[])
    file_id = str(uuid4())
    with (
        patch.object(tool, "_load_original", return_value=(b"dxf", "part.dxf")),
        pytest.raises(ToolCallException) as caught,
    ):
        tool._run(
            invocation=_invocation(
                {
                    "commented_sheet_file_id": file_id,
                    "revised_sheet_file_id": file_id,
                }
            ),
            context=ToolContext(),
        )
    assert "commented_sheet_file_id" in caught.value.llm_facing_message


def test_file_notice_names_comment_review_ahead_of_read_file() -> None:
    metadata = FileToolMetadata(
        file_id="sheet-1",
        filename="marked.pdf",
        approx_char_count=20,
    )
    listed = prepare_prompt(
        [UserMessage(content="verify")],
        system_prompt=None,
        custom_agent_prompt=None,
        reminder_message=None,
        context_files=ExtractedContextFiles(
            file_texts=[],
            image_files=[],
            use_as_search_filter=False,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=None,
            file_metadata_for_tool=[metadata],
        ),
        token_counter=len,
        available_tool_names={"read_file", "verify_drawing_comments"},
    )
    listed_text = "\n".join(message.text for message in listed)
    assert "verify_drawing_comments" in listed_text
    assert 'file_id="sheet-1"' in listed_text
    assert "Use the read_file tool" not in listed_text


def test_extra_issue_uses_grounded_span_without_native_comment_box() -> None:
    from onyx.tools.tool_implementations.drawing_review.comment_queue import (
        ExtraIssueDraft,
        extra_issue_from_draft,
    )
    from onyx.tools.tool_implementations.drawing_review.spans import SheetSpan

    span = SheetSpan(
        span_id="p1s1", page=1, text="THRU", x=0.1, y=0.2, width=0.3, height=0.04
    )
    issue = extra_issue_from_draft(
        ExtraIssueDraft(title="Fit missing", detail="Add fit", span_id="p1s1"),
        issue_id="e1",
        page=1,
        spans={span.span_id: span},
    )
    assert issue.box is not None
    assert issue.box.x == 0.1
    assert issue.page_level is False
    fallback = extra_issue_from_draft(
        ExtraIssueDraft(title="Check note"), issue_id="e2", page=1, spans={}
    )
    assert fallback.page_level is True


def test_extra_issues_do_not_discard_completed_pdf_comment_review() -> None:
    with (
        patch(
            "onyx.tools.tool_implementations.drawing_review.comment_review._invoke",
            side_effect=[
                _comment("Add H7 fit", "Add H7 fit"),
                _verdict("solved_correct", "Ø8 H7 THRU", ""),
                json.dumps(
                    {
                        "issues": [
                            {"title": "Unrelated note missing", "detail": "Add note"}
                        ]
                    }
                ),
            ],
        ),
        patch(
            "onyx.tools.tool_implementations.drawing_review.comment_review._encode",
            return_value="data:image/png;base64,test",
        ),
    ):
        result = verify_sheet_comments(
            _pages(1),
            _pages(1),
            commented_name="original.pdf",
            revised_name="revised.pdf",
            dxf_summary=None,
            llm=MagicMock(),
            include_extra_issues=True,
        )
    assert result.comments[0].verdict.value == "solved_correct"
    assert result.extra_issues[0].title == "Unrelated note missing"


def test_optional_extra_failure_retains_pdf_verdicts() -> None:
    with (
        patch(
            f"{_REVIEW}._invoke",
            side_effect=[
                _comment("Add a note", "Add a note"),
                _verdict("open", "Old note remains", "Add the requested note"),
            ],
        ),
        patch(f"{_REVIEW}._encode", return_value="data:image/png;base64,test"),
        patch(
            f"{_REVIEW}._extra_issues", side_effect=RuntimeError("auxiliary failure")
        ),
    ):
        result = verify_sheet_comments(
            _pages(1),
            _pages(1),
            commented_name="original.pdf",
            revised_name="revised.pdf",
            dxf_summary=None,
            llm=MagicMock(),
            include_extra_issues=True,
        )
    assert result.comments[0].verdict.value == "open"
    assert result.extra_issues == []
    assert "Additional-issue detection failed" in result.status


@pytest.mark.parametrize(
    "page_text,indexed_text,duplicate,span_id,status",
    [
        ("80\n100", "80", False, "pitch", CommentVerdict.SOLVED_CORRECT),
        ("08\n100", "80", False, None, CommentVerdict.SOLVED_CORRECT),
        ("180\n100", "180", False, "pitch", CommentVerdict.UNCLEAR),
        ("80\n80", "80", True, None, CommentVerdict.UNCLEAR),
        ("80\n80", "80", True, "pitch", CommentVerdict.SOLVED_CORRECT),
    ],
)
def test_short_dimension_evidence_requires_an_exact_unique_after_span(
    page_text: str,
    indexed_text: str,
    duplicate: bool,
    span_id: str | None,
    status: CommentVerdict,
) -> None:
    from onyx.llm.models import ImageContentPart
    from onyx.tools.tool_implementations.drawing_review.comment_review import (
        _judge_comment,
    )

    spans = [SheetSpan("pitch", 1, indexed_text, 0.2, 0.2, 0.1, 0.1)]
    if duplicate:
        spans.append(SheetSpan("other", 1, "80", 0.6, 0.6, 0.1, 0.1))
    row = comment_from_extraction(
        ExtractedComment(
            text="Circled 90 with red 80", request="Change hole pitch from 90 to 80"
        ),
        comment_id="c1",
        page=1,
        spans={},
    )
    llm = _llm(
        [
            json.dumps(
                {
                    "status": "solved_correct",
                    "evidence": "80",
                    "remaining": "",
                    "span_id": span_id,
                }
            )
        ]
    )
    with patch(
        f"{_REVIEW}.prepare_image_bytes", return_value="data:image/png;base64,aa"
    ):
        verdict = _judge_comment(
            llm,
            b"after",
            filename="after.pdf",
            page_number=1,
            page_count=1,
            comment=row,
            spans=spans,
            dxf_summary=None,
            revised_page_text=page_text,
            original_image_data=b"before",
        )
    assert verdict is not None and verdict.status == status
    if status == CommentVerdict.SOLVED_CORRECT:
        assert verdict.span_id == "pitch"
    sent = llm.invoke.call_args.args[0].messages[1].content
    assert sum(isinstance(part, ImageContentPart) for part in sent) == 2


def test_visual_markups_supplement_native_comments_without_dropping_them() -> None:
    native = ExtractedComment(text="Add a finish note", request="Add clear anodize")
    llm = _llm(
        [
            json.dumps(
                {
                    "comments": [
                        {
                            "text": "Circled 120 with red 100 below",
                            "request": "Change overall width from 120 to 100",
                            "ambiguity": "",
                        }
                    ]
                }
            ),
            _verdict("solved_correct", "Clear anodize", ""),
            _verdict("open", "Overall width 120", "Change width to 100"),
        ]
    )
    with patch(
        f"{_REVIEW}.prepare_image_bytes", return_value="data:image/png;base64,aa"
    ):
        result = verify_sheet_comments(
            _pages(1),
            _pages(1),
            commented_name="before.pdf",
            revised_name="after.pdf",
            dxf_summary=None,
            llm=llm,
            native_comments={1: [native]},
            include_extra_issues=False,
        )
    assert [row.text for row in result.comments] == [
        "Add a finish note",
        "Circled 120 with red 100 below",
    ]
    assert [row.verdict for row in result.comments] == [
        CommentVerdict.SOLVED_CORRECT,
        CommentVerdict.OPEN,
    ]


def test_ambiguous_visual_mark_remains_in_queue_without_a_guessed_verdict() -> None:
    llm = _llm(
        [
            json.dumps(
                {
                    "comments": [
                        {
                            "text": "Circle around a hole",
                            "request": "Confirm the marked feature",
                            "ambiguity": "No replacement value or requested operation is visible.",
                        }
                    ]
                }
            ),
            _verdict(
                "unclear",
                "none",
                "No replacement value or requested operation is visible.",
            ),
        ]
    )
    with patch(
        f"{_REVIEW}.prepare_image_bytes", return_value="data:image/png;base64,aa"
    ):
        result = verify_sheet_comments(
            _pages(1),
            _pages(1),
            commented_name="before.pdf",
            revised_name="after.pdf",
            dxf_summary=None,
            llm=llm,
            include_extra_issues=False,
        )
    assert result.comments[0].verdict == CommentVerdict.UNCLEAR
    assert "No replacement value" in result.comments[0].remaining
    assert llm.invoke.call_count == 2


def test_delegated_review_preserves_scope_and_recovers_from_pdf_text_failure() -> None:
    from onyx.llm.models import TextContentPart
    from onyx.utils.process_isolation import IsolatedProcessTimeout

    tool = CommentReviewTool(tool_id=8, user_file_ids=[], chat_file_ids=[])
    user_request = "Only check page 2 and verify my marked width."
    instructions = "Find the circled width and verify 200 on the same feature."
    revised = _SheetPages(
        pages=[b"page", b"page"],
        spans=[SheetSpan("width", 2, "200", 0.2, 0.2, 0.1, 0.1)],
        truncated_pages=[],
        total=2,
    )
    llm = _llm(
        [
            json.dumps(
                {
                    "comments": [
                        {
                            "text": "Circled 500 with 200 beside it",
                            "request": "Change the width from 500 to 200",
                            "requested_value": "200",
                        }
                    ]
                }
            ),
            json.dumps(
                {
                    "status": "solved_correct",
                    "evidence": "200",
                    "remaining": "",
                    "span_id": "width",
                }
            ),
        ]
    )
    llm.config.model_name = "test-vision"
    updates = MagicMock()
    with (
        patch.object(
            tool,
            "_load_sheet",
            side_effect=[(b"before", "before.pdf"), (b"after", "after.pdf")],
        ),
        patch(f"{_TOOL}._sheet_pages", side_effect=[_pages(2), revised]),
        patch(
            f"{_TOOL}.run_in_isolated_process",
            side_effect=[(2, {}), IsolatedProcessTimeout(30), (2, {})],
        ),
        patch(f"{_TOOL}.get_default_llm_with_vision", return_value=llm),
        patch(
            f"{_REVIEW}.prepare_image_bytes", return_value="data:image/png;base64,aa"
        ),
    ):
        result = tool._run(
            ToolInvocation(
                call_id="comments",
                cancellation=CancellationSignal(),
                update=updates,
                arguments={
                    "commented_sheet_file_id": str(uuid4()),
                    "revised_sheet_file_id": str(uuid4()),
                    "review_instructions": instructions,
                    "original_pages": [2],
                    "include_extra_issues": False,
                },
            ),
            ToolContext(user_request=user_request),
        )
    assert isinstance(result.details, CommentReviewResult)
    assert [(row.page, row.verdict) for row in result.details.comments] == [
        (2, CommentVerdict.SOLVED_CORRECT)
    ]
    assert result.details.comments[0].revised_span_id == "width"
    snapshot = updates.call_args.args[0].details
    assert isinstance(snapshot, CommentReviewResult)
    assert snapshot.comments == result.details.comments
    assert snapshot.status == "Reviewed 1 comments"
    assert result.details.reviewed_pages == 1
    assert "revised_text_extraction_failed" in result.content
    assert llm.invoke.call_count == 2
    for call in llm.invoke.call_args_list:
        message = call.args[0].messages[1]
        assert isinstance(message, UserMessage) and isinstance(message.content, list)
        text = "\n".join(
            part.text for part in message.content if isinstance(part, TextContentPart)
        )
        assert user_request in text
        assert instructions in text


def test_review_deadline_returns_explicit_incomplete_result() -> None:
    llm = MagicMock()
    with patch(f"{_REVIEW}._REVIEW_TIMEOUT", 0):
        result = verify_sheet_comments(
            _pages(1),
            _pages(1),
            commented_name="original.pdf",
            revised_name="revised.pdf",
            dxf_summary=None,
            llm=llm,
        )
    llm.invoke.assert_not_called()
    assert result.reviewed_pages == 0
    assert result.comments[0].verdict == CommentVerdict.UNCLEAR
    assert "time limit" in result.report


@pytest.mark.parametrize("confirmed", [True, False])
def test_visual_mismatch_keeps_evidence_without_fabricating_text_anchor(
    confirmed: bool,
) -> None:
    from onyx.tools.tool_implementations.drawing_review.comment_review import (
        _judge_comment,
    )

    row = comment_from_extraction(
        ExtractedComment(
            text="86", request="Set overall height to 86", requested_value="86"
        ),
        comment_id="c1",
        page=1,
        spans={},
    )
    llm = _llm(
        [
            json.dumps(
                {
                    "status": "open",
                    "evidence": "60",
                    "remaining": "Set overall height to 86; it shows 60.",
                    "evidence_source": "visual",
                    "target_description": "Overall height between top and bottom edges",
                }
            ),
            json.dumps(
                {
                    "same_target": confirmed,
                    "observed_evidence": "60",
                    "supported_status": "open",
                }
            ),
        ]
    )
    with patch(f"{_REVIEW}._encode", return_value="data:image/png;base64,test"):
        verdict = _judge_comment(
            llm,
            b"after",
            filename="after.pdf",
            page_number=1,
            page_count=1,
            comment=row,
            spans=[SheetSpan("title", 1, "VIEW A", 0.1, 0.1, 0.2, 0.1)],
            dxf_summary=None,
            revised_page_text="VIEW A",
            original_image_data=b"before",
            expected_value="86",
        )
    assert verdict is not None
    assert verdict.status == (
        CommentVerdict.OPEN if confirmed else CommentVerdict.UNCLEAR
    )
    assert verdict.evidence == "60"
    assert verdict.span_id is None
    assert "86" in verdict.remaining
    assert llm.invoke.call_count == 2


def test_text_failure_preserves_observation_and_specific_discrepancy() -> None:
    from onyx.tools.tool_implementations.drawing_review.comment_review import (
        _judge_comment,
    )

    row = comment_from_extraction(
        ExtractedComment(text="86", request="Set height to 86"),
        comment_id="c1",
        page=1,
        spans={},
    )
    with patch(f"{_REVIEW}._encode", return_value="data:image/png;base64,test"):
        verdict = _judge_comment(
            _llm([_verdict("open", "60", "Height must be 86.")]),
            b"after",
            filename="after.pdf",
            page_number=1,
            page_count=1,
            comment=row,
            spans=[],
            dxf_summary=None,
            revised_page_text="VIEW A",
            original_image_data=b"before",
        )
    assert verdict is not None and verdict.status == CommentVerdict.UNCLEAR
    assert verdict.evidence == "60"
    assert "Height must be 86" in verdict.remaining


def test_other_changes_receive_both_revisions_and_retain_partial_results() -> None:
    import time

    from onyx.llm.models import ImageContentPart
    from onyx.tools.tool_implementations.drawing_review.comment_review import (
        _scan_extra_issues,
    )

    llm = _llm(
        [
            json.dumps(
                {
                    "issues": [
                        {
                            "kind": "change",
                            "title": "Finish changed",
                            "detail": "Finish changed without a linked request.",
                            "before_evidence": "PAINT",
                            "after_evidence": "ANODIZE",
                        }
                    ],
                    "coverage_limits": [],
                }
            ),
            "invalid response",
        ]
    )
    with patch(f"{_REVIEW}._encode", return_value="data:image/png;base64,test"):
        issues, incomplete = _scan_extra_issues(
            llm,
            _pages(2),
            _pages(2),
            [],
            "after.pdf",
            "",
            set(),
            time.monotonic() + 30,
        )
    assert incomplete
    assert len(issues) == 1 and issues[0].kind == "change"
    assert issues[0].before_evidence == "PAINT"
    assert issues[0].after_evidence == "ANODIZE"
    for call in llm.invoke.call_args_list:
        content = call.args[0].messages[1].content
        assert sum(isinstance(part, ImageContentPart) for part in content) == 2


def test_other_changes_without_baseline_evidence_are_not_reported_as_verified() -> None:
    import time

    from onyx.tools.tool_implementations.drawing_review.comment_review import (
        _scan_extra_issues,
    )

    llm = _llm(
        [
            json.dumps(
                {
                    "issues": [
                        {
                            "kind": "change",
                            "title": "New hole",
                            "after_evidence": "hole",
                        }
                    ]
                }
            )
        ]
    )
    with patch(f"{_REVIEW}._encode", return_value="data:image/png;base64,test"):
        issues, incomplete = _scan_extra_issues(
            llm,
            _pages(1),
            _pages(1),
            [],
            "after.pdf",
            "",
            set(),
            time.monotonic() + 30,
        )
    assert incomplete and not issues


def test_associated_native_numeric_request_survives_missing_model_value() -> None:
    from onyx.tools.tool_implementations.drawing_review.markup_inventory import (
        merge_markups,
    )

    items = merge_markups(
        [ExtractedComment(text="86")],
        [
            ExtractedComment(
                text="height mark", request="Set overall height", native_ids=["n1"]
            )
        ],
    )
    assert len(items) == 1 and items[0].requested_value == "86"


def test_grounded_wrong_value_cannot_pass_numeric_request() -> None:
    from onyx.tools.tool_implementations.drawing_review.comment_review import (
        _enforce_numeric_request,
    )

    draft = _enforce_numeric_request(
        VerdictDraft(status=CommentVerdict.SOLVED_CORRECT, evidence="60"), "86"
    )
    assert draft.status == CommentVerdict.OPEN
    assert "Requested 86" in draft.remaining and "shows 60" in draft.remaining


def test_observed_scalar_grounds_prose_without_accepting_an_unrelated_span() -> None:
    from onyx.tools.tool_implementations.drawing_review.comment_review import (
        _judge_comment,
    )

    llm = _llm(
        [
            json.dumps(
                {
                    "status": "solved_correct",
                    "evidence": "The dimension was changed to 60.",
                    "observed_value": "60",
                    "span_id": "height",
                }
            )
        ]
    )
    row = comment_from_extraction(
        ExtractedComment(text="86", request="Set height to 86"),
        comment_id="c1",
        page=1,
        spans={},
    )
    with patch(f"{_REVIEW}._encode", return_value="data:image/png;base64,test"):
        verdict = _judge_comment(
            llm,
            b"after",
            filename="after.pdf",
            page_number=1,
            page_count=1,
            comment=row,
            spans=[SheetSpan("height", 1, "60", 0.1, 0.2, 0.1, 0.1)],
            dxf_summary=None,
            expected_value="86",
            revised_page_text="60",
        )
    assert verdict is not None and verdict.status == CommentVerdict.OPEN
    assert verdict.evidence == "60"


def test_native_recovery_reads_the_selected_span_instead_of_model_prose() -> None:
    from onyx.llm.models import ImageContentPart, ImageUrlDetail
    from onyx.tools.tool_implementations.drawing_review.comment_review import (
        _recover_native_callout,
    )

    row = comment_from_extraction(
        ExtractedComment(text="requested value", request="Set marked height"),
        comment_id="c1",
        page=1,
        spans={},
    )
    llm = _llm(
        [
            json.dumps(
                {
                    "span_id": "height",
                    "target_description": "Right view overall height",
                    "status": "open",
                    "remaining": [],
                }
            )
        ]
    )
    recovered = _recover_native_callout(
        llm,
        [ImageContentPart(image_url=ImageUrlDetail(url="data:image/png;base64,test"))],
        "data:image/png;base64,test",
        row,
        [SheetSpan("height", 1, "45", 0.1, 0.1, 0.1, 0.1)],
        filename="after.pdf",
        page_number=1,
        deadline=None,
    )
    assert recovered is not None and recovered.evidence == "45"
    assert recovered.status == CommentVerdict.OPEN
