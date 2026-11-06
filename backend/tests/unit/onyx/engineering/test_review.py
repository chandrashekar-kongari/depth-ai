"""PDF and durable-ledger regressions. SQLite does not verify PG row locking."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import JSON, Column, MetaData, Table, create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Session

from onyx.db.engineering_review import (
    cancel_review,
    claim_review,
    finish_review,
    heartbeat,
    owned_review,
    record_decision,
    save_review,
    snapshot,
)
from onyx.db.models import EngineeringReview, EngineeringReviewDecision
from onyx.engineering.config import private_review_llm, validate_private_endpoint
from onyx.engineering.models import DecisionRequest, DecisionValue
from onyx.engineering.processing import ReviewInputError, pdf_comments
from onyx.error_handling.exceptions import OnyxError
from onyx.tools.models import CommentReviewResult, CommentVerdict, DrawingComment
from onyx.tools.tool_implementations.drawing_review.comment_review import (
    verify_sheet_comments,
)
from onyx.tools.tool_implementations.drawing_review.sheet import _SheetPages


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    metadata = MetaData()
    Table("user", metadata, Column("id", UUID(as_uuid=True), primary_key=True))
    for model in (EngineeringReview, EngineeringReviewDecision):
        source = model.__table__
        assert isinstance(source, Table)
        table = source.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def make_review(session: Session) -> EngineeringReview:
    row = EngineeringReview(
        id=uuid4(),
        owner_id=uuid4(),
        request_key=uuid4(),
        original_blob="original",
        revised_blob="revised",
        original_name="original.pdf",
        revised_name="revised.pdf",
        original_sha256="a" * 64,
        revised_sha256="b" * 64,
        page_order_confirmed=True,
    )
    save_review(session, row)
    return row


def result() -> CommentReviewResult:
    return CommentReviewResult(
        status="Proposals",
        report="Report",
        comments=[
            DrawingComment(
                id="c1",
                page=1,
                text="Change the note",
                request="Change the note",
                verdict=CommentVerdict.UNCLEAR,
                evidence="unavailable",
                remaining="Check",
            )
        ],
    )


def test_restart_claim_and_stale_owner_cannot_publish(session: Session) -> None:
    row = make_review(session)
    first = claim_review(session)
    assert first is not None
    assert claim_review(session) is None
    row.lease_until = datetime.now(timezone.utc) - timedelta(seconds=5)
    session.commit()
    second = claim_review(session)
    assert second is not None and second[1] != first[1]
    assert not finish_review(session, *first, result=result())
    assert finish_review(session, *second, result=result())
    assert (
        snapshot(session, owned_review(session, row.id, row.owner_id)).status == "ready"
    )


def test_cancel_fences_heartbeat_and_late_results(session: Session) -> None:
    row = make_review(session)
    claim = claim_review(session)
    assert claim is not None
    assert heartbeat(session, *claim)
    assert cancel_review(session, row.id, row.owner_id).status == "cancelled"
    assert not heartbeat(session, *claim)
    assert not finish_review(session, *claim, result=result())


def test_other_owner_cannot_read_cancel_or_decide(session: Session) -> None:
    row = make_review(session)
    for operation in (
        lambda: owned_review(session, row.id, uuid4()),
        lambda: cancel_review(session, row.id, uuid4()),
        lambda: record_decision(
            session,
            row.id,
            uuid4(),
            "c1",
            DecisionRequest(value=DecisionValue.ACCEPT, expected_version=0),
        ),
    ):
        with pytest.raises(OnyxError) as error:
            operation()
        assert error.value.status_code == 404


def test_decisions_are_versioned_and_append_only(session: Session) -> None:
    row = make_review(session)
    claim = claim_review(session)
    assert claim is not None
    assert finish_review(session, *claim, result=result())
    first = record_decision(
        session,
        row.id,
        row.owner_id,
        "c1",
        DecisionRequest(
            value=DecisionValue.REJECT, note="Incorrect evidence", expected_version=0
        ),
    )
    assert first.version == 1
    with pytest.raises(OnyxError) as error:
        record_decision(
            session,
            row.id,
            row.owner_id,
            "c1",
            DecisionRequest(value=DecisionValue.ACCEPT, expected_version=0),
        )
    assert error.value.status_code == 409
    final = record_decision(
        session,
        row.id,
        row.owner_id,
        "c1",
        DecisionRequest(value=DecisionValue.NEEDS_REVIEW, expected_version=1),
    )
    assert len(final.decisions) == 2
    assert final.decisions[0].note == "Incorrect evidence"
    with pytest.raises(OnyxError):
        record_decision(
            session,
            row.id,
            row.owner_id,
            "invented",
            DecisionRequest(value=DecisionValue.ACCEPT, expected_version=2),
        )


def test_repeated_worker_death_has_bounded_recovery(session: Session) -> None:
    row = make_review(session)
    for _ in range(3):
        assert claim_review(session) is not None
        row.lease_until = datetime.now(timezone.utc) - timedelta(seconds=5)
        session.commit()
    assert claim_review(session) is None
    session.refresh(row)
    assert row.status == "failed"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "https://8.8.8.8",
        "http://169.254.169.254",
        "http://0.0.0.0",
        "http://127.0.0.1:1234/path",
        "http://user:secret@127.0.0.1",
        "http://127.0.0.1?x=1",
    ],
)
def test_private_endpoint_fails_closed(url: str) -> None:
    with pytest.raises(ValueError):
        validate_private_endpoint(url)


def test_private_model_never_uses_chat_default() -> None:
    with (
        patch("onyx.engineering.config.REVIEW_MODEL", ""),
        patch("onyx.engineering.config.get_llm") as factory,
    ):
        assert private_review_llm() is None
        factory.assert_not_called()
    assert (
        validate_private_endpoint("http://127.0.0.1:11434/") == "http://127.0.0.1:11434"
    )


def pdf(*, pages: int = 1, encrypted: bool = False) -> bytes:
    from pypdf import PdfWriter
    from pypdf.annotations import Text

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=600, height=800)
    writer.add_annotation(
        0, Text(rect=(20, 30, 40, 50), text="Change finish to Ra 1.6")
    )
    if encrypted:
        writer.encrypt("password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_native_comments_are_kept_without_an_ai_verdict() -> None:
    count, comments = pdf_comments(pdf())
    assert count == 1 and comments[1][0].text == "Change finish to Ra 1.6"
    pages = _SheetPages(pages=[b"page"], spans=[], truncated_pages=[], total=1)
    checked = verify_sheet_comments(
        pages,
        pages,
        commented_name="old.pdf",
        revised_name="new.pdf",
        dxf_summary=None,
        llm=None,
        native_comments=comments,
    )
    assert len(checked.comments) == 1
    assert checked.comments[0].verdict == CommentVerdict.UNCLEAR


@pytest.mark.parametrize("data", [pdf(pages=9), pdf(encrypted=True)])
def test_unsupported_pdf_is_rejected_instead_of_partly_reviewed(data: bytes) -> None:
    with pytest.raises(ReviewInputError):
        pdf_comments(data)


def test_exact_note_check_requires_unique_complete_lines() -> None:
    from onyx.engineering.checks import verify_note_replacement

    comment = (
        result()
        .comments[0]
        .model_copy(update={"text": 'Replace note "FINISH A" with "FINISH B"'})
    )
    checked = verify_note_replacement(comment, "FINISH A\nOTHER", "FINISH B\nOTHER")
    assert checked is not None and checked.verdict == CommentVerdict.SOLVED_CORRECT
    assert verify_note_replacement(comment, "FINISH A\nFINISH A", "FINISH B") is None
    assert verify_note_replacement(comment, "FINISH A", "PREFIX FINISH B") is None
    assert (
        verify_note_replacement(
            comment.model_copy(update={"text": "Change diameter to 10"}), "10", "10"
        )
        is None
    )


def test_model_evidence_must_exist_in_the_revised_source() -> None:
    from onyx.engineering.checks import has_verbatim_evidence

    assert has_verbatim_evidence("2X Ø6.6 THRU", "2X Ø6.6\nTHRU")
    assert not has_verbatim_evidence("2X Ø6.0 THRU", "2X Ø6.6 THRU")
    assert not has_verbatim_evidence("120.0", "120.0")
    assert not has_verbatim_evidence("Ø20.0 ±0.20", "Ø20.0 ±0.10 THRU")
    assert not has_verbatim_evidence("Ø20.0 ±0.1", "Ø20.0 ±0.10 THRU")


def test_private_review_forwards_context_size_to_ollama() -> None:
    from onyx.engineering.config import REVIEW_CONTEXT_TOKENS

    with (
        patch("onyx.engineering.config.REVIEW_MODEL", "test-vision"),
        patch("onyx.engineering.config.REVIEW_API_BASE", "http://127.0.0.1:11434"),
        patch("onyx.engineering.config.get_llm") as factory,
    ):
        private_review_llm()
    assert factory.call_args.kwargs["max_input_tokens"] == REVIEW_CONTEXT_TOKENS
    assert factory.call_args.kwargs["model_kwargs"]["num_ctx"] == REVIEW_CONTEXT_TOKENS


def test_unrelated_highlight_cannot_look_like_precise_evidence() -> None:
    from onyx.engineering.checks import ground_review_highlights
    from onyx.tools.models import DrawingMarkBox
    from onyx.tools.tool_implementations.drawing_review.spans import SheetSpan

    span = SheetSpan(
        span_id="p1s0", page=1, text="HEADER", x=0.1, y=0.1, width=0.1, height=0.1
    )
    original = result()
    original.comments[0] = original.comments[0].model_copy(
        update={
            "revised_page": 1,
            "revised_span_id": span.span_id,
            "revised_box": DrawingMarkBox(x=0.1, y=0.1, width=0.1, height=0.1),
            "evidence": "2X Ø6.6 THRU",
        }
    )
    checked = ground_review_highlights(original, [span]).comments[0]
    assert checked.revised_page_level
    assert checked.revised_span_id is None
    assert checked.revised_box == DrawingMarkBox(x=0, y=0, width=1, height=1)
    matching = span.__class__(
        span_id="p1s0", page=1, text="Ø6.6 THRU", x=0.1, y=0.1, width=0.1, height=0.1
    )
    assert (
        ground_review_highlights(original, [matching]).comments[0].revised_span_id
        == "p1s0"
    )


def test_identical_pdfs_are_rejected_before_model_inference() -> None:
    from onyx.engineering.processing import process_pair

    data = pdf()
    with pytest.raises(ReviewInputError, match="identical"):
        process_pair(data, data, "original.pdf", "revised.pdf", uuid4(), None)
