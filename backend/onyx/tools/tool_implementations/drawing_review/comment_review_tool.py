"""Check each comment on a marked sheet against a new sheet."""

import json
from hashlib import sha256
from threading import Lock
from uuid import UUID

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.agents.tools import ToolInvocation, ToolProgress
from onyx.engineering.checks import ground_review_highlights
from onyx.engineering.drawing_changes import load_drawing_evidence
from onyx.engineering.processing import pdf_comments, pdf_texts
from onyx.file_processing.extract_file_text import get_file_ext
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
from onyx.tools.tool_implementations.drawing_review.files import ReviewFileLoader
from onyx.tools.tool_implementations.drawing_review.sheet import _sheet_pages
from onyx.utils.logger import setup_logger
from onyx.utils.process_isolation import run_in_isolated_process

logger = setup_logger()

_SHEET_ERROR = (
    "Pass commented_sheet_file_id for the marked-up PDF. "
    "Pass revised_sheet_file_id for the new PDF. "
    "This review accepts two PDFs only. "
    "Never convert a PDF to DXF to fix an internal processing error. "
    "Images, DXF, DWG, and STEP are not accepted."
)


class CommentReviewTool(Tool):
    NAME = "verify_drawing_comments"
    DISPLAY_NAME = "Comment Review"
    DESCRIPTION = (
        "Check each marked change on a BEFORE drawing against the AFTER drawing. "
        "BEFORE may contain handwritten replacement values, crossed-out dimensions, arrows, circles, or graphic redlines without written instructions. "
        "Infer clear changes from drawing context; report ambiguous marks as unclear. "
        "Pass commented_sheet_file_id for the marked-up PDF. "
        "Pass revised_sheet_file_id for the new PDF. "
        "Check the file names and roles before calling; do not reverse the original with comments and the corrected revision. "
        "Use two PDFs only. Prefer CAD-exported PDFs; scanned PDFs use visual evidence. "
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
        self._pair_lock = Lock()
        self._reviewed_pairs: set[tuple[str, str]] = set()
        self._files = ReviewFileLoader(user_file_ids, chat_file_ids)

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
                            "UUID of the marked-up PDF. "
                            "This sheet has the review comments."
                        ),
                    },
                    "revised_sheet_file_id": {
                        "type": "string",
                        "description": (
                            "UUID of the new PDF. "
                            "Check each comment against this sheet."
                        ),
                    },
                    "review_instructions": {
                        "type": "string",
                        "description": "Describe what to find and verify. Preserve the user's scope, target features, values, tolerances, and evidence requirements.",
                    },
                    "confirmed_page_order": {
                        "type": "boolean",
                        "description": "Set true only if the user explicitly confirms that both PDFs have the same sheet order. Equal page counts alone do not establish order.",
                    },
                    "original_pages": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                        "description": "Original PDF page numbers, only when the user explicitly restricts the review to those pages. Omit to review all pages.",
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
        if (
            commented_id is None
            or revised_id is None
            or _present(arguments.dxf_file_id) is not None
        ):
            raise ToolCallException(
                message="verify_drawing_comments requires two PDFs only",
                llm_facing_message=_SHEET_ERROR,
            )

        commented_bytes, commented_name = self._load_sheet(commented_id, "commented")
        revised_bytes, revised_name = self._load_sheet(revised_id, "revised")
        self._claim_pair(commented_bytes, revised_bytes)
        commented_pages = _sheet_pages(
            commented_bytes, commented_name, draw_annotations=True
        )
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

        commented_bytes = commented_pages.recovered_pdf or commented_bytes
        revised_bytes = revised_pages.recovered_pdf or revised_bytes

        brief = DrawingReviewBrief(
            user_request=context.user_request[:12000],
            instructions=arguments.review_instructions.strip(),
            original_pages=sorted(set(arguments.original_pages)),
            include_extra_issues=False,
        )
        _validate_page_scope(
            brief.original_pages,
            len(commented_pages.pages),
            commented_pages.total,
            revised_pages.total,
            arguments.confirmed_page_order,
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

        drawing_evidence = None
        if (
            get_file_ext(commented_name) == ".pdf"
            and get_file_ext(revised_name) == ".pdf"
        ):
            drawing_evidence = load_drawing_evidence(
                commented_bytes,
                revised_bytes,
                brief.original_pages,
                confirmed_page_order=arguments.confirmed_page_order,
            )
        result = verify_sheet_comments(
            commented_pages,
            revised_pages,
            commented_name=commented_name,
            revised_name=revised_name,
            dxf_summary=None,
            on_comment_reviewed=report_progress,
            llm=vision_llm,
            native_comments=native_comments,
            original_pdf=commented_bytes
            if get_file_ext(commented_name) == ".pdf"
            else None,
            revised_text_by_page=revised_text,
            brief=brief,
            drawing_evidence=drawing_evidence,
            commented_sheet_file_id=commented_id,
            revised_sheet_file_id=revised_id,
        )
        result = ground_review_highlights(result, revised_pages.spans)
        result = _summarize_review(
            result,
            confirmed_page_order=arguments.confirmed_page_order,
            same_page_count=commented_pages.total == revised_pages.total,
        )
        invocation.update(ToolProgress(content=result.status, details=result))
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
            if (
                result.coverage_notices
                or (
                    result.drawing_changes
                    and result.drawing_changes.validation_status == "complete"
                )
                or (
                    result.drawing_changes
                    and any(
                        change.vision_validation == "confirmed"
                        for change in result.drawing_changes.changes
                    )
                )
            ):
                return ToolResult(details=result, content=result.report)
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

    def _claim_pair(self, commented_bytes: bytes, revised_bytes: bytes) -> None:
        first, second = sorted(
            (sha256(commented_bytes).hexdigest(), sha256(revised_bytes).hexdigest())
        )
        pair = (first, second)
        with self._pair_lock:
            if pair in self._reviewed_pairs:
                raise ToolCallException(
                    message="PDF pair already reviewed in this turn",
                    llm_facing_message="This PDF pair was already submitted in this chat turn. Use its existing review and coverage; do not call again until a new user turn.",
                )
            self._reviewed_pairs.add(pair)

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
                    f"{argument} must be a PDF. "
                    f"'{filename}' is not a sheet. {_SHEET_ERROR}"
                ),
            )
        return data, filename

    def _load_original(self, raw_file_id: str) -> tuple[bytes, str]:
        return self._files.load(raw_file_id)


