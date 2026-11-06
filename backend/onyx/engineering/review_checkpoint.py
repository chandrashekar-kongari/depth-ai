"""Short-lived, owner-scoped checkpoints for accepted per-comment results."""

import hashlib

from pydantic import ValidationError

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.tools.models import CommentVerdict, DrawingComment
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ReviewCheckpoint:
    def __init__(self, namespace: str) -> None:
        self.namespace = namespace
        self.cache = get_cache_backend(operation_timeout_s=1)

    def _key(self, comment: DrawingComment) -> str:
        identity = f"{self.namespace}:{comment.page}:{comment.text}:{comment.request}"
        return "drawing-review-v1:" + hashlib.sha256(identity.encode()).hexdigest()

    def read(self, comment: DrawingComment) -> DrawingComment | None:
        try:
            value = self.cache.get(self._key(comment))
            result = DrawingComment.model_validate_json(value) if value else None
            if result and result.verdict != CommentVerdict.UNCLEAR:
                return result.model_copy(update={"id": comment.id})
        except (*CACHE_TRANSIENT_ERRORS, ValidationError):
            logger.warning("Drawing checkpoint unavailable; processing normally")
        return None

    def write(self, comment: DrawingComment) -> None:
        if comment.verdict == CommentVerdict.UNCLEAR:
            return
        try:
            self.cache.set(self._key(comment), comment.model_dump_json(), ex=86400)
        except CACHE_TRANSIENT_ERRORS:
            logger.warning("Drawing checkpoint could not be saved")
