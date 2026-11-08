"""Send plotted drawing pages to the vision model.

The DXF is not rendered. The sheet is the PDF or image the user plotted.
Checklist findings cite span ids. The server resolves those ids to boxes.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from pdfminer.pdfexceptions import PDFException
from pdfplumber.utils.exceptions import PdfminerException
from pydantic import JsonValue, ValidationError
from pypdfium2 import PdfiumError

from onyx.configs.app_configs import PDF_TEXT_EXTRACTION_TIMEOUT_SECONDS
from onyx.configs.chat_configs import IMAGE_SUMMARIZATION_TIMEOUT
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.file_processing.image_summarization import (
    UnsupportedImageFormatError,
    prepare_image_bytes,
)
from onyx.llm.factory import get_default_llm_with_vision
from onyx.llm.interfaces import LLM, GenerationContext
from onyx.llm.models import (
    GenerationOptions,
    GenerationRequest,
    ImageContentPart,
    ImageUrlDetail,
    Message,
    SystemMessage,
    TextContentPart,
    UserMessage,
)
from onyx.tools.models import DrawingFinding, DrawingFindingCategory, DrawingFocus
from onyx.tools.tool_implementations.drawing_review.checklist import (
    checklist_error_is_parse_failure,
    cross_sheet_system_prompt,
    cross_sheet_unreadable_finding,
    format_observed,
    page_categories,
    page_system_prompt,
    parse_checklist,
    resolve_findings,
    single_page_cross_sheet_finding,
    span_text,
    standards_text,
    unreadable_page_finding,
)
from onyx.tools.tool_implementations.drawing_review.pdf_recovery import (
    recover_review_pdf,
)
from onyx.tools.tool_implementations.drawing_review.spans import (
    SheetSpan,
    extract_pdf_spans,
)
from onyx.tools.tool_implementations.drawing_review.standards import StandardExcerpt
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.traces import TraceContentMode
from onyx.utils.logger import setup_logger
from onyx.utils.process_isolation import IsolatedProcessError, run_in_isolated_process

logger = setup_logger()

MAX_SHEET_PAGES = 8

_NO_VISION_MODEL = "## observed\nNo Captioning LLM is set. The sheet was not reviewed."
_NOT_A_SHEET = (
    "## observed\n"
    "The sheet must be a PDF, PNG, JPEG, or WEBP file. A DXF is not a sheet."
)
_RENDER_FAILED = "## observed\nThe sheet could not be rendered."


@dataclass(frozen=True)
class SheetReview:
    report: str
    filename: str | None = None
    page_count: int = 0
    reviewed_pages: int = 0
    findings: list[DrawingFinding] = field(default_factory=list)


@dataclass(frozen=True)
class _SheetPages:
    pages: list[bytes]
    spans: list[SheetSpan]
    truncated_pages: list[int]
    total: int
    error: str | None = None
    recovered_pdf: bytes | None = None


def review_sheet(
    data: bytes,
    filename: str,
    *,
    dxf_summary: str,
    focus: DrawingFocus,
    standards_loader: Callable[[], list[StandardExcerpt]] | None = None,
) -> SheetReview:
    """Return the observed section and checklist findings for one sheet."""
    loaded = _sheet_pages(data, filename)
    if loaded.error is not None:
        return SheetReview(report=loaded.error, filename=filename)

    llm = get_default_llm_with_vision()
    if llm is None:
        return SheetReview(
            report=_NO_VISION_MODEL,
            filename=filename,
            page_count=loaded.total,
            reviewed_pages=0,
        )

    standards = _load_standards(standards_loader)
    findings: list[DrawingFinding] = []
    categories = set(page_categories(focus))
    if categories:
        for index, page in enumerate(loaded.pages, start=1):
            page_spans = [span for span in loaded.spans if span.page == index]
            findings.extend(
                _review_page(
                    llm,
                    page,
                    filename,
                    index,
                    len(loaded.pages),
                    page_spans,
                    index in loaded.truncated_pages,
                    dxf_summary,
                    focus,
                    standards,
                    categories,
                    len(findings),
                )
            )

    if focus in {DrawingFocus.GENERAL, DrawingFocus.CROSS_SHEET}:
        findings.extend(
            _review_cross_sheet(
                llm,
                filename,
                loaded.spans,
                len(loaded.pages),
                dxf_summary,
                standards,
                len(findings),
            )
        )

    skipped = None
    if loaded.total > len(loaded.pages):
        skipped = (
            f"Pages after page {len(loaded.pages)} were not reviewed. "
            f"The sheet has {loaded.total} pages."
        )
    return SheetReview(
        report=format_observed(filename, findings, standards, skipped),
        findings=findings,
        filename=filename,
        page_count=loaded.total,
        reviewed_pages=len(loaded.pages),
    )


def render_pdf_pngs(
    file_bytes: bytes, max_pages: int, *, draw_annotations: bool = False
) -> tuple[list[bytes], int, list[SheetSpan], list[int]]:
    """Render the first pages of a PDF to PNG bytes. Runs in a child process."""
    from io import BytesIO

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(file_bytes)
    try:
        total = len(pdf)
        images: list[bytes] = []
        spans, truncated_pages = extract_pdf_spans(file_bytes, max_pages)
        for index in range(min(total, max_pages)):
            page = pdf[index]
            try:
                bitmap = page.render(scale=2, draw_annots=draw_annotations)
                try:
                    image = bitmap.to_pil()
                    buffer = BytesIO()
                    image.save(buffer, format="PNG")
                    images.append(buffer.getvalue())
                finally:
                    bitmap.close()
            finally:
                page.close()
        return images, total, spans, truncated_pages
    finally:
        pdf.close()


def _render_pdf_sheet(data: bytes, *, draw_annotations: bool) -> _SheetPages:
    recovered: bytes | None = None
    try:
        pages, total, spans, truncated = render_pdf_pngs(
            data, MAX_SHEET_PAGES, draw_annotations=draw_annotations
        )
    except (PdfminerException, PDFException, RecursionError):
        recovered = recover_review_pdf(data, MAX_SHEET_PAGES)
        pages, total, spans, truncated = render_pdf_pngs(
            recovered, MAX_SHEET_PAGES, draw_annotations=draw_annotations
        )
    return _SheetPages(
        pages=pages,
        spans=spans,
        truncated_pages=truncated,
        total=total,
        error=None if pages else "## observed\nThe sheet has no pages.",
        recovered_pdf=recovered,
    )


def _sheet_pages(
    data: bytes, filename: str, *, draw_annotations: bool = False
) -> _SheetPages:
    extension = get_file_ext(filename)
    if extension == ".pdf":
        try:
            return run_in_isolated_process(
                _render_pdf_sheet,
                data,
                timeout=PDF_TEXT_EXTRACTION_TIMEOUT_SECONDS,
                draw_annotations=draw_annotations,
            )
        except (
            IsolatedProcessError,
            PdfiumError,
            PdfminerException,
            PDFException,
            RecursionError,
            ValueError,
        ):
            logger.warning("Failed to read or render drawing sheet %s", filename)
            return _SheetPages(
                pages=[], spans=[], truncated_pages=[], total=0, error=_RENDER_FAILED
            )
    if extension in OnyxFileExtensions.IMAGE_EXTENSIONS:
        return _SheetPages(pages=[data], spans=[], truncated_pages=[], total=1)
    return _SheetPages(
        pages=[], spans=[], truncated_pages=[], total=0, error=_NOT_A_SHEET
    )


def _review_page(
    llm: LLM,
    image_data: bytes,
    filename: str,
    page_number: int,
    page_count: int,
    spans: list[SheetSpan],
    truncated: bool,
    dxf_summary: str,
    focus: DrawingFocus,
    standards: list[StandardExcerpt],
    allowed: set[DrawingFindingCategory],
    id_start: int,
) -> list[DrawingFinding]:
    try:
        encoded = prepare_image_bytes(image_data)
    except UnsupportedImageFormatError:
        return [
            unreadable_page_finding(
                page_number,
                standards=standards,
                finding_id=f"f{id_start + 1}",
            )
        ]

    messages: list[Message] = [
        SystemMessage(content=page_system_prompt(focus)),
        UserMessage(
            content=[
                TextContentPart(
                    text=(
                        f"The file name is '{filename}'. "
                        f"This is page {page_number} of {page_count}.\n"
                        f"Focus: {focus.value}.\n"
                        f"{standards_text(standards)}\n"
                        f"DXF measured section:\n{dxf_summary[:6000]}\n"
                        f"Spans:\n{span_text(spans, truncated)}"
                    )
                ),
                ImageContentPart(image_url=ImageUrlDetail(url=encoded)),
            ]
        ),
    ]
    text = _invoke(llm, messages, filename, page_number)
    if text is None:
        return [
            unreadable_page_finding(
                page_number, standards=standards, finding_id=f"f{id_start + 1}"
            )
        ]
    try:
        items = parse_checklist(text)
    except (ValueError, ValidationError, json.JSONDecodeError) as error:
        if not checklist_error_is_parse_failure(error):
            raise
        return [
            unreadable_page_finding(
                page_number, standards=standards, finding_id=f"f{id_start + 1}"
            )
        ]
    return resolve_findings(
        items,
        {span.span_id: span for span in spans},
        page=page_number,
        allowed=allowed,
        standards=standards,
        id_start=id_start,
    )


def _review_cross_sheet(
    llm: LLM,
    filename: str,
    spans: list[SheetSpan],
    reviewed_pages: int,
    dxf_summary: str,
    standards: list[StandardExcerpt],
    id_start: int,
) -> list[DrawingFinding]:
    if reviewed_pages < 2:
        return [
            single_page_cross_sheet_finding(
                standards=standards, finding_id=f"f{id_start + 1}"
            )
        ]
    grouped = "\n".join(f"{span.span_id}: {span.text}" for span in spans) or "none"
    messages: list[Message] = [
        SystemMessage(content=cross_sheet_system_prompt()),
        UserMessage(
            content=(
                f"The file name is '{filename}'. Reviewed pages: {reviewed_pages}.\n"
                f"{standards_text(standards)}\n"
                f"DXF measured section:\n{dxf_summary[:6000]}\n"
                f"Spans:\n{grouped}"
            )
        ),
    ]
    text = _invoke(llm, messages, filename, 0)
    if text is None:
        return [
            cross_sheet_unreadable_finding(
                standards=standards, finding_id=f"f{id_start + 1}"
            )
        ]
    try:
        items = parse_checklist(text)
    except (ValueError, ValidationError, json.JSONDecodeError) as error:
        if not checklist_error_is_parse_failure(error):
            raise
        return [
            cross_sheet_unreadable_finding(
                standards=standards, finding_id=f"f{id_start + 1}"
            )
        ]
    return resolve_findings(
        items,
        {span.span_id: span for span in spans},
        page=None,
        allowed={DrawingFindingCategory.CROSS_SHEET},
        standards=standards,
        id_start=id_start,
    )


def _load_standards(
    loader: Callable[[], list[StandardExcerpt]] | None,
) -> list[StandardExcerpt]:
    if loader is None:
        return []
    try:
        return loader()
    except Exception:
        logger.warning("Drawing standards could not be loaded", exc_info=True)
        return []


def _invoke(
    llm: LLM,
    messages: list[Message],
    filename: str,
    page_number: int,
    *,
    max_tokens: int | None = None,
    timeout: float = IMAGE_SUMMARIZATION_TIMEOUT,
    structured_response_format: dict[str, JsonValue] | None = None,
) -> str | None:
    try:
        response = llm.invoke(
            GenerationRequest(
                messages=messages,
                options=GenerationOptions(
                    max_tokens=max_tokens,
                    structured_response_format=structured_response_format,
                ),
            ),
            context=GenerationContext(
                flow=LLMFlow.DRAWING_REVIEW,
                content_mode=TraceContentMode.METADATA_ONLY,
                total_timeout_s=timeout,
            ),
        )
    except Exception:
        logger.warning(
            "Sheet review failed for %s page %s",
            filename,
            page_number,
            exc_info=True,
        )
        return None
    return response.text.strip() or None
