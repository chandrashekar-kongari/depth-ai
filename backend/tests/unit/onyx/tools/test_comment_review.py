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
    assert llm.invoke.call_count == 5


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
    assert llm.invoke.call_count == 4


def test_missing_sheet_tells_the_model_which_file_to_pass() -> None:
    tool = CommentReviewTool(tool_id=8, user_file_ids=[], chat_file_ids=[])
    with pytest.raises(ToolCallException) as caught:
        tool._run(invocation=_invocation({}), context=ToolContext())
    message = caught.value.llm_facing_message
    assert "commented_sheet_file_id" in message
    assert "revised_sheet_file_id" in message


def test_reversed_pdf_roles_are_rejected_before_vision_review() -> None:
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
    model.assert_not_called()


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
        )
    assert result.comments[0].verdict.value == "open"
    assert result.extra_issues == []
    assert "Additional-issue detection failed" in result.status
