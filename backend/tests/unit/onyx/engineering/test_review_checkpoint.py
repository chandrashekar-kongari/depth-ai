from unittest.mock import Mock, patch

from onyx.engineering.review_checkpoint import ReviewCheckpoint
from onyx.tools.models import CommentVerdict, DrawingComment


def comment() -> DrawingComment:
    return DrawingComment(
        id="c1",
        page=1,
        text="Bore",
        request="Add tolerance",
        verdict=CommentVerdict.SOLVED_CORRECT,
        evidence="Ø20.0 ±0.1",
        remaining="",
    )


def test_owner_scoped_checkpoints_restore_accepted_results_only() -> None:
    with patch(
        "onyx.engineering.review_checkpoint.get_cache_backend", return_value=Mock()
    ) as factory:
        first = ReviewCheckpoint("owner-a:file-hashes:qwen")
        second = ReviewCheckpoint("owner-b:file-hashes:qwen")
    row = comment()
    assert first._key(row) != second._key(row)
    first.write(row)
    factory.return_value.set.assert_called_once_with(
        first._key(row), row.model_dump_json(), ex=86400
    )
    factory.return_value.get.return_value = row.model_dump_json().encode()
    assert first.read(row) == row
    factory.assert_called_with(operation_timeout_s=1)


def test_unclear_verdict_is_not_cached_as_complete() -> None:
    with patch(
        "onyx.engineering.review_checkpoint.get_cache_backend", return_value=Mock()
    ) as factory:
        cache = ReviewCheckpoint("owner:file:model")
    cache.write(comment().model_copy(update={"verdict": CommentVerdict.UNCLEAR}))
    factory.return_value.set.assert_not_called()
