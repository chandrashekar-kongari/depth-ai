"""Local native-PDF callout locations. These locate text, not inferred geometry."""

import re
import unicodedata
from io import BytesIO
from typing import Literal

import pdfplumber
from pydantic import BaseModel, Field

from onyx.engineering.workspace_models import Anchor


class LocationQuery(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    page: int = Field(ge=1, le=100)
    request: str = Field(max_length=4000)
    evidence: str = Field(default="", max_length=4000)
    source_text: str = Field(default="", max_length=4000)
    role: Literal["original", "revised"] = "revised"


class LocationRequest(BaseModel):
    document_id: str = Field(min_length=1, max_length=256)
    queries: list[LocationQuery] = Field(max_length=100)


class TextLocation(BaseModel):
    id: str
    status: Literal["located_text", "located_comment", "ambiguous", "unresolved"]
    source: Literal["pdfplumber"] = "pdfplumber"
    anchor: Anchor | None = None
    text: str | None = None
    candidate_count: int = 0


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold().replace("⌀", "ø")


def nominal_number(text: str) -> float | None:
    diameter = re.search(r"[Øø⌀]\s*(\d+(?:\.\d+)?)", text)
    number = diameter or re.search(r"\d+(?:\.\d+)?", text)
    return float(number.group(1) if diameter else number.group()) if number else None


def locate_callouts(data: bytes, queries: list[LocationQuery]) -> list[TextLocation]:
    results: list[TextLocation] = []
    with pdfplumber.open(BytesIO(data), unicode_norm="NFKC") as pdf:
        for page_number in sorted({query.page for query in queries}):
            page_queries = [query for query in queries if query.page == page_number]
            if page_number > len(pdf.pages):
                results.extend(
                    TextLocation(id=query.id, status="unresolved")
                    for query in page_queries
                )
                continue
            page = pdf.pages[page_number - 1]
            # CropBox and intrinsic rotation are already in pdfplumber's displayed coordinates.
            crop = page.crop(page.cropbox)
            lines = crop.extract_text_lines(return_chars=False)
            for query in page_queries:
                if query.role == "original":
                    annotations = [
                        item
                        for item in (crop.annots or [])
                        if query.source_text
                        and normalized(str(item.get("contents") or ""))
                        == normalized(query.source_text)
                    ]
                    if len(annotations) == 1:
                        item = annotations[0]
                        results.append(
                            TextLocation(
                                id=query.id,
                                status="located_comment",
                                text=query.source_text,
                                candidate_count=1,
                                anchor=Anchor(
                                    page=page_number,
                                    x=(float(item["x0"]) - crop.bbox[0]) / crop.width,
                                    y=(float(item["top"]) - crop.bbox[1]) / crop.height,
                                    width=float(item["width"]) / crop.width,
                                    height=float(item["height"]) / crop.height,
                                ),
                            )
                        )
                        continue
                    results.append(
                        TextLocation(
                            id=query.id,
                            status="ambiguous" if annotations else "unresolved",
                            candidate_count=len(annotations),
                        )
                    )
                    continue
                candidates: list[tuple[str, Anchor]] = []
                request_number = nominal_number(query.request)
                evidence = normalized(query.evidence)
                for line in lines:
                    text = str(line["text"]).strip()
                    # Only isolated dimension labels; prose, title blocks and notes cannot qualify.
                    dimension = bool(
                        re.fullmatch(
                            r"[\d\s.,Øø⌀±+−–\-/°×xX()]+(?:\s*(?:THRU|H\d+|h\d+))?", text
                        )
                    )
                    if len(text) > 250 or (not dimension and len(text.split()) < 2):
                        continue
                    if not normalized(text) or not re.search(
                        r"(?<!\d)" + re.escape(normalized(text)) + r"(?!\d)",
                        evidence,
                    ):
                        continue
                    if (
                        dimension
                        and request_number is not None
                        and nominal_number(text) != request_number
                    ):
                        continue
                    x0, top, x1, bottom = (
                        float(line[key]) for key in ("x0", "top", "x1", "bottom")
                    )
                    if x1 - x0 > crop.width * 0.35:
                        continue
                    x, y = (
                        (x0 - crop.bbox[0]) / crop.width,
                        (top - crop.bbox[1]) / crop.height,
                    )
                    width, height = (x1 - x0) / crop.width, (bottom - top) / crop.height
                    if (
                        x < 0
                        or y < 0
                        or width <= 0
                        or height <= 0
                        or x + width > 1
                        or y + height > 1
                    ):
                        continue
                    candidates.append(
                        (
                            text,
                            Anchor(
                                page=page_number, x=x, y=y, width=width, height=height
                            ),
                        )
                    )
                dimensions = [
                    candidate
                    for candidate in candidates
                    if re.fullmatch(
                        r"[\d\s.,Øø⌀±+−–\-/°×xX()]+(?:\s*(?:THRU|H\d+|h\d+))?",
                        candidate[0],
                    )
                ]
                if dimensions:
                    candidates = dimensions
                if not candidates:
                    excerpt = re.sub(
                        r"^(?:visible text|native pdf text)\s*:\s*",
                        "",
                        query.evidence.strip(),
                        flags=re.IGNORECASE,
                    ).strip('"')
                    excerpt = unicodedata.normalize("NFKC", excerpt)
                    excerpt_is_dimension = bool(
                        re.fullmatch(
                            r"[\d\s.,Øø⌀±+−–\-/°×xX()]+(?:\s*(?:THRU|H\d+|h\d+))?",
                            excerpt,
                        )
                    )
                    if 6 <= len(excerpt) <= 400 and (
                        not excerpt_is_dimension
                        or request_number is None
                        or nominal_number(excerpt) == request_number
                    ):
                        pattern = (
                            r"(?<!\w)"
                            + r"\s+".join(re.escape(part) for part in excerpt.split())
                            + r"(?!\w)"
                        )
                        for item in crop.search(
                            pattern, regex=True, case=False, return_chars=False
                        ):
                            anchor = Anchor(
                                page=page_number,
                                x=(float(item["x0"]) - crop.bbox[0]) / crop.width,
                                y=(float(item["top"]) - crop.bbox[1]) / crop.height,
                                width=(float(item["x1"]) - float(item["x0"]))
                                / crop.width,
                                height=(float(item["bottom"]) - float(item["top"]))
                                / crop.height,
                            )
                            candidates.append((str(item["text"]), anchor))
                if len(candidates) == 1:
                    text, anchor = candidates[0]
                    results.append(
                        TextLocation(
                            id=query.id,
                            status="located_text",
                            anchor=anchor,
                            text=text,
                            candidate_count=1,
                        )
                    )
                else:
                    results.append(
                        TextLocation(
                            id=query.id,
                            status="ambiguous" if candidates else "unresolved",
                            candidate_count=len(candidates),
                        )
                    )
    return results
