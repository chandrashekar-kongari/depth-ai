"""Owner-scoped private review pilot, separate from chat file processing."""

import hashlib
from io import BytesIO
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session
from onyx.db.engineering_review import (
    cancel_review,
    find_request,
    list_reviews,
    owned_review,
    record_decision,
    save_review,
    snapshot,
)
from onyx.db.enums import Permission
from onyx.db.models import EngineeringReview, User
from onyx.engineering.config import MAX_PDF_BYTES, REVIEW_ENABLED
from onyx.engineering.models import DecisionRequest, ReviewSnapshot
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.api_key_usage import check_api_key_usage
from onyx.server.query_and_chat.token_limit import check_token_rate_limits
from shared_configs.configs import MULTI_TENANT


def require_reviews() -> None:
    if not REVIEW_ENABLED or MULTI_TENANT:
        raise OnyxError(
            OnyxErrorCode.FEATURE_DISABLED,
            "Private reviews are not enabled for this deployment",
        )


router = APIRouter(prefix="/engineering/reviews")


@router.get("/capabilities")
def capabilities(
    _user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> dict[str, bool]:
    return {"enabled": REVIEW_ENABLED and not MULTI_TENANT}


async def read_pdf(upload: UploadFile) -> tuple[bytes, str]:
    data = await upload.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES or not data.startswith(b"%PDF-"):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Upload a PDF of at most 20 MiB")
    name = (upload.filename or "drawing.pdf").replace("\\", "/").split("/")[-1][:255]
    return data, name if name.lower().endswith(".pdf") else "drawing.pdf"


@router.post("", dependencies=[Depends(require_reviews)])
async def create_review(
    original: UploadFile = File(...),
    revised: UploadFile = File(...),
    request_key: UUID = Form(...),
    page_order_confirmed: bool = Form(...),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    session: Session = Depends(get_session),
    _budget: None = Depends(check_token_rate_limits),
    _usage: None = Depends(check_api_key_usage),
) -> ReviewSnapshot:
    if not page_order_confirmed:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Confirm that both PDFs contain the same sheets in the same order",
        )
    original_data, original_name = await read_pdf(original)
    revised_data, revised_name = await read_pdf(revised)
    old_hash, new_hash = (
        hashlib.sha256(original_data).hexdigest(),
        hashlib.sha256(revised_data).hexdigest(),
    )
    if old_hash == new_hash:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Original and revised PDFs are identical. Upload the revised drawing.",
        )
    existing = find_request(session, user.id, request_key)
    if existing:
        if existing.original_sha256 != old_hash or existing.revised_sha256 != new_hash:
            raise OnyxError(
                OnyxErrorCode.CONFLICT,
                "Request key was already used for different PDFs",
            )
        return snapshot(session, existing)
    review_id = uuid4()
    store = get_default_file_store()
    stored: list[str] = []
    try:
        for role, data, name in [
            ("original", original_data, original_name),
            ("revised", revised_data, revised_name),
        ]:
            stored.append(
                store.save_file(
                    BytesIO(data),
                    display_name=name,
                    file_origin=FileOrigin.OTHER,
                    file_type="application/pdf",
                    file_id=f"engineering/{review_id}/{role}",
                )
            )
        row = EngineeringReview(
            id=review_id,
            owner_id=user.id,
            request_key=request_key,
            original_blob=stored[0],
            revised_blob=stored[1],
            original_name=original_name,
            revised_name=revised_name,
            original_sha256=old_hash,
            revised_sha256=new_hash,
            page_order_confirmed=True,
        )
        save_review(session, row)
    except Exception as error:
        session.rollback()
        # Only a confirmed rolled-back transaction permits deleting inputs.
        # Connection failures can have an ambiguous commit outcome.
        if isinstance(error, IntegrityError):
            for blob_id in stored:
                store.delete_file(blob_id, error_on_missing=False)
            existing = find_request(session, user.id, request_key)
            if (
                existing
                and existing.original_sha256 == old_hash
                and existing.revised_sha256 == new_hash
            ):
                return snapshot(session, existing)
        raise
    return snapshot(session, row)


@router.get("", dependencies=[Depends(require_reviews)])
def get_reviews(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    session: Session = Depends(get_session),
) -> list[ReviewSnapshot]:
    return list_reviews(session, user.id, limit, offset)


@router.get("/{review_id}", dependencies=[Depends(require_reviews)])
def get_review(
    review_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    session: Session = Depends(get_session),
) -> ReviewSnapshot:
    return snapshot(session, owned_review(session, review_id, user.id))


@router.post("/{review_id}/cancel", dependencies=[Depends(require_reviews)])
def cancel(
    review_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    session: Session = Depends(get_session),
) -> ReviewSnapshot:
    return cancel_review(session, review_id, user.id)


@router.patch(
    "/{review_id}/findings/{finding_id}/decision",
    dependencies=[Depends(require_reviews)],
)
def decide(
    review_id: UUID,
    finding_id: str,
    request: DecisionRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    session: Session = Depends(get_session),
) -> ReviewSnapshot:
    return record_decision(session, review_id, user.id, finding_id, request)


@router.get("/{review_id}/files/{role}", dependencies=[Depends(require_reviews)])
def review_file(
    review_id: UUID,
    role: Literal["original", "revised"],
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    session: Session = Depends(get_session),
) -> Response:
    row = owned_review(session, review_id, user.id)
    with get_default_file_store().read_file(
        row.original_blob if role == "original" else row.revised_blob, mode="b"
    ) as source:
        data = source.read()
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{review_id}/export", dependencies=[Depends(require_reviews)])
def export_review(
    review_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    session: Session = Depends(get_session),
) -> Response:
    document = snapshot(session, owned_review(session, review_id, user.id, lock=True))
    return Response(
        content=document.model_dump_json(indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="review-{review_id}-v{document.version}.json"',
            "Cache-Control": "private, no-store",
        },
    )
