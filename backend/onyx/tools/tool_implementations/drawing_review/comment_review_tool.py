"""Check each comment on a marked sheet against a new sheet."""

import hashlib
from uuid import UUID

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.agents.tools import ToolInvocation, ToolProgress
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.user_file import get_file_id_by_user_file_id, get_user_file_metadata
from onyx.engineering.checks import ground_review_highlights
from onyx.engineering.processing import ReviewInputError, pdf_comments, pdf_texts
from onyx.engineering.review_checkpoint import ReviewCheckpoint
from onyx.file_processing.dxf import format_measured_section, parse_dxf
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.utils import load_chat_file_by_id
from onyx.llm.factory import get_default_llm_with_vision
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.tools.interface import Tool, parse_tool_arguments
from onyx.tools.models import (
    CommentReviewArguments,
    DrawingComment,
    ToolCallException,
    ToolContext,
)
from onyx.tools.tool_implementations.drawing_review.comment_queue import empty_result
from onyx.tools.tool_implementations.drawing_review.comment_review import (
    verify_sheet_comments,
)
from onyx.tools.tool_implementations.drawing_review.sheet import _sheet_pages
from onyx.utils.logger import setup_logger
from onyx.utils.process_isolation import run_in_isolated_process

logger = setup_logger()

_SHEET_ERROR = (
    "Pass commented_sheet_file_id for the marked-up PDF, PNG, JPEG, or WEBP. "
    "Pass revised_sheet_file_id for the new sheet in those formats. "
    "PDF plus PDF is supported. A DXF is optional and is not a replacement sheet. "
    "Never convert a PDF to DXF to fix an internal processing error. "
    "Pass dxf_file_id only for an optional source CAD drawing. "
    "DWG and STEP are not accepted. Export DXF."
)


