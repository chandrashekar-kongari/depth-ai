from io import BytesIO

from reportlab.pdfgen.canvas import Canvas

from onyx.engineering.pdf_locations import LocationQuery, locate_callouts


def drawing(labels: list[tuple[float, float, str]]) -> bytes:
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(600, 400))
    for x, y, text in labels:
        canvas.drawString(x, y, text)
    canvas.save()
    return stream.getvalue()


def test_locates_dimension_callout_and_excludes_prose_note() -> None:
    data = drawing([(300, 100, "8.0 ±0.1"), (400, 300, "8.0 ±0.1. Stock: aluminum")])
    result = locate_callouts(
        data,
        [
            LocationQuery(
                id="c4",
                page=1,
                request="Specify 8.0 ±0.1",
                evidence="visible text: 8.0 ±0.1. Stock: aluminum",
            )
        ],
    )[0]
    assert result.status == "located_text"
    assert result.anchor is not None
    assert result.anchor.x == 0.5
    assert 0.72 < result.anchor.y < 0.76
    assert result.text == "8.0 ±0.1"


def test_repeated_callouts_are_ambiguous_not_first_match() -> None:
    data = drawing([(100, 100, "8.0 ±0.1"), (300, 300, "8.0 ±0.1")])
    result = locate_callouts(
        data,
        [
            LocationQuery(
                id="c4", page=1, request="Specify 8.0 ±0.1", evidence="8.0 ±0.1"
            )
        ],
    )[0]
    assert result.status == "ambiguous"
    assert result.candidate_count == 2
    assert result.anchor is None


def test_missing_text_and_missing_page_never_get_an_edge_location() -> None:
    data = drawing([(100, 100, "160.0")])
    results = locate_callouts(
        data,
        [
            LocationQuery(id="c1", page=1, request="Add bore 20.0", evidence="20.0"),
            LocationQuery(id="c2", page=2, request="Add 20.0", evidence="20.0"),
        ],
    )
    assert all(
        result.status == "unresolved" and result.anchor is None for result in results
    )


def test_does_not_confuse_other_dimension_in_evidence() -> None:
    data = drawing([(100, 100, "120.0"), (300, 300, "60.0")])
    result = locate_callouts(
        data,
        [
            LocationQuery(
                id="c2",
                page=1,
                request="Correct horizontal pitch to 120.0",
                evidence="120.0 x 60.0",
            )
        ],
    )[0]
    assert result.status == "located_text"
    assert result.text == "120.0"


def test_cropped_pdf_coordinates_are_relative_to_visible_page() -> None:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import RectangleObject

    reader = PdfReader(BytesIO(drawing([(300, 100, "8.0 ±0.1")])))
    reader.pages[0].cropbox = RectangleObject([50, 50, 550, 350])
    writer = PdfWriter()
    writer.add_page(reader.pages[0])
    output = BytesIO()
    writer.write(output)
    result = locate_callouts(
        output.getvalue(),
        [LocationQuery(id="c4", page=1, request="8.0 ±0.1", evidence="8.0 ±0.1")],
    )[0]
    assert result.anchor is not None
    assert result.anchor.x == 0.5
    assert 0.79 < result.anchor.y < 0.82


def test_tolerance_match_cannot_substitute_another_nominal_dimension() -> None:
    data = drawing([(300, 100, "20.0 ±0.1")])
    result = locate_callouts(
        data,
        [
            LocationQuery(
                id="c4", page=1, request="Specify 8.0 ±0.1", evidence="20.0 ±0.1"
            )
        ],
    )[0]
    assert result.status == "unresolved"


def test_original_uses_native_comment_not_revised_value() -> None:
    from pypdf import PdfReader, PdfWriter
    from pypdf.annotations import Text

    writer = PdfWriter()
    writer.add_page(PdfReader(BytesIO(drawing([(100, 100, "120.0")]))).pages[0])
    writer.add_annotation(
        0, Text(rect=(200, 200, 218, 218), text="C01 Add missing hole diameter")
    )
    buffer = BytesIO()
    writer.write(buffer)
    query = LocationQuery(
        id="c1",
        page=1,
        role="original",
        source_text="C01 Add missing hole diameter",
        request="Add Ø9.0",
        evidence="4X Ø9.0 THRU",
    )
    result = locate_callouts(buffer.getvalue(), [query])[0]
    assert result.status == "located_comment" and result.anchor is not None
    assert result.anchor.x == 200 / 600


def test_unique_evidence_excerpt_locates_finish_note_without_numeric_label_rule() -> (
    None
):
    data = drawing([(100, 100, "Clear anodize on pads 1 and 2. Break sharp edges.")])
    result = locate_callouts(
        data,
        [
            LocationQuery(
                id="c12",
                page=1,
                request="Specify anodize",
                evidence="visible text: Clear anodize on pads 1 and 2",
            )
        ],
    )[0]
    assert result.status == "located_text" and result.anchor is not None
    assert result.text == "Clear anodize on pads 1 and 2"
