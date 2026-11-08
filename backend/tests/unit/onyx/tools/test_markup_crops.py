from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter

from onyx.tools.models import DrawingMarkBox
from onyx.tools.tool_implementations.drawing_review.comment_queue import (
    ExtractedComment,
)
from onyx.tools.tool_implementations.drawing_review.comment_review import (
    _locate_crop_comments,
    verify_sheet_comments,
)
from onyx.tools.tool_implementations.drawing_review.markup_crops import (
    MarkupCrop,
    render_markup_crops,
)
from onyx.tools.tool_implementations.drawing_review.sheet import (
    _SheetPages,
    render_pdf_pngs,
)

_REVIEW = "onyx.tools.tool_implementations.drawing_review.comment_review"


@pytest.mark.parametrize("rotation", [0, 90])
def test_flattened_ink_crop_uses_rendered_page_coordinates(rotation: int) -> None:
    source = BytesIO()
    with Image.new("RGB", (400, 300), "white") as image:
        draw = ImageDraw.Draw(image)
        draw.line((10, 150, 380, 150), fill="black", width=2)
        draw.ellipse((72, 47, 88, 63), outline="red", width=3)
        image.save(source, format="PDF")

    writer = PdfWriter()
    page = writer.add_page(PdfReader(source).pages[0])
    page.rotate(rotation)
    page.cropbox.lower_left = (20, 20)
    page.cropbox.upper_right = (380, 280)
    pdf = BytesIO()
    writer.write(pdf)
    pages, _, _, _ = render_pdf_pngs(pdf.getvalue(), 1)

    crops = render_markup_crops(pdf.getvalue(), 1, pages[0])

    assert len(crops) == 1
    crop = crops[0]
    x, y = (1 / 6, 35 / 260) if rotation == 0 else (225 / 260, 1 / 6)
    assert crop.box.x < x < crop.box.x + crop.box.width
    assert crop.box.y < y < crop.box.y + crop.box.height
    with Image.open(BytesIO(crop.image)) as image:
        displayed_width = page.cropbox.width if rotation == 0 else page.cropbox.height
        assert image.width > 2 * crop.box.width * displayed_width
        red_pixels = [
            (index % image.width, index // image.width)
            for index, (r, g, b) in enumerate(image.convert("RGB").get_flattened_data())
            if r > g + 70 and r > b + 70
        ]
        assert red_pixels
        center_x = sum(px for px, _ in red_pixels) / len(red_pixels)
        center_y = sum(py for _, py in red_pixels) / len(red_pixels)
        assert crop.box.x + center_x / image.width * crop.box.width == pytest.approx(
            x, abs=0.01
        )
        assert crop.box.y + center_y / image.height * crop.box.height == pytest.approx(
            y, abs=0.01
        )


def test_crop_locations_merge_only_the_same_mark() -> None:
    crop = MarkupCrop(DrawingMarkBox(x=0.25, y=0.5, width=0.5, height=0.25), b"crop")
    mark = ExtractedComment(
        text="38",
        request="Set width to 38",
        box=DrawingMarkBox(x=0.5, y=0.25, width=0.25, height=0.25),
        crop_id=1,
    )
    duplicate = mark.model_copy(
        update={
            "crop_id": None,
            "box": DrawingMarkBox(x=0.5, y=0.5625, width=0.125, height=0.0625),
        }
    )
    other = duplicate.model_copy(
        update={"box": DrawingMarkBox(x=0.1, y=0.2, width=0.1, height=0.1)}
    )
    invalid = mark.model_copy(update={"crop_id": 99})

    located = _locate_crop_comments([mark, duplicate, other, invalid], [crop])

    assert [item.box for item in located] == [duplicate.box, other.box, None]


def test_failed_crop_extraction_keeps_full_page_and_embedded_comments() -> None:
    crop = MarkupCrop(DrawingMarkBox(x=0.2, y=0.2, width=0.2, height=0.2), b"crop")
    pages = _SheetPages(pages=[b"page"], spans=[], truncated_pages=[], total=1)
    native = ExtractedComment(text="Add finish note")
    visual = ExtractedComment(text="Set width to 38")
    with (
        patch(f"{_REVIEW}._find_markup_crops", return_value=([crop], False)),
        patch(
            f"{_REVIEW}._extract_page", side_effect=[(None, False), ([visual], False)]
        ) as extract,
    ):
        result = verify_sheet_comments(
            pages,
            pages,
            commented_name="before.pdf",
            revised_name="after.pdf",
            original_pdf=b"pdf",
            native_comments={1: [native]},
            dxf_summary=None,
            llm=MagicMock(),
        )

    assert extract.call_count == 2
    assert {comment.text for comment in result.comments} == {native.text, visual.text}
    assert any("visual markups" in notice for notice in result.coverage_notices)


def test_pdf_recovery_retries_text_parser_and_preserves_native_comments() -> None:
    from pdfplumber.utils.exceptions import PdfminerException
    from pypdf.annotations import Text

    from onyx.engineering.processing import pdf_comments
    from onyx.tools.tool_implementations.drawing_review.sheet import _render_pdf_sheet
    from onyx.tools.tool_implementations.drawing_review.spans import extract_pdf_spans

    writer = PdfWriter()
    writer.add_blank_page(width=600, height=400)
    writer.add_annotation(0, Text(rect=(10, 10, 30, 30), text="Check dimension"))
    output = BytesIO()
    writer.write(output)
    data = output.getvalue()
    sheet = "onyx.tools.tool_implementations.drawing_review.sheet"
    with patch(
        f"{sheet}.extract_pdf_spans",
        side_effect=[PdfminerException(RecursionError()), extract_pdf_spans(data, 1)],
    ):
        recovered = _render_pdf_sheet(data, draw_annotations=True)

    assert recovered.error is None
    assert recovered.total == 1
    assert recovered.recovered_pdf is not None
    assert pdf_comments(recovered.recovered_pdf)[1][1][0].text == "Check dimension"
