"""Check each comment on a marked sheet against a new sheet."""

import json
from uuid import UUID

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.agents.tools import ToolInvocation, ToolProgress
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.user_file import get_file_id_by_user_file_id, get_user_file_metadata
from onyx.engineering.checks import ground_review_highlights
from onyx.engineering.processing import pdf_comments, pdf_texts
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
    CommentReviewResult,
    DrawingComment,
    DrawingReviewBrief,
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
        "Check each marked change on a BEFORE drawing against the AFTER drawing. "
        "BEFORE may contain handwritten replacement values, crossed-out dimensions, arrows, circles, or graphic redlines without written instructions. "
        "Infer clear changes from drawing context; report ambiguous marks as unclear. "
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
    ) -> None:
        self._id = tool_id
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
                    "review_instructions": {
                        "type": "string",
                        "description": "Describe what to find and verify. Preserve the user's scope, target features, values, tolerances, and evidence requirements.",
                    },
                    "original_pages": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                        "description": "Original PDF page numbers, only when the user explicitly restricts the review to those pages. Omit to review all pages.",
                    },
                    "include_extra_issues": {
                        "type": "boolean",
                        "description": "Set true only when the user explicitly asks to scan for additional unrelated issues.",
                    },
                    "dxf_file_id": {
                        "type": "string",
                        "description": (
                            "UUID of the new drawing's DXF. "
                            "Omit it when the user did not attach a DXF."
                        ),
                    },
                },
                "required": [
                    "commented_sheet_file_id",
                    "revised_sheet_file_id",
                    "review_instructions",
                ],
            },
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:
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

        brief = DrawingReviewBrief(
            user_request=context.user_request[:12000],
            instructions=arguments.review_instructions.strip(),
            original_pages=sorted(set(arguments.original_pages)),
            include_extra_issues=arguments.include_extra_issues,
        )
        if any(
            page < 1 or page > len(commented_pages.pages)
            for page in brief.original_pages
        ):
            raise ToolCallException(
                message="Requested original pages are unavailable",
                llm_facing_message="Check the requested original PDF page numbers. "
                f"Only original pages 1 through {len(commented_pages.pages)} are available for review.",
            )

        native_comments = None
        revised_text = None
        diagnostics: list[dict[str, str]] = []
        if commented_name.lower().endswith(".pdf") and commented_pages.total <= 8:
            try:
                _, native_comments = run_in_isolated_process(
                    pdf_comments, commented_bytes, timeout=30
                )
            except Exception:
                logger.warning(
                    "Original annotation extraction failed; using visual discovery",
                    exc_info=True,
                )
                diagnostics.append(
                    {
                        "code": "original_annotation_extraction_failed",
                        "recovery": "visual_markup_discovery",
                    }
                )
        if revised_name.lower().endswith(".pdf") and revised_pages.total <= 8:
            try:
                revised_text = run_in_isolated_process(
                    pdf_texts, revised_bytes, timeout=30
                )
            except Exception:
                logger.warning(
                    "Revised text extraction failed; using indexed spans and visual evidence",
                    exc_info=True,
                )
                diagnostics.append(
                    {
                        "code": "revised_text_extraction_failed",
                        "recovery": "indexed_spans_and_visual_review",
                    }
                )
                invocation.update(
                    ToolProgress(
                        content="Revised text extraction failed. Checking indexed spans and drawing images."
                    )
                )
            indexed_text: dict[int, list[str]] = {}
            for span in revised_pages.spans:
                indexed_text.setdefault(span.page, []).append(span.text)
            revised_text = revised_text or {}
            for page, lines in indexed_text.items():
                if not revised_text.get(page, "").strip():
                    revised_text[page] = "\n".join(lines)

        revised_comments = {}
        if native_comments == {} and revised_name.lower().endswith(".pdf"):
            try:
                _, revised_comments = run_in_isolated_process(
                    pdf_comments, revised_bytes, timeout=30
                )
            except Exception:
                logger.warning(
                    "Could not check revised annotations for reversed roles",
                    exc_info=True,
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
        findings: list[DrawingComment] = []
        model_name = vision_llm.config.model_name if vision_llm else None

        def report_progress(comment: DrawingComment) -> None:
            findings.append(comment)
            progress = f"Reviewed {len(findings)} comments"
            snapshot = CommentReviewResult(
                status=progress,
                report="",
                comments=list(findings),
                vision_model=model_name,
                commented_sheet_file_id=commented_id,
                commented_sheet_filename=commented_name,
                revised_sheet_file_id=revised_id,
                revised_sheet_filename=revised_name,
                commented_page_count=commented_pages.total,
                revised_page_count=revised_pages.total,
            )
            invocation.update(
                ToolProgress(
                    content=progress,
                    details=ground_review_highlights(snapshot, revised_pages.spans),
                )
            )

        result = verify_sheet_comments(
            commented_pages,
            revised_pages,
            commented_name=commented_name,
            revised_name=revised_name,
            dxf_summary=measured,
            on_comment_reviewed=report_progress,
            llm=vision_llm,
            native_comments=native_comments,
            revised_text_by_page=revised_text,
            brief=brief,
            commented_sheet_file_id=commented_id,
            revised_sheet_file_id=revised_id,
        )
        result = ground_review_highlights(result, revised_pages.spans)
        if not result.comments:
            if native_comments == {} and revised_comments:
                raise ToolCallException(
                    message="Drawing sheet roles appear reversed",
                    llm_facing_message=(
                        f"No reviewable marks were found in '{commented_name}', while '{revised_name}' contains embedded review comments. "
                        "The roles may be reversed. Check the filenames and retry with "
                        f"commented_sheet_file_id='{revised_id}' and revised_sheet_file_id='{commented_id}' if appropriate. "
                        "No review was completed. PDFs are supported; no DXF or conversion is required."
                    ),
                )
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
        content = result.report
        if diagnostics:
            content += "\n\nReview recovery diagnostics: " + json.dumps(diagnostics)
        return ToolResult(details=result, content=content)

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
