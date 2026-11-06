"""Checklist findings for one plotted sheet.

The model returns span ids. The server resolves each id to a box.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, ValidationError

from onyx.tools.models import (
    DrawingFinding,
    DrawingFindingCategory,
    DrawingFindingStatus,
    DrawingFocus,
    DrawingMarkBox,
)
from onyx.tools.tool_implementations.drawing_review.spans import SheetSpan, page_box
from onyx.tools.tool_implementations.drawing_review.standards import (
    NO_COMPANY_STANDARD,
    StandardExcerpt,
)

_PAGE_CATEGORIES = (
    DrawingFindingCategory.TITLE_BLOCK,
    DrawingFindingCategory.VIEWS,
    DrawingFindingCategory.DIMENSIONS,
    DrawingFindingCategory.GDT,
    DrawingFindingCategory.BOM,
)
_MAX_ITEMS = 12
_CATEGORY_ORDER = (
    DrawingFindingCategory.TITLE_BLOCK,
    DrawingFindingCategory.VIEWS,
    DrawingFindingCategory.DIMENSIONS,
    DrawingFindingCategory.GDT,
    DrawingFindingCategory.BOM,
    DrawingFindingCategory.CROSS_SHEET,
)

_PAGE_SYSTEM_PROMPT = """
You review one page of a mechanical drawing.
Return JSON only. The shape is {"items":[...]}.
Each item has category, status, span_id, title, detail, evidence, and source.
status is pass, fail, or needs_review.
span_id is an id from the span list, or null when no span matches.
A number on the sheet is visible text, not a measurement.
If you mention a number, evidence starts with "visible text:".
source is observed for sheet text.
source is measured only when you cite a DXF dimension entity.
Do not replace a DXF measurement with sheet text.
A mismatch between a DXF dimension entity and visible text is a dimensions finding.
Do not claim the drawing meets ASME, ISO, or a company standard.
The review does not certify the drawing.
""".strip()

_CROSS_SHEET_SYSTEM_PROMPT = """
You compare one drawing across its sheets.
Return JSON only. The shape is {"items":[...]}.
category is cross_sheet.
status is pass, fail, or needs_review.
Compare material, finish, revision, angular tolerance, and title block fields.
span_id is an id from the span list, or null.
page is the page number of that span.
A number on the sheet is visible text, not a measurement.
Evidence for sheet text starts with "visible text:".
Do not claim the drawing meets ASME, ISO, or a company standard.
The review does not certify the drawing.
""".strip()


class ChecklistItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: DrawingFindingCategory
    status: DrawingFindingStatus
    span_id: str | None = None
    title: str
    detail: str = ""
    evidence: str = ""
    source: str = "observed"
    page: int | None = None
    standard_citation: str | None = None


def page_categories(focus: DrawingFocus) -> tuple[DrawingFindingCategory, ...]:
    if focus is DrawingFocus.GENERAL:
        return _PAGE_CATEGORIES
    if focus is DrawingFocus.CROSS_SHEET:
        return ()
    return (DrawingFindingCategory(focus.value),)


def page_system_prompt(focus: DrawingFocus) -> str:
    categories = ", ".join(item.value for item in page_categories(focus))
    return f"{_PAGE_SYSTEM_PROMPT}\ncategory is one of: {categories}."


def cross_sheet_system_prompt() -> str:
    return _CROSS_SHEET_SYSTEM_PROMPT


def standards_text(standards: list[StandardExcerpt]) -> str:
    if not standards:
        return NO_COMPANY_STANDARD
    lines = ["Company standards. Cite a title when a finding uses it."]
    lines.extend(f"- {item.title}: {item.text}" for item in standards)
    return "\n".join(lines)


def span_text(spans: list[SheetSpan], truncated: bool) -> str:
    if not spans:
        return "No text spans. Use span_id null."
    lines = [f"{span.span_id}: {span.text}" for span in spans]
    if truncated:
        lines.append("The span list is truncated.")
    return "\n".join(lines)


def parse_checklist(text: str) -> list[ChecklistItem]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        fence = raw.rfind("```")
        if fence >= 0:
            raw = raw[:fence]
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Checklist JSON is missing.")
    payload = json.loads(raw[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Checklist JSON is missing.")
    raw_items = payload.get("items", [])
    if not isinstance(raw_items, list):
        raise ValueError("Checklist JSON is missing.")
    items: list[ChecklistItem] = []
    for raw_item in raw_items:
        try:
            items.append(ChecklistItem.model_validate(raw_item))
        except ValidationError:
            continue
    return items


def resolve_findings(
    items: list[ChecklistItem],
    spans: dict[str, SheetSpan],
    *,
    page: int | None,
    allowed: set[DrawingFindingCategory],
    standards: list[StandardExcerpt],
    id_start: int,
) -> list[DrawingFinding]:
    """Turn checklist items into findings. Unknown span ids cover the page."""
    findings: list[DrawingFinding] = []
    next_id = id_start
    for item in items:
        if item.category not in allowed or not item.title.strip():
            continue
        if len(findings) >= _MAX_ITEMS:
            break
        span_id = item.span_id.strip() if item.span_id else None
        span = spans.get(span_id) if span_id else None
        finding_page = (
            page
            if page is not None
            else item.page or (span.page if span is not None else 1)
        )
        if span is not None and span.page != finding_page:
            span = None
            span_id = None
        marked = item.status is not DrawingFindingStatus.PASS
        page_level = marked and span is None
        box = None
        if marked and span is not None:
            box = DrawingMarkBox(
                x=span.x, y=span.y, width=span.width, height=span.height
            )
        elif page_level:
            x, y, width, height = page_box()
            box = DrawingMarkBox(x=x, y=y, width=width, height=height)
        source = "measured" if item.source == "measured" else "observed"
        next_id += 1
        findings.append(
            DrawingFinding(
                id=f"f{next_id}",
                category=item.category,
                status=item.status,
                page=finding_page,
                title=item.title.strip()[:160],
                detail=item.detail.strip()[:400],
                evidence=_label_evidence(item.evidence, source),
                source=source,
                span_id=span.span_id if span is not None else None,
                box=box,
                page_level=page_level,
                standard_citation=_cite(item.standard_citation, standards),
            )
        )
    return findings


def unreadable_page_finding(
    page: int, *, standards: list[StandardExcerpt], finding_id: str
) -> DrawingFinding:
    x, y, width, height = page_box()
    return DrawingFinding(
        id=finding_id,
        category=DrawingFindingCategory.VIEWS,
        status=DrawingFindingStatus.NEEDS_REVIEW,
        page=page,
        title="This page could not be reviewed.",
        detail="The checklist did not return a readable result.",
        evidence="visible text: none",
        source="observed",
        box=DrawingMarkBox(x=x, y=y, width=width, height=height),
        page_level=True,
        standard_citation=_cite(None, standards),
    )


def cross_sheet_unreadable_finding(
    *, standards: list[StandardExcerpt], finding_id: str
) -> DrawingFinding:
    x, y, width, height = page_box()
    return DrawingFinding(
        id=finding_id,
        category=DrawingFindingCategory.CROSS_SHEET,
        status=DrawingFindingStatus.NEEDS_REVIEW,
        page=1,
        title="Sheets could not be compared.",
        detail="The cross-sheet checklist did not return a readable result.",
        evidence="visible text: none",
        source="observed",
        box=DrawingMarkBox(x=x, y=y, width=width, height=height),
        page_level=True,
        standard_citation=_cite(None, standards),
    )


def single_page_cross_sheet_finding(
    *, standards: list[StandardExcerpt], finding_id: str
) -> DrawingFinding:
    return DrawingFinding(
        id=finding_id,
        category=DrawingFindingCategory.CROSS_SHEET,
        status=DrawingFindingStatus.PASS,
        page=1,
        title="One page was reviewed.",
        detail="There is no second sheet to compare.",
        evidence="visible text: none",
        source="observed",
        standard_citation=_cite(None, standards),
    )


def format_observed(
    filename: str,
    findings: list[DrawingFinding],
    standards: list[StandardExcerpt],
    skipped_note: str | None,
) -> str:
    lines = ["## observed", f"Source: {filename}"]
    if standards:
        lines.append("Company standards were retrieved.")
    else:
        lines.append(NO_COMPANY_STANDARD)
    if skipped_note:
        lines.append(skipped_note)
    lines.append("The review does not certify the drawing.")
    if not findings:
        lines.append("No checklist findings.")
        return "\n".join(lines)
    for category in _CATEGORY_ORDER:
        group = [item for item in findings if item.category is category]
        if not group:
            continue
        lines.append(f"### {category.value}")
        for item in group:
            mark = "page" if item.page_level else (item.span_id or "none")
            lines.append(
                f"- {item.status.value}: {item.title} {item.detail} "
                f"Evidence: {item.evidence}. Page {item.page}. Mark: {mark}. "
                f"Standard: {item.standard_citation}"
            )
    return "\n".join(lines)


def _cite(citation: str | None, standards: list[StandardExcerpt]) -> str:
    if not standards:
        return NO_COMPANY_STANDARD
    raw = (citation or "").strip()
    for excerpt in standards:
        if excerpt.title and excerpt.title in raw:
            return raw[:300]
    return NO_COMPANY_STANDARD


def _label_evidence(evidence: str, source: str) -> str:
    text = evidence.strip() or "none"
    if source == "measured":
        if "DXF" not in text:
            return f"DXF dimension entity. {text}"[:300]
        return text[:300]
    if not text.lower().startswith("visible text"):
        return f"visible text: {text}"[:300]
    return text[:300]


def checklist_error_is_parse_failure(error: Exception) -> bool:
    return isinstance(error, (ValueError, ValidationError, json.JSONDecodeError))