def _validate_page_scope(
    pages: list[int],
    available: int,
    before: int,
    after: int,
    confirmed_page_order: bool,
) -> None:
    if any(page < 1 or page > available for page in pages):
        raise ToolCallException(
            message="Requested original pages are unavailable",
            llm_facing_message="Check the requested original PDF page numbers. "
            f"Only original pages 1 through {available} are available for review.",
        )
    if confirmed_page_order and before != after:
        raise ToolCallException(
            message="Confirmed sheet order requires equal page counts",
            llm_facing_message="The PDFs have different page counts. Use automatic sheet pairing or supply matching PDF packages.",
        )


def _summarize_review(
    result: CommentReviewResult, *, confirmed_page_order: bool, same_page_count: bool
) -> CommentReviewResult:
    comparison = result.drawing_changes
    if (
        not confirmed_page_order
        and same_page_count
        and comparison is not None
        and any(
            reason.startswith("Ambiguous sheet pairing")
            for reason in comparison.skipped_original_pages.values()
        )
    ):
        notice = "Some sheets could not be paired. Confirm that both PDFs have the same sheet order to compare them by page number."
        result = result.model_copy(
            update={
                "coverage_notices": [*result.coverage_notices, notice],
                "report": f"{result.report}\n\n{notice}",
            }
        )
    logger.info(
        "Comment review summary: findings=%d verification=%s verified_pages=%s "
        "coverage_notices=%d page_pairs=%s compared_pages=%s "
        "change_validation=%s validated_pages=%s skipped_pages=%s unmatched_revised_pages=%s",
        len(result.comments),
        result.comment_verification_status,
        result.comment_verified_pages,
        len(result.coverage_notices),
        comparison.page_pairs if comparison else None,
        comparison.compared_pages if comparison else [],
        comparison.validation_status if comparison else None,
        comparison.validated_pages if comparison else [],
        comparison.skipped_original_pages if comparison else {},
        comparison.unmatched_revised_pages if comparison else [],
    )
    return result


def _present(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _is_sheet(filename: str) -> bool:
    extension = get_file_ext(filename)
    return extension == ".pdf"
