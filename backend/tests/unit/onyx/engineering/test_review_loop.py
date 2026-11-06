from io import BytesIO
from unittest.mock import Mock

from PIL import Image

from onyx.engineering.review_loop import review_with_crops
from onyx.tools.models import CommentVerdict
from onyx.tools.tool_implementations.drawing_review.comment_queue import VerdictDraft


def image_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (600, 400), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_retries_use_different_regions_and_stop_on_supported_verdict() -> None:
    unclear = VerdictDraft(
        status=CommentVerdict.UNCLEAR, evidence="none", remaining="unreadable"
    )
    solved = VerdictDraft(status=CommentVerdict.SOLVED_CORRECT, evidence="8.0 ±0.1")
    judge = Mock(side_effect=[unclear, solved])
    result, attempts = review_with_crops(image_bytes(), judge)
    assert result == solved and attempts == 2
    assert Image.open(BytesIO(judge.call_args_list[0].args[0])).size == (600, 400)
    assert Image.open(BytesIO(judge.call_args_list[1].args[0])).size == (600, 260)


def test_identical_unclear_result_stops_without_inventing_success() -> None:
    draft = VerdictDraft(
        status=CommentVerdict.UNCLEAR, evidence="none", remaining="missing"
    )
    judge = Mock(return_value=draft)
    result, attempts = review_with_crops(image_bytes(), judge)
    assert result == draft and attempts == 2


def test_failures_are_bounded_to_three_calls() -> None:
    judge = Mock(return_value=None)
    result, attempts = review_with_crops(image_bytes(), judge)
    assert result is None and attempts == 3


def test_supported_verdict_is_preserved_when_location_retry_is_unclear() -> None:
    solved = VerdictDraft(status=CommentVerdict.SOLVED_CORRECT, evidence="8.0 ±0.1")
    unclear = VerdictDraft(
        status=CommentVerdict.UNCLEAR, evidence="none", remaining="region missing"
    )
    judge = Mock(side_effect=[solved, unclear, None])
    result, attempts = review_with_crops(
        image_bytes(), judge, accepted=lambda item: item.span_id is not None
    )
    assert result == solved and attempts == 3
