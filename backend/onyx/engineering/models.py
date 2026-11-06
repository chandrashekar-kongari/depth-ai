from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from onyx.tools.models import CommentReviewResult


class ReviewStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DecisionValue(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    NEEDS_REVIEW = "needs_review"


class DecisionRequest(BaseModel):
    value: DecisionValue
    note: str = Field(default="", max_length=2000)
    expected_version: int = Field(ge=0)


class DecisionSnapshot(BaseModel):
    finding_id: str
    value: DecisionValue
    note: str
    actor_id: UUID
    created_at: datetime
    version: int


class ReviewSnapshot(BaseModel):
    id: UUID
    status: ReviewStatus
    original_name: str
    revised_name: str
    original_sha256: str
    revised_sha256: str
    created_at: datetime
    updated_at: datetime
    attempts: int
    error: str | None
    result: CommentReviewResult | None
    decisions: list[DecisionSnapshot]
    version: int
    pipeline_version: str
    model_name: str | None
    page_order_confirmed: bool