class CommentReviewTool(Tool):
    NAME = "verify_drawing_comments"
    DISPLAY_NAME = "Comment Review"
    DESCRIPTION = (
        "Check each comment on a marked-up drawing against a new drawing. "
        "Pass commented_sheet_file_id for the marked-up PDF, PNG, JPEG, or WEBP. "
        "Pass revised_sheet_file_id for the new sheet in those formats. "
        "Check the file names and roles before calling; do not reverse the original with comments and the corrected revision. "
        "Pass dxf_file_id when the new drawing has a DXF and a comment is about a dimension. "
        "PDF plus PDF is supported without a DXF. "
        "An internal tool error does not mean PDF is unsupported; never recommend a PDF-to-DXF conversion to fix it. "
        "The structured result automatically displays status marks in the PDF viewer. "
        "A number in a comment is not a measurement. "
        "DWG and STEP are not accepted. "
        "The review does not certify the drawing."
    )

    def __init__(
        self,
        tool_id: int,
        user_file_ids: list[UUID],
        chat_file_ids: list[UUID],
        owner_id: UUID | None = None,
    ) -> None:
        self._id = tool_id
        self._owner_id = owner_id
        self._user_file_ids = set(user_file_ids)
        self._chat_file_ids = set(chat_file_ids)
        self._chat_file_id_strings = {str(file_id) for file_id in chat_file_ids}

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
                    "commented_sheet_file_id": {
                        "type": "string",
                        "description": (
                            "UUID of the marked-up PDF or image. "
                            "This sheet has the review comments."
                        ),
                    },
                    "revised_sheet_file_id": {
                        "type": "string",
                        "description": (
                            "UUID of the new PDF or image. "
                            "Check each comment against this sheet."
                        ),
                    },
                    "dxf_file_id": {
                        "type": "string",
                        "description": (
                            "UUID of the new drawing's DXF. "
                            "Omit it when the user did not attach a DXF."
                        ),
                    },
                },
                "required": ["commented_sheet_file_id", "revised_sheet_file_id"],
            },
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(CommentReviewArguments, invocation.arguments)
        commented_id = _present(arguments.commented_sheet_file_id)
        revised_id = _present(arguments.revised_sheet_file_id)
        dxf_id = _present(arguments.dxf_file_id)
        if commented_id is None or revised_id is None:
            raise ToolCallException(
                message="verify_drawing_comments requires both sheets",
                llm_facing_message=_SHEET_ERROR,
            )

        commented_bytes, commented_name = self._load_sheet(commented_id, "commented")
        revised_bytes, revised_name = self._load_sheet(revised_id, "revised")
        commented_pages = _sheet_pages(commented_bytes, commented_name)
        revised_pages = _sheet_pages(revised_bytes, revised_name)
        if commented_pages.error is not None or revised_pages.error is not None:
            report = "\n".join(
                item
                for item in (commented_pages.error, revised_pages.error)
                if item is not None
            )
            result = empty_result(
                status=report,
                report=f"{report}\n\n{_SHEET_ERROR}",
                commented_sheet_file_id=commented_id,
                commented_sheet_filename=commented_name,
                revised_sheet_file_id=revised_id,
                revised_sheet_filename=revised_name,
            )
            return ToolResult(details=result, content=result.report)

        native_comments = None
        revised_text = None
        if commented_name.lower().endswith(".pdf") and commented_pages.total <= 8:
            try:
                _, native_comments = run_in_isolated_process(
                    pdf_comments, commented_bytes, timeout=30
                )
            except ReviewInputError:
                native_comments = None
        if revised_name.lower().endswith(".pdf") and revised_pages.total <= 8:
            revised_text = run_in_isolated_process(pdf_texts, revised_bytes, timeout=30)

        if native_comments == {} and revised_name.lower().endswith(".pdf"):
            try:
                _, revised_comments = run_in_isolated_process(
                    pdf_comments, revised_bytes, timeout=30
                )
            except ReviewInputError:
                revised_comments = {}
            if revised_comments:
                logger.warning("Comment review rejected likely reversed sheet roles")
                raise ToolCallException(
                    message="Drawing sheet roles appear reversed",
                    llm_facing_message=(
                        f"'{commented_name}' was passed as the marked original but has no native review comments. "
                        f"'{revised_name}' was passed as the revised sheet and contains native review comments. "
                        "The file roles appear reversed. Check the file names and retry with "
                        f"commented_sheet_file_id='{revised_id}' and revised_sheet_file_id='{commented_id}' "
                        "if these are the original reviewed sheet and corrected revision. "
                        "No review was completed. PDFs are supported; no DXF or conversion is required."
                    ),
                )

        logger.info(
            "Comment review inputs: original_pages=%s revised_pages=%s native_comments=%s",
            commented_pages.total,
            revised_pages.total,
            sum(len(items) for items in native_comments.values())
            if native_comments is not None
            else "unavailable",
        )

        vision_llm = get_default_llm_with_vision(temperature=0)
        measured = self._measured(dxf_id) if dxf_id is not None else None
        checkpoint = None
        if (
            self._owner_id is not None
            and vision_llm is not None
            and isinstance(vision_llm.config.model_name, str)
        ):
            source_hash = hashlib.sha256(
                commented_bytes + revised_bytes + (measured or "").encode()
            ).hexdigest()
            checkpoint = ReviewCheckpoint(
                f"{self._owner_id}:{source_hash}:{vision_llm.config.model_name}"
            )
        reviewed = 0
        total = (
            sum(len(items) for items in native_comments.values())
            if native_comments and len(native_comments) == len(commented_pages.pages)
            else None
        )

        def save_progress(comment: DrawingComment) -> None:
            nonlocal reviewed
            if checkpoint:
                checkpoint.write(comment)
            reviewed += 1
            progress = (
                f"Reviewed {reviewed} of {total} comments"
                if total is not None
                else f"Reviewed {reviewed} comments"
            )
            invocation.update(ToolProgress(content=progress))

        result = verify_sheet_comments(
            commented_pages,
            revised_pages,
            commented_name=commented_name,
            revised_name=revised_name,
            dxf_summary=measured,
            checkpoint_read=checkpoint.read if checkpoint else None,
            checkpoint_write=save_progress,
            llm=vision_llm,
            native_comments=native_comments,
            revised_text_by_page=revised_text,
            commented_sheet_file_id=commented_id,
            revised_sheet_file_id=revised_id,
        )
        result = ground_review_highlights(result, revised_pages.spans)
        if not result.comments:
            logger.warning("Comment review produced zero comments; no review completed")
            raise ToolCallException(
                message="No drawing comments could be reviewed",
                llm_facing_message=(
                    f"No comments were extracted from the marked input '{commented_name}'. "
                    f"The revised input was '{revised_name}'. No review was completed. "
                    "Check the file roles against the attached file names. "
                    "If the roles are correct, comment extraction did not find reviewable comments; "
                    "do not claim the drawing passed or that all issues were fixed. "
                    "PDF review does not require DXF. Missing CAD measurements did not cause this result."
                ),
            )
        if vision_llm is not None:
            result = result.model_copy(
                update={"vision_model": vision_llm.config.model_name}
            )
        return ToolResult(details=result, content=result.report)

    def _load_sheet(self, raw_file_id: str, role: str) -> tuple[bytes, str]:
        data, filename = self._load_original(raw_file_id)
        if not _is_sheet(filename):
            argument = (
                "commented_sheet_file_id"
                if role == "commented"
                else "revised_sheet_file_id"
            )
            raise ToolCallException(
                message=f"{filename} is not a sheet",
                llm_facing_message=(
                    f"{argument} must be a PDF, PNG, JPEG, or WEBP. "
                    f"'{filename}' is not a sheet. {_SHEET_ERROR}"
                ),
            )
        return data, filename

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


def _is_sheet(filename: str) -> bool:
    extension = get_file_ext(filename)
    return extension == ".pdf" or extension in OnyxFileExtensions.IMAGE_EXTENSIONS


def _read_user_file(user_file_id: UUID) -> tuple[bytes, str]:
    with get_session_with_current_tenant() as db_session:
        metadata = get_user_file_metadata(user_file_id, db_session)
    content = get_default_file_store().read_file(metadata.file_id, mode="b").read()
    return content, metadata.name
