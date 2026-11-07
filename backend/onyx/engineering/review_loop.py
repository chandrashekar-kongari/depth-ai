"""Bounded visual retries use different crops and preserve unresolved results."""

from collections.abc import Callable
from io import BytesIO

from PIL import Image

from onyx.llm.cancellation import check_cancelled
from onyx.tools.models import CommentVerdict
from onyx.tools.tool_implementations.drawing_review.comment_queue import VerdictDraft


def review_with_crops(
    image_data: bytes,
    judge: Callable[[bytes], VerdictDraft | None],
    accepted: Callable[[VerdictDraft], bool] | None = None,
    *,
    retry: Callable[[bytes, VerdictDraft | None], VerdictDraft | None] | None = None,
) -> tuple[VerdictDraft | None, int]:
    check_cancelled()
    accept = accepted or (lambda draft: draft.status != CommentVerdict.UNCLEAR)
    best = judge(image_data)
    attempts = 1
    if best is not None and accept(best):
        return best, attempts
    try:
        image = Image.open(BytesIO(image_data)).convert("RGB")
    except (OSError, ValueError):
        return best, attempts
    previous = best
    for bounds in [
        (0, 0, image.width, int(image.height * 0.65)),
        (0, int(image.height * 0.35), image.width, image.height),
    ]:
        check_cancelled()
        buffer = BytesIO()
        image.crop(bounds).save(buffer, format="PNG")
        crop = buffer.getvalue()
        candidate = retry(crop, previous) if retry is not None else judge(crop)
        attempts += 1
        if candidate is not None:
            if (
                best is None
                or best.status == CommentVerdict.UNCLEAR
                or candidate.status != CommentVerdict.UNCLEAR
            ):
                best = candidate
            if accept(candidate):
                break
            if candidate == previous and retry is None:
                break
        previous = candidate
    return best, attempts
