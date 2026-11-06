"""Owner-scoped drawing commands and linked evidence crops."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.drawing_workspace import (
    apply_workspace_command,
    create_workspace,
    owned_workspace,
    workspace_snapshot,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.engineering.pdf_locations import (
    LocationRequest,
    TextLocation,
    locate_callouts,
)
from onyx.engineering.workspace_files import (
    authorized_source,
    describe_pdf,
    render_region,
)
from onyx.engineering.workspace_models import (
    Anchor,
    WorkspaceCommand,
    WorkspaceCreate,
    WorkspaceDocument,
    WorkspaceSnapshot,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.process_isolation import run_in_isolated_process

router = APIRouter(prefix="/engineering/workspaces")


@router.post("")
def open_workspace(
    request: WorkspaceCreate,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    session: Session = Depends(get_session),
) -> WorkspaceSnapshot:
    documents = []
    for reference in request.file_ids:
        data, name = authorized_source(session, user, reference)
        try:
            documents.append(
                run_in_isolated_process(describe_pdf, data, reference, name, timeout=30)
            )
        except ValueError as error:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(error)) from error
    return workspace_snapshot(create_workspace(session, user.id, documents))


@router.get("/{workspace_id}")
def read_workspace(
    workspace_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    session: Session = Depends(get_session),
) -> WorkspaceSnapshot:
    return workspace_snapshot(owned_workspace(session, workspace_id, user.id))


@router.post("/{workspace_id}/commands")
def drawing_command(
    workspace_id: UUID,
    request: WorkspaceCommand,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    session: Session = Depends(get_session),
) -> WorkspaceSnapshot:
    return apply_workspace_command(session, workspace_id, user.id, request)


@router.post("/{workspace_id}/regions")
def crop_region(
    workspace_id: UUID,
    anchor: Anchor,
    document_id: str = Query(...),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    session: Session = Depends(get_session),
) -> Response:
    row = owned_workspace(session, workspace_id, user.id)
    document = next(
        (
            WorkspaceDocument.model_validate(item)
            for item in row.documents
            if isinstance(item, dict) and item.get("id") == document_id
        ),
        None,
    )
    if document is None or anchor.page > len(document.pages):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Drawing region not found")
    data, _ = authorized_source(session, user, document_id)
    image = run_in_isolated_process(render_region, data, anchor, timeout=30)
    return Response(
        content=image,
        media_type="image/png",
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/{workspace_id}/locations")
def drawing_locations(
    workspace_id: UUID,
    request: LocationRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    session: Session = Depends(get_session),
) -> list[TextLocation]:
    row = owned_workspace(session, workspace_id, user.id)
    if not any(
        isinstance(item, dict) and item.get("id") == request.document_id
        for item in row.documents
    ):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Drawing not found")
    data, _ = authorized_source(session, user, request.document_id)
    try:
        return run_in_isolated_process(
            locate_callouts, data, request.queries, timeout=30
        )
    except ValueError as error:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Drawing text could not be located"
        ) from error
