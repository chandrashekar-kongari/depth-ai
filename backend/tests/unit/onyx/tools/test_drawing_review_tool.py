import json
import os
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import ezdxf
import pytest
from pydantic import JsonValue
from pypdf import PdfWriter

from onyx.agents.tools import ToolInvocation
from onyx.chat.prompt_utils import prepare_prompt
from onyx.context.search.models import PersonaSearchInfo
from onyx.file_store.models import FileToolMetadata
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolResult, UserMessage
from onyx.tools.models import (
    DrawingFindingCategory,
    DrawingFindingStatus,
    DrawingReviewResult,
    ToolCallException,
    ToolContext,
)
from onyx.tools.tool_implementations.drawing_review.checklist import (
    ChecklistItem,
    resolve_findings,
)
from onyx.tools.tool_implementations.drawing_review.drawing_review_tool import (
    DrawingReviewTool,
)
from onyx.tools.tool_implementations.drawing_review.spans import (
    SheetSpan,
    extract_page_spans,
)
from onyx.tools.tool_implementations.drawing_review.standards import (
    NO_COMPANY_STANDARD,
    StandardExcerpt,
)

_SHEET = "onyx.tools.tool_implementations.drawing_review.sheet"


@pytest.fixture(autouse=True)
def _sheet_renderer_can_import_onyx(monkeypatch: pytest.MonkeyPatch) -> None:
    """The PDF renderer runs in a child process. Pytest's pythonpath does not."""
    backend = Path(__file__).resolve().parents[4]
    current = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH",
        str(backend) if not current else os.pathsep.join((str(backend), current)),
    )


def _sample_dxf() -> bytes:
    document = ezdxf.new(dxfversion="R2010")
    document.header["$INSUNITS"] = 4
    model = document.modelspace()
    model.add_text(
        "25.4",
        dxfattribs={"insert": (0, 0), "height": 2.5, "layer": "NOTES"},
    )
    dimension = model.add_linear_dim(
        base=(0, 10),
        p1=(0, 0),
        p2=(25.4, 0),
        dxfattribs={"layer": "DIMS"},
    )
    dimension.render()
    buffer = StringIO()
    document.write(buffer)
    return buffer.getvalue().encode()


def _one_page_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _file_arguments(dxf_file_id: str, sheet_file_id: str) -> dict[str, JsonValue]:
    return {"dxf_file_id": dxf_file_id, "sheet_file_id": sheet_file_id}


def _invocation(arguments: dict[str, JsonValue]) -> ToolInvocation:
    return ToolInvocation(
        call_id="review",
        arguments=arguments,
        cancellation=CancellationSignal(),
        update=lambda _progress: None,
    )


def test_review_keeps_dxf_measurements_apart_from_sheet_comments() -> None:
    dxf_id = uuid4()
    sheet_id = uuid4()
    files = {
        str(dxf_id): (_sample_dxf(), "part.dxf"),
        str(sheet_id): (_one_page_pdf(), "sheet.pdf"),
    }
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(
        text=json.dumps(
            {
                "items": [
                    {
                        "category": "title_block",
                        "status": "fail",
                        "span_id": "missing",
                        "title": "Title block is missing a revision.",
                        "detail": "The revision field is blank.",
                        "evidence": "25.4",
                        "source": "observed",
                    }
                ]
            }
        )
    )
    tool = DrawingReviewTool(
        tool_id=7,
        user_file_ids=[dxf_id, sheet_id],
        chat_file_ids=[],
    )

    with (
        patch.object(
            DrawingReviewTool, "_load_original", side_effect=lambda raw: files[raw]
        ),
        patch(f"{_SHEET}.get_default_llm_with_vision", return_value=llm),
    ):
        result = tool.run(
            invocation=_invocation(_file_arguments(str(dxf_id), str(sheet_id))),
            context=ToolContext(),
        )

    assert isinstance(result, ToolResult)
    assert isinstance(result.details, DrawingReviewResult)
    measured, observed = result.text.split("## observed", maxsplit=1)
    assert "measurement=25.4" in measured
    assert "NOTES / text: 25.4" in measured
    assert "measurement=" not in observed
    assert "visible text: 25.4" in observed
    assert "Title block is missing a revision." in result.text
    assert result.text.index("## measured") < result.text.index("## observed")
    assert NO_COMPANY_STANDARD in result.text
    finding = result.details.findings[0]
    assert finding.page_level is True
    assert finding.box is not None
    assert finding.box.width == 1
    assert finding.standard_citation == NO_COMPANY_STANDARD
    llm.invoke.assert_called_once()


