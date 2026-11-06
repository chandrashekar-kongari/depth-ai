"""All review queries, ownership checks, leases and fenced writes."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from onyx.db.models import EngineeringReview, EngineeringReviewDecision
from onyx.engineering.models import (
    DecisionRequest,
    DecisionSnapshot,
    DecisionValue,
    ReviewSnapshot,
    ReviewStatus,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.tools.models import CommentReviewResult

LEASE_SECONDS = 60
MAX_ATTEMPTS = 3


def owned_review(
    session: Session, review_id: UUID, owner_id: UUID, *, lock: bool = False
) -> EngineeringReview:
    query = select(EngineeringReview).where(
        EngineeringReview.id == review_id, EngineeringReview.owner_id == owner_id
    )
    if lock:
        query = query.with_for_update()
    row = session.scalar(query)
    if row is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Review not found")
    return row


def find_request(
    session: Session, owner_id: UUID, request_key: UUID
) -> EngineeringReview | None:
    return session.scalar(
        select(EngineeringReview).where(
            EngineeringReview.owner_id == owner_id,
            EngineeringReview.request_key == request_key,
        )
    )


def save_review(session: Session, row: EngineeringReview) -> None:
    session.add(row)
    session.commit()
    session.refresh(row)


def snapshot(session: Session, row: EngineeringReview) -> ReviewSnapshot:
    decisions = session.scalars(
        select(EngineeringReviewDecision)
        .where(EngineeringReviewDecision.review_id == row.id)
        .order_by(EngineeringReviewDecision.version)
    ).all()
    return ReviewSnapshot(
        id=row.id,
        status=ReviewStatus(row.status),
        original_name=row.original_name,
        revised_name=row.revised_name,
        original_sha256=row.original_sha256,
        revised_sha256=row.revised_sha256,
        created_at=row.created_at,
        updated_at=row.updated_at,
        attempts=row.attempts,
        error=row.error,
        result=CommentReviewResult.model_validate(row.result)
        if row.result is not None
        else None,
        decisions=[
            DecisionSnapshot(
                finding_id=d.finding_id,
                value=DecisionValue(d.value),
                note=d.note,
                actor_id=d.actor_id,
                created_at=d.created_at,
                version=d.version,
            )
            for d in decisions
        ],
        version=row.version,
        pipeline_version=row.pipeline_version,
        model_name=row.model_name,
        page_order_confirmed=row.page_order_confirmed,
    )


def list_reviews(
    session: Session, owner_id: UUID, limit: int, offset: int
) -> list[ReviewSnapshot]:
    rows = session.scalars(
        select(EngineeringReview)
        .where(EngineeringReview.owner_id == owner_id)
        .order_by(EngineeringReview.created_at.desc(), EngineeringReview.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [snapshot(session, row) for row in rows]


def claim_review(session: Session) -> tuple[UUID, UUID] | None:
    eligible = or_(
        EngineeringReview.status == "queued",
        (EngineeringReview.status == "running")
        & (EngineeringReview.lease_until < func.now()),
    )
    row = session.scalar(
        select(EngineeringReview)
        .where(eligible)
        .order_by(EngineeringReview.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if row is None:
        return None
    if row.attempts >= MAX_ATTEMPTS:
        row.status = "failed"
        row.error = "Processing stopped after repeated worker interruptions. Submit a new review."
        row.lease_token = None
        row.lease_until = None
        row.updated_at = datetime.now(timezone.utc)
        session.commit()
        return None
    token = uuid4()
    row.status = "running"
    row.attempts += 1
    row.lease_token = token
    row.lease_until = datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS)
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    return row.id, token


def heartbeat(session: Session, review_id: UUID, token: UUID) -> bool:
    changed = session.scalar(
        update(EngineeringReview)
        .where(
            EngineeringReview.id == review_id,
            EngineeringReview.status == "running",
            EngineeringReview.lease_token == token,
            EngineeringReview.lease_until > func.now(),
        )
        .values(
            lease_until=datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS),
            updated_at=func.now(),
        )
        .returning(EngineeringReview.id)
    )
    session.commit()
    return changed is not None


def worker_input(
    session: Session, review_id: UUID, token: UUID
) -> EngineeringReview | None:
    row = session.scalar(
        select(EngineeringReview).where(
            EngineeringReview.id == review_id,
            EngineeringReview.lease_token == token,
            EngineeringReview.status == "running",
        )
    )
    if row is not None:
        session.expunge(row)
    return row


def finish_review(
    session: Session,
    review_id: UUID,
    token: UUID,
    *,
    result: CommentReviewResult | None = None,
    error: str | None = None,
    model_name: str | None = None,
) -> bool:
    statement = (
        update(EngineeringReview)
        .where(
            EngineeringReview.id == review_id,
            EngineeringReview.lease_token == token,
            EngineeringReview.status == "running",
            EngineeringReview.lease_until > func.now(),
        )
        .values(
            status="failed" if error else "ready",
            result=result.model_dump(mode="json") if result else None,
            error=error,
            model_name=model_name,
            lease_token=None,
            lease_until=None,
            updated_at=func.now(),
        )
    )
    changed = session.scalar(statement.returning(EngineeringReview.id))
    session.commit()
    return changed is not None


def cancel_review(session: Session, review_id: UUID, owner_id: UUID) -> ReviewSnapshot:
    row = owned_review(session, review_id, owner_id, lock=True)
    if row.status in {"queued", "running"}:
        row.status = "cancelled"
        row.lease_token = None
        row.lease_until = None
        row.updated_at = datetime.now(timezone.utc)
        session.commit()
    return snapshot(session, row)


def record_decision(
    session: Session,
    review_id: UUID,
    owner_id: UUID,
    finding_id: str,
    request: DecisionRequest,
) -> ReviewSnapshot:
    row = owned_review(session, review_id, owner_id, lock=True)
    if row.status != "ready" or row.result is None:
        raise OnyxError(OnyxErrorCode.CONFLICT, "Review is not ready")
    if row.version != request.expected_version:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "Review changed. Reload before saving your decision.",
        )
    result = CommentReviewResult.model_validate(row.result)
    valid_ids = {c.id for c in result.comments} | {
        issue.id for issue in result.extra_issues
    }
    if finding_id not in valid_ids:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Finding not found")
    row.version += 1
    row.updated_at = datetime.now(timezone.utc)
    session.add(
        EngineeringReviewDecision(
            review_id=row.id,
            finding_id=finding_id,
            value=request.value.value,
            note=request.note,
            actor_id=owner_id,
            version=row.version,
        )
    )
    session.commit()
    return snapshot(session, row)
