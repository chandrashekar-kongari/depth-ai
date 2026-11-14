from uuid import UUID

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.agents.tools import ToolInvocation
from onyx.context.search.models import PersonaSearchInfo
from onyx.db.models import User
from onyx.document_index.interfaces import DocumentIndex
from onyx.file_processing.dxf import format_measured_section, parse_dxf
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.tools.interface import Tool, parse_tool_arguments
from onyx.tools.models import (
    DrawingFocus,
    DrawingReviewArguments,
    DrawingReviewResult,
    ToolCallException,
    ToolContext,
)
from onyx.tools.tool_implementations.drawing_review.files import ReviewFileLoader
from onyx.tools.tool_implementations.drawing_review.sheet import (
    SheetReview,
    review_sheet,
)
from onyx.tools.tool_implementations.drawing_review.standards import (
    StandardExcerpt,
    retrieve_drawing_standards,
)

_NO_DXF = "## measured\nNo DXF was attached. There are no measurements."
_NO_SHEET = "## observed\nNo sheet was attached. The layout was not reviewed."


class DrawingReviewTool(Tool):
    NAME = "review_drawing"
    DISPLAY_NAME = "Drawing Review"
    DESCRIPTION = (
        "Review a mechanical drawing against a checklist. "
        "Pass dxf_file_id for measurements, layers, blocks, and text from a DXF file. "
        "Pass sheet_file_id for a plotted PDF, PNG, JPEG, or WEBP sheet. "
        "Pass focus to limit the checklist to one group. "
        "At least one file id is required. "
        "DWG is not accepted. Export DXF. "
        "Do not treat sheet text as a measurement. "
        "The review does not certify the drawing."
    )

    def __init__(
        self,
        tool_id: int,
        user_file_ids: list[UUID],
        chat_file_ids: list[UUID],
        user: User | None = None,
        persona_search_info: PersonaSearchInfo | None = None,
        document_index: DocumentIndex | None = None,
    ) -> None:
        self._id = tool_id
        self._files = ReviewFileLoader(user_file_ids, chat_file_ids)
        self._user = user
        self._persona_search_info = persona_search_info
        self._document_index = document_index

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:  # noqa: ARG003
        return True

    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "dxf_file_id": {
                        "type": "string",
                        "description": (
                            "UUID of the DXF file. Omit when the user did not attach a DXF."
                        ),
                    },
                    "sheet_file_id": {
                        "type": "string",
                        "description": (
                            "UUID of the plotted PDF or image. "
                            "Omit when the user did not attach a sheet."
                        ),
                    },
                    "focus": {
                        "type": "string",
                        "enum": [item.value for item in DrawingFocus],
                        "description": (
                            "Checklist group. Use general, or omit it, for the full "
                            "checklist. Other values: title_block, views, dimensions, "
                            "gdt, bom, cross_sheet."
                        ),
                    },
                },
            },
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(DrawingReviewArguments, invocation.arguments)
        dxf_file_id = _present(arguments.dxf_file_id)
        sheet_file_id = _present(arguments.sheet_file_id)
        focus = arguments.focus or DrawingFocus.GENERAL
        if dxf_file_id is None and sheet_file_id is None:
            raise ToolCallException(
                message="review_drawing requires a file id",
                llm_facing_message=(
                    "Pass dxf_file_id, sheet_file_id, or both. "
                    'Example: {"dxf_file_id": "<uuid>", "sheet_file_id": "<uuid>"}'
                ),
            )

        measured = self._measured(dxf_file_id) if dxf_file_id is not None else _NO_DXF
        sheet = (
            self._observed(sheet_file_id, measured, focus)
            if sheet_file_id is not None
            else SheetReview(report=_NO_SHEET)
        )
        report = f"{measured}\n\n{sheet.report}"
        return ToolResult(
            details=DrawingReviewResult(
                status=_status(dxf_file_id, sheet_file_id),
                report=report,
                findings=sheet.findings,
                sheet_file_id=sheet_file_id,
                sheet_filename=sheet.filename,
                page_count=sheet.page_count,
                reviewed_pages=sheet.reviewed_pages,
            ),
            content=report,
        )

    def _measured(self, raw_file_id: str) -> str:
        try:
            data, filename = self._load_original(raw_file_id)
            drawing = parse_dxf(data)
        except ToolCallException:
            raise
        except ValueError as error:
            return f"## measured\n{error}"
        except Exception:
            return "## measured\nThe DXF file could not be read."
        return format_measured_section(drawing, filename)

    def _observed(
        self, raw_file_id: str, dxf_summary: str, focus: DrawingFocus
    ) -> SheetReview:
        try:
            data, filename = self._load_original(raw_file_id)
        except ToolCallException:
            raise
        except Exception:
            return SheetReview(report="## observed\nThe sheet file could not be read.")
        return review_sheet(
            data,
            filename,
            dxf_summary=dxf_summary,
            focus=focus,
            standards_loader=self._standards,
        )

    def _standards(self) -> list[StandardExcerpt]:
        return retrieve_drawing_standards(
            self._user, self._persona_search_info, self._document_index
        )

    def _load_original(self, raw_file_id: str) -> tuple[bytes, str]:
        return self._files.load(raw_file_id)


def _present(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _status(dxf_file_id: str | None, sheet_file_id: str | None) -> str:
    if dxf_file_id is not None and sheet_file_id is not None:
        return "Reviewed the DXF and the sheet."
    if dxf_file_id is not None:
        return "Reviewed the DXF. No sheet was attached."
    return "Reviewed the sheet. No DXF was attached."