def test_missing_vision_model_still_returns_the_dxf_section() -> None:
    dxf_id = uuid4()
    sheet_id = uuid4()
    files = {
        str(dxf_id): (_sample_dxf(), "part.dxf"),
        str(sheet_id): (_one_page_pdf(), "sheet.pdf"),
    }
    tool = DrawingReviewTool(
        tool_id=7,
        user_file_ids=[dxf_id, sheet_id],
        chat_file_ids=[],
    )

    with (
        patch.object(
            DrawingReviewTool, "_load_original", side_effect=lambda raw: files[raw]
        ),
        patch(f"{_SHEET}.get_default_llm_with_vision", return_value=None),
    ):
        result = tool.run(
            invocation=_invocation(_file_arguments(str(dxf_id), str(sheet_id))),
            context=ToolContext(),
        )

    assert isinstance(result, ToolResult)
    assert "measurement=25.4" in result.text
    assert "No Captioning LLM is set" in result.text


def test_review_requires_a_file_id() -> None:
    tool = DrawingReviewTool(tool_id=7, user_file_ids=[], chat_file_ids=[])

    empty: dict[str, JsonValue] = {}
    with pytest.raises(ToolCallException):
        tool._run(invocation=_invocation(empty), context=ToolContext())


def test_prompt_lists_drawing_file_ids_when_the_tool_is_offered() -> None:
    metadata = {
        "abc": FileToolMetadata(
            file_id="abc",
            filename="part.dxf",
            approx_char_count=20,
        )
    }

    listed = prepare_prompt(
        [UserMessage(content="Review this drawing")],
        system_prompt=None,
        custom_agent_prompt=None,
        reminder_message=None,
        context_files=None,
        token_counter=len,
        all_injected_file_metadata=metadata,
        available_tool_names={"review_drawing"},
    )
    hidden = prepare_prompt(
        [UserMessage(content="Review this drawing")],
        system_prompt=None,
        custom_agent_prompt=None,
        reminder_message=None,
        context_files=None,
        token_counter=len,
        all_injected_file_metadata=metadata,
        available_tool_names=set(),
    )

    listed_text = "\n".join(message.text for message in listed)
    hidden_text = "\n".join(message.text for message in hidden)
    assert 'file_id="abc"' in listed_text
    assert "part.dxf" in listed_text
    assert 'file_id="abc"' not in hidden_text


def test_known_span_becomes_a_box_and_unknown_span_covers_the_page() -> None:
    span = SheetSpan("p1s0", 1, "REV A", 0.1, 0.2, 0.3, 0.05)
    findings = resolve_findings(
        [
            ChecklistItem(
                category=DrawingFindingCategory.TITLE_BLOCK,
                status=DrawingFindingStatus.FAIL,
                span_id="p1s0",
                title="Revision is present.",
                evidence="REV A",
            ),
            ChecklistItem(
                category=DrawingFindingCategory.TITLE_BLOCK,
                status=DrawingFindingStatus.NEEDS_REVIEW,
                span_id="missing",
                title="Scale is unclear.",
                evidence="none",
            ),
            ChecklistItem(
                category=DrawingFindingCategory.TITLE_BLOCK,
                status=DrawingFindingStatus.PASS,
                span_id="p1s0",
                title="The title is present.",
                evidence="REV A",
            ),
        ],
        {"p1s0": span},
        page=1,
        allowed={DrawingFindingCategory.TITLE_BLOCK},
        standards=[],
        id_start=0,
    )

    known, unknown, passed = findings
    assert known.box is not None
    assert known.box.x == 0.1
    assert known.box.y == 0.2
    assert known.page_level is False
    assert known.span_id == "p1s0"
    assert unknown.page_level is True
    assert unknown.box is not None
    assert unknown.box.width == 1
    assert unknown.span_id is None
    assert passed.box is None
    assert passed.page_level is False
    assert all(item.standard_citation == NO_COMPANY_STANDARD for item in findings)


