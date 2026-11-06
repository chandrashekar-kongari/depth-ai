from uuid import UUID

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.agents.tools import ToolInvocation
from onyx.context.search.models import PersonaSearchInfo
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.db.user_file import get_file_id_by_user_file_id, get_user_file_metadata
from onyx.document_index.interfaces import DocumentIndex
from onyx.file_processing.dxf import format_measured_section, parse_dxf
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.utils import load_chat_file_by_id
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.tools.interface import Tool, parse_tool_arguments
from onyx.tools.models import (
    DrawingFocus,
    DrawingReviewArguments,
    DrawingReviewResult,
    ToolCallException,
    ToolContext,
)
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
        self._user_file_ids = set(user_file_ids)
        self._chat_file_ids = set(chat_file_ids)
        self._chat_file_id_strings = {str(file_id) for file_id in chat_file_ids}
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
        try:
            file_id = UUID(raw_file_id)
        except ValueError:
            raise ToolCallException(
                message=f"Invalid file_id: {raw_file_id}",
                llm_facing_message=f"'{raw_file_id}' is not a valid file UUID.",
            )

        if file_id in self._user_file_ids:
            return _read_user_file(file_id)
        if file_id in self._chat_file_ids:
            chat_file = load_chat_file_by_id(str(file_id))
            return chat_file.content, chat_file.filename or str(file_id)

        # Chat uploads list the UserFile id. The allowed set stores the blob id.
        with get_session_with_current_tenant() as db_session:
            blob_id = get_file_id_by_user_file_id(str(file_id), db_session)
        if blob_id is not None and blob_id in self._chat_file_id_strings:
            return _read_user_file(file_id)

        raise ToolCallException(
            message=f"File {file_id} not in available files",
            llm_facing_message=(
                f"File '{file_id}' is not available. "
                "Use a file_id from the drawing file list or an attached image tag."
            ),
        )


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


def _read_user_file(user_file_id: UUID) -> tuple[bytes, str]:
    with get_session_with_current_tenant() as db_session:
        metadata = get_user_file_metadata(user_file_id, db_session)
    content = get_default_file_store().read_file(metadata.file_id, mode="b").read()
    return content, metadata.name
