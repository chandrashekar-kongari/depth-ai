"""Generated PDFs qualify source comparisons, not engineering design correctness."""

import math
from io import BytesIO
from unittest.mock import patch

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
)

from onyx.engineering.drawing_changes import (
    attach_drawing_changes,
    compare_drawing_pdfs,
)
from onyx.tools.models import (
    CommentReviewResult,
    CommentVerdict,
    DrawingChangeReview,
    DrawingComment,
    DrawingMarkBox,
)
from onyx.utils.process_isolation import IsolatedProcessTimeout


def drawing(
    values: list[str],
    *,
    annotate: bool = False,
    frame: bool = False,
    shift: int = 0,
    extra: str = "",
) -> bytes:
    writer = PdfWriter()
    for number, value in enumerate(values):
        page = writer.add_blank_page(600, 400)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): writer._add_object(font)}
                )
            }
        )
        # Distinct fixed landmarks provide registration independent of compared numbers.
        commands = ["0 G 1 w"]
        for i in range(7):
            for j in range(4):
                x, y = 40 + i * 67, 35 + j * 68
                commands.append(f"{x} {y} {12 + i * 2} {8 + j * 3} re S")
                commands.append(f"{x} {y} m {x + 8 + j * 3} {y + 21 + i} l S")
        commands.append(f"BT /F1 14 Tf {250 + shift} 320 Td ({value}) Tj ET")
        commands.append(f"BT /F1 10 Tf 500 20 Td (SHEET {number + 1}) Tj ET")
        if frame:
            commands.append(f"{245 + shift} 315 75 25 re S")
        if extra:
            commands.append(f"BT /F1 14 Tf 400 320 Td ({extra}) Tj ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(commands).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
        if annotate:
            mark = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Annot"),
                    NameObject("/Subtype"): NameObject("/Circle"),
                    NameObject("/Rect"): ArrayObject(
                        [FloatObject(x) for x in (240, 310, 325, 345)]
                    ),
                    NameObject("/C"): ArrayObject(
                        [FloatObject(1), FloatObject(0), FloatObject(0)]
                    ),
                }
            )
            page[NameObject("/Annots")] = ArrayObject([writer._add_object(mark)])
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def native_pairs(result: DrawingChangeReview) -> list[tuple[str, str, str]]:
    return [
        (c.kind, c.before_text, c.after_text)
        for c in result.changes
        if c.kind != "visual"
    ]


def test_annotations_are_not_design_changes() -> None:
    result = compare_drawing_pdfs(drawing(["24"], annotate=True), drawing(["24"]))
    assert result.status == "complete"
    assert result.changes == []


def test_tiny_decimal_and_all_pages_are_compared() -> None:
    result = compare_drawing_pdfs(drawing(["0.01", "R42"]), drawing(["0.02", "R37"]))
    assert result.compared_pages == [1, 2]
    assert ("text_changed", "0.01", "0.02") in native_pairs(result)
    assert ("text_changed", "R42", "R37") in native_pairs(result)


def test_unchanged_repeated_value_is_not_paired_with_new_callout() -> None:
    result = compare_drawing_pdfs(drawing(["24"]), drawing(["24"], extra="48"))
    pairs = native_pairs(result)
    assert ("text_added", "", "48") in pairs
    assert not any(before == "24" for _, before, _ in pairs)


def test_framed_value_is_not_replacement_for_unframed_dimension() -> None:
    result = compare_drawing_pdfs(drawing(["240"]), drawing(["0.04"], frame=True))
    assert ("text_changed", "240", "0.04") not in native_pairs(result)
    assert ("text_removed", "240", "") in native_pairs(result)
    assert ("text_added", "", "0.04") in native_pairs(result)


def test_scoped_pages_and_mismatched_counts_are_explicit() -> None:
    result = compare_drawing_pdfs(drawing(["25", "35"]), drawing(["26", "36"]), [2])
    assert result.compared_pages == [2]
    assert all(c.page == 2 for c in result.changes)
    mismatch = compare_drawing_pdfs(drawing(["25"]), drawing(["25", "35"]))
    assert mismatch.status == "partial"
    assert mismatch.compared_pages == [1]
    assert mismatch.unmatched_revised_pages == {2: "Inserted sheet."}


def test_comment_association_cannot_change_inventory_or_verdicts() -> None:
    before, after = drawing(["42"]), drawing(["43"])
    base = compare_drawing_pdfs(before, after)
    comment = DrawingComment(
        id="c1",
        page=1,
        text="43",
        request="43",
        verdict=CommentVerdict.SOLVED_CORRECT,
        evidence="43",
        remaining="",
        box=DrawingMarkBox(x=0.4, y=0.15, width=0.15, height=0.1),
    )
    existing = CommentReviewResult(
        status="Done", report="Comment report", comments=[comment]
    )
    with patch(
        "onyx.engineering.drawing_changes.run_in_isolated_process", return_value=base
    ):
        linked = attach_drawing_changes(existing, before, after)
        unlinked = attach_drawing_changes(
            existing.model_copy(update={"comments": []}), before, after
        )
    assert linked.comments == existing.comments
    assert linked.status == existing.status
    assert linked.drawing_changes is not None and unlinked.drawing_changes is not None
    assert [
        c.model_dump(exclude={"possible_comment_ids"})
        for c in linked.drawing_changes.changes
    ] == [
        c.model_dump(exclude={"possible_comment_ids"})
        for c in unlinked.drawing_changes.changes
    ]
    assert any(c.possible_comment_ids for c in linked.drawing_changes.changes)