def test_pdf_characters_become_a_word_box() -> None:
    class _TextPage:
        def count_chars(self) -> int:
            return 5

        def get_text_range(
            self, index: int = 0, count: int = -1, errors: str = "ignore"
        ) -> str:
            del count, errors
            return "REV A"[index]

        def get_charbox(
            self, index: int, loose: bool = False
        ) -> tuple[float, float, float, float]:
            del loose
            if index == 3:
                return (40.0, 100.0, 44.0, 112.0)
            left = 10.0 + index * 8
            return (left, 100.0, left + 6.0, 112.0)

        def close(self) -> None:
            return None

    class _Page:
        def get_size(self) -> tuple[float, float]:
            return (200.0, 200.0)

        def get_textpage(self) -> _TextPage:
            return _TextPage()

    spans, truncated = extract_page_spans(_Page(), 1)
    assert truncated is False
    assert [span.text for span in spans] == ["REV", "A"]
    assert spans[0].span_id == "p1s0"
    assert spans[0].y < 1
    assert spans[0].width > 0


def test_empty_document_sets_do_not_search() -> None:
    dxf_id = uuid4()
    sheet_id = uuid4()
    files = {
        str(dxf_id): (_sample_dxf(), "part.dxf"),
        str(sheet_id): (_one_page_pdf(), "sheet.pdf"),
    }
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(text='{"items": []}')
    tool = DrawingReviewTool(
        tool_id=7,
        user_file_ids=[dxf_id, sheet_id],
        chat_file_ids=[],
        user=MagicMock(),
        persona_search_info=PersonaSearchInfo(
            document_set_names=[],
            search_start_date=None,
            attached_document_ids=[],
            hierarchy_node_ids=[],
        ),
        document_index=MagicMock(),
    )

    with (
        patch.object(
            DrawingReviewTool, "_load_original", side_effect=lambda raw: files[raw]
        ),
        patch(f"{_SHEET}.get_default_llm_with_vision", return_value=llm),
        patch(
            "onyx.tools.tool_implementations.drawing_review.standards.search_pipeline"
        ) as search,
    ):
        result = tool.run(
            invocation=_invocation(_file_arguments(str(dxf_id), str(sheet_id))),
            context=ToolContext(),
        )

    search.assert_not_called()
    assert isinstance(result, ToolResult)
    assert isinstance(result.details, DrawingReviewResult)
    assert NO_COMPANY_STANDARD in result.text


def test_finding_keeps_a_citation_that_names_a_retrieved_standard() -> None:
    dxf_id = uuid4()
    sheet_id = uuid4()
    files = {
        str(dxf_id): (_sample_dxf(), "part.dxf"),
        str(sheet_id): (_one_page_pdf(), "sheet.pdf"),
    }
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(
        text=json.dumps(
            {
                "items": [
                    {
                        "category": "dimensions",
                        "status": "needs_review",
                        "span_id": None,
                        "title": "The tolerance is tight.",
                        "detail": "A machined hole uses a tight position.",
                        "evidence": "0.001",
                        "source": "observed",
                        "standard_citation": "Machining standard: relax the tolerance.",
                    },
                    {
                        "category": "views",
                        "status": "fail",
                        "span_id": None,
                        "title": "A view is missing.",
                        "detail": "The side view is not on the sheet.",
                        "evidence": "none",
                        "source": "observed",
                        "standard_citation": "ASME Y14.5",
                    },
                ]
            }
        )
    )
    tool = DrawingReviewTool(
        tool_id=7,
        user_file_ids=[dxf_id, sheet_id],
        chat_file_ids=[],
    )

    with (
        patch.object(
            DrawingReviewTool, "_load_original", side_effect=lambda raw: files[raw]
        ),
        patch(f"{_SHEET}.get_default_llm_with_vision", return_value=llm),
        patch(
            "onyx.tools.tool_implementations.drawing_review.drawing_review_tool.retrieve_drawing_standards",
            return_value=[
                StandardExcerpt(title="Machining standard", text="Use 0.005 inch.")
            ],
        ),
    ):
        result = tool.run(
            invocation=_invocation(_file_arguments(str(dxf_id), str(sheet_id))),
            context=ToolContext(),
        )

    assert isinstance(result, ToolResult)
    assert isinstance(result.details, DrawingReviewResult)
    cited = result.details.findings[0]
    unused = result.details.findings[1]
    assert cited.standard_citation == "Machining standard: relax the tolerance."
    assert unused.standard_citation == NO_COMPANY_STANDARD
    assert "visible text: 0.001" in result.text
    assert "measurement=25.4" in result.text.split("## observed", maxsplit=1)[0]
