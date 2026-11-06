"""Owner-scoped drawing state with serialized, idempotent edit commands."""

import base64
import copy
import hashlib
import json
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.models import DrawingWorkspace, DrawingWorkspaceOperation
from onyx.engineering.workspace_models import (
    WorkspaceCommand,
    WorkspaceDocument,
    WorkspaceSnapshot,
    validate_annotation,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def owned_workspace(
    session: Session, workspace_id: UUID, owner: UUID, *, lock: bool = False
) -> DrawingWorkspace:
    query = select(DrawingWorkspace).where(
        DrawingWorkspace.id == workspace_id, DrawingWorkspace.owner_id == owner
    )
    row = session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Drawing workspace not found")
    return row


def workspace_snapshot(row: DrawingWorkspace) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        id=row.id,
        version=row.version,
        documents=[WorkspaceDocument.model_validate(item) for item in row.documents],
        state=row.state,
        can_undo=bool(row.undo_stack),
        can_redo=bool(row.redo_stack),
    )


def create_workspace(
    session: Session, owner: UUID, documents: list[dict[str, JsonValue]]
) -> DrawingWorkspace:
    key = hashlib.sha256(json.dumps(documents, sort_keys=True).encode()).hexdigest()
    existing = session.scalar(
        select(DrawingWorkspace).where(
            DrawingWorkspace.owner_id == owner, DrawingWorkspace.source_key == key
        )
    )
    if existing is not None:
        return existing
    row = DrawingWorkspace(
        id=uuid4(),
        owner_id=owner,
        source_key=key,
        documents=documents,
        state={"annotations": {}, "anchors": {}, "calibrations": {}},
        version=0,
        undo_stack=[],
        redo_stack=[],
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(DrawingWorkspace).where(
                DrawingWorkspace.owner_id == owner, DrawingWorkspace.source_key == key
            )
        )
        if existing is None:
            raise
        return existing
    return row


def apply_workspace_command(
    session: Session,
    workspace_id: UUID,
    owner: UUID,
    command: WorkspaceCommand,
    *,
    actor: str = "user",
) -> WorkspaceSnapshot:
    row = owned_workspace(session, workspace_id, owner, lock=True)
    request_hash = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
    previous = session.scalar(
        select(DrawingWorkspaceOperation).where(
            DrawingWorkspaceOperation.workspace_id == workspace_id,
            DrawingWorkspaceOperation.command_id == command.command_id,
        )
    )
    if previous is not None:
        if previous.request_hash != request_hash:
            raise OnyxError(
                OnyxErrorCode.CONFLICT, "Command ID was used for another edit"
            )
        return workspace_snapshot(row)
    if row.version != command.expected_version:
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "Drawing changed. Reload before applying this edit"
        )
    state = copy.deepcopy(row.state)
    undo = list(row.undo_stack)
    redo = list(row.redo_stack)
    if command.action in {"undo", "redo"}:
        source, target = (undo, redo) if command.action == "undo" else (redo, undo)
        if not source:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, "No edit to undo or redo")
        target.append(state)
        restored = source.pop()
        if not isinstance(restored, dict):
            raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, "Invalid drawing history")
        state = restored
    else:
        documents = [WorkspaceDocument.model_validate(item) for item in row.documents]
        document = next(
            (item for item in documents if item.id == command.document_id), None
        )
        if document is None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT, "Document is not in this workspace"
            )
        undo.append(copy.deepcopy(state))
        undo = undo[-30:]
        while len(undo) > 1 and len(json.dumps(undo)) > 16 * 1024 * 1024:
            undo.pop(0)
        redo = []
        _apply_document_edit(state, document, command)
    if len(json.dumps(state)) > 8 * 1024 * 1024:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Drawing workspace exceeds its size limit"
        )
    changed = session.execute(
        update(DrawingWorkspace)
        .where(
            DrawingWorkspace.id == row.id,
            DrawingWorkspace.version == command.expected_version,
        )
        .values(state=state, version=row.version + 1, undo_stack=undo, redo_stack=redo)
    )
    if changed.rowcount != 1:
        session.rollback()
        raise OnyxError(OnyxErrorCode.CONFLICT, "Drawing changed during this edit")
    session.add(
        DrawingWorkspaceOperation(
            workspace_id=row.id,
            command_id=command.command_id,
            request_hash=request_hash,
            actor=actor,
            version=command.expected_version + 1,
            command=command.model_dump(mode="json"),
        )
    )
    session.commit()
    session.refresh(row)
    return workspace_snapshot(row)


def _apply_document_edit(
    state: dict[str, JsonValue], document: WorkspaceDocument, command: WorkspaceCommand
) -> None:
    annotations = state.setdefault("annotations", {})
    anchors = state.setdefault("anchors", {})
    calibrations = state.setdefault("calibrations", {})
    if (
        not isinstance(annotations, dict)
        or not isinstance(anchors, dict)
        or not isinstance(calibrations, dict)
    ):
        raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, "Invalid drawing state")
    items = annotations.setdefault(document.id, {})
    if not isinstance(items, dict):
        raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, "Invalid drawing annotations")
    try:
        if command.action == "upsert_annotation":
            annotation = command.annotation
            if annotation is None or annotation.pageIndex >= len(document.pages):
                raise ValueError("Annotation page is missing")
            validate_annotation(annotation, document.pages[annotation.pageIndex])
            if command.appearance:
                appearance = base64.b64decode(command.appearance, validate=True)
                if len(appearance) > 2 * 1024 * 1024 or not appearance.startswith(
                    (b"%PDF", b"\x89PNG", b"\xff\xd8")
                ):
                    raise ValueError("Invalid annotation appearance")
            items[annotation.id] = {
                "annotation": annotation.model_dump(mode="json"),
                "appearance": command.appearance,
            }
            if len(items) > 1000:
                raise ValueError("A document has too many markups")
        elif command.action == "delete_annotation":
            if command.annotation is None:
                raise ValueError("Deleted markup geometry is missing")
            annotation = command.annotation
            if annotation.pageIndex >= len(document.pages):
                raise ValueError("Markup page is missing")
            validate_annotation(annotation, document.pages[annotation.pageIndex])
            items[annotation.id] = {
                "annotation": annotation.model_dump(mode="json"),
                "deleted": True,
            }
        elif command.action == "set_anchor":
            if (
                not command.issue_id
                or command.anchor is None
                or command.anchor.page > len(document.pages)
            ):
                raise ValueError("Issue anchor is missing")
            anchors[f"{document.id}:{command.issue_id}"] = command.anchor.model_dump(
                mode="json"
            )
        elif command.action == "calibrate":
            if command.page > len(document.pages) or command.units_per_point is None:
                raise ValueError("Calibration is missing")
            calibrations[f"{document.id}:{command.page}"] = {
                "units_per_point": command.units_per_point,
                "unit": command.unit,
            }
    except (ValueError, IndexError) as error:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(error)) from error