def test_timeout_preserves_comment_results() -> None:
    existing = CommentReviewResult(status="Done", report="Comment report")
    with patch(
        "onyx.engineering.drawing_changes.run_in_isolated_process",
        side_effect=IsolatedProcessTimeout(120),
    ):
        result = attach_drawing_changes(existing, b"old", b"new")
    assert result.status == existing.status and result.comments == existing.comments
    assert result.drawing_changes is not None
    assert result.drawing_changes.status == "failed"


@pytest.mark.parametrize("value", ["24", "0.003", "R42"])
def test_same_drawing_has_no_changes(value: str) -> None:
    data = drawing([value])
    result = compare_drawing_pdfs(data, data)
    assert result.changes == []


def test_registration_failure_keeps_visual_evidence_and_reports_coverage() -> None:
    with patch("onyx.engineering.drawing_changes._estimate", return_value=None):
        result = compare_drawing_pdfs(drawing(["28"]), drawing(["29"]))
    assert result.status == "partial"
    assert result.warnings
    assert result.changes and all(c.kind == "visual" for c in result.changes)


def test_repeated_equal_labels_stay_independent() -> None:
    result = compare_drawing_pdfs(
        drawing(["24"], extra="24"), drawing(["25"], extra="24")
    )
    assert native_pairs(result) == [("text_changed", "24", "25")]


def test_candidate_limit_is_never_a_complete_review() -> None:
    with patch("onyx.engineering.drawing_changes._MAX_CHANGES", 1):
        result = compare_drawing_pdfs(drawing(["31"]), drawing(["32"], extra="45"))
    assert result.status == "partial" and result.warnings
    assert len(result.changes) == 1


@pytest.mark.parametrize("rotation", [90, 270])
def test_rotated_pages_keep_native_value_changes(rotation: int) -> None:
    def rotated(data: bytes) -> bytes:
        writer = PdfWriter(clone_from=BytesIO(data))
        for page in writer.pages:
            page.rotate(rotation)
        stream = BytesIO()
        writer.write(stream)
        return stream.getvalue()

    result = compare_drawing_pdfs(
        rotated(drawing(["0.01"])), rotated(drawing(["0.02"]))
    )
    assert ("text_changed", "0.01", "0.02") in native_pairs(result)


def test_covered_native_text_does_not_become_a_visible_change() -> None:
    def covered(data: bytes) -> bytes:
        writer = PdfWriter(clone_from=BytesIO(data))
        page = writer.pages[0]
        content = page.get_contents()
        assert content is not None
        stream = DecodedStreamObject()
        stream.set_data(content.get_data() + b"\nq 1 g 240 310 90 35 re f Q")
        page[NameObject("/Contents")] = writer._add_object(stream)
        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    result = compare_drawing_pdfs(
        covered(drawing(["0.01"])), covered(drawing(["0.02"]))
    )
    assert result.changes == []


def dimension_drawing(
    value: str, rotation: int, offset: int, *, target_shift: int = 0
) -> bytes:
    """Move the annotation while keeping its measured extension origins explicit."""
    writer = PdfWriter(clone_from=BytesIO(drawing(["PART"])))
    page = writer.pages[0]
    content = page.get_contents()
    assert content is not None
    theta = math.radians(rotation)
    a, b = math.cos(theta), math.sin(theta)
    x = 450 + target_shift
    dimension = x + offset
    operators = [
        f"{x} 110 m {x} 290 l S",
        f"{x + 2} 110 m {dimension + 3} 110 l S",
        f"{x + 2} 290 m {dimension + 3} 290 l S",
        f"{dimension} 110 m {dimension} 290 l S",
        f"BT /F1 14 Tf {a:.8f} {b:.8f} {-b:.8f} {a:.8f} {dimension - 12} 195 Tm ({value}) Tj ET",
    ]
    stream = DecodedStreamObject()
    stream.set_data(content.get_data() + ("\n" + "\n".join(operators)).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize("rotation", [90, 180, 270, 45])
def test_equal_dimension_survives_text_rotation_and_line_offset(rotation: int) -> None:
    result = compare_drawing_pdfs(
        dimension_drawing("48", 0, 40), dimension_drawing("48", rotation, 70)
    )
    assert native_pairs(result) == []
    # The visual differences remain available; they are not declared metric errors.
    assert any(change.kind == "visual" for change in result.changes)


def test_real_value_change_survives_text_rotation() -> None:
    result = compare_drawing_pdfs(
        dimension_drawing("48", 0, 40), dimension_drawing("49", 90, 70)
    )
    assert ("text_changed", "48", "49") in native_pairs(result)


def test_equal_values_on_different_references_do_not_cancel() -> None:
    result = compare_drawing_pdfs(
        dimension_drawing("48", 0, 40), dimension_drawing("48", 90, 40, target_shift=20)
    )
    assert ("text_removed", "48", "") in native_pairs(result)
    assert ("text_added", "", "48") in native_pairs(result)


def test_shared_evidence_keeps_unchanged_dimension_for_comment_verification() -> None:
    from onyx.engineering.drawing_changes import build_drawing_evidence

    before = dimension_drawing("48", 0, 40)
    after = dimension_drawing("48", 90, 70)
    evidence = build_drawing_evidence(before, after)
    assert any(
        item.original_text == item.revised_text == "48" for item in evidence.callouts
    )
    assert not native_pairs(evidence.comparison)


def test_reordered_sheets_use_identifiers_and_revision_page_numbers() -> None:
    before = drawing(["24", "48"])
    writer = PdfWriter(clone_from=BytesIO(before))
    reordered = PdfWriter()
    reordered.add_page(writer.pages[1])
    reordered.add_page(writer.pages[0])
    output = BytesIO()
    reordered.write(output)
    result = compare_drawing_pdfs(before, output.getvalue())
    assert result.page_pairs == {1: 2, 2: 1}
    assert result.compared_pages == [1, 2]
    assert result.changes == []


def test_page_limit_reports_exact_unchecked_pair() -> None:
    result = compare_drawing_pdfs(drawing(["24"] * 9), drawing(["24"] * 9))
    assert result.status == "partial"
    assert result.compared_pages == list(range(1, 9))
    assert 9 in result.skipped_original_pages


def test_shared_evidence_keeps_completed_page_after_later_timeout() -> None:
    from onyx.engineering.drawing_changes import DrawingEvidence, load_drawing_evidence

    completed = DrawingEvidence(
        comparison=DrawingChangeReview(status="complete", compared_pages=[1])
    )
    with patch(
        "onyx.engineering.drawing_changes.run_in_isolated_process",
        side_effect=[({1: 1, 2: 2}, {}, {}, 2), completed, IsolatedProcessTimeout(30)],
    ):
        result = load_drawing_evidence(b"before", b"after")
    assert result.comparison.compared_pages == [1]
    assert result.comparison.status == "partial"
    assert "timed out" in result.comparison.skipped_original_pages[2]


def test_duplicate_sheet_identifiers_stay_ambiguous() -> None:
    source = PdfWriter(clone_from=BytesIO(drawing(["24"])))
    writer = PdfWriter()
    writer.add_page(source.pages[0])
    writer.add_page(source.pages[0])
    output = BytesIO()
    writer.write(output)
    result = compare_drawing_pdfs(output.getvalue(), output.getvalue())
    assert result.page_pairs == {}
    assert result.compared_pages == []
    assert len(result.skipped_original_pages) == 2
    assert all(
        "Ambiguous" in reason for reason in result.skipped_original_pages.values()
    )


def test_confirmed_page_order_pairs_unidentified_sheets_through_comparison() -> None:
    from onyx.engineering.drawing_changes import build_drawing_evidence

    before = drawing(["24", "34"])
    source = PdfWriter(clone_from=BytesIO(drawing(["25"])))
    writer = PdfWriter()
    writer.add_page(source.pages[0])
    writer.add_page(source.pages[0])
    output = BytesIO()
    writer.write(output)
    after = output.getvalue()
    automatic = build_drawing_evidence(before, after)
    confirmed = build_drawing_evidence(before, after, confirmed_page_order=True)

    assert automatic.comparison.page_pairs == {}
    assert confirmed.comparison.page_pairs == {1: 1, 2: 2}
    assert confirmed.comparison.compared_pages == [1, 2]


def test_sheet_counters_ignore_prose_and_match_only_same_package() -> None:
    from onyx.engineering.drawing_changes import _sheet_identity

    before = "MECHANICAL DRAWING COMPARISON TEST PK-440 | REV A\nTHREE-SHEET REVIEW PACKAGE\nSHEET 01 / 03 OPEN REVIEW COMMENTS"
    after = "MECHANICAL DRAWING COMPARISON TEST PK-440 | REV B\nTHREE-SHEET REVIEW PACKAGE\nSHEET 1 OF 3 RELEASED NOTES"
    assert _sheet_identity(before) == _sheet_identity(after) == "counter:PK-440:1/3"
    assert _sheet_identity(after.replace("PK-440", "PK-441")) != _sheet_identity(before)
    assert _sheet_identity(before + "\nSHEET 2 / 3") is None
