from collections.abc import Generator
from io import BytesIO
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pypdf import PdfWriter
from sqlalchemy import JSON, Column, MetaData, Table, create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Session

from onyx.db.drawing_workspace import apply_workspace_command, create_workspace, owned_workspace
from onyx.db.models import DrawingWorkspace, DrawingWorkspaceOperation
from onyx.engineering.processing import pdf_comments
from onyx.engineering.workspace_files import describe_pdf, render_region
from onyx.engineering.workspace_models import Anchor, WorkspaceCommand
from onyx.error_handling.exceptions import OnyxError


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    metadata = MetaData()
    Table("user", metadata, Column("id", UUID(as_uuid=True), primary_key=True))
    for model in (DrawingWorkspace, DrawingWorkspaceOperation):
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def document() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=400)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def command(version: int = 0, **kwargs: object) -> WorkspaceCommand:
    return WorkspaceCommand.model_validate({"command_id": str(uuid4()), "expected_version": version, "action": "upsert_annotation", "document_id": "file-a", "annotation": {"id": "mark-1", "type": 5, "pageIndex": 0, "rect": {"origin": {"x": 20, "y": 30}, "size": {"width": 100, "height": 50}}, "contents": "Check bore"}, **kwargs})


def test_commands_survive_reload_and_are_idempotent(session: Session) -> None:
    owner = uuid4()
    descriptor = describe_pdf(document(), "file-a", "drawing.pdf")
    row = create_workspace(session, owner, [descriptor])
    assert create_workspace(session, owner, [descriptor]).id == row.id
    edit = command()
    first = apply_workspace_command(session, row.id, owner, edit)
    second = apply_workspace_command(session, row.id, owner, edit)
    assert first.version == second.version == 1
    session.expire_all()
    assert owned_workspace(session, row.id, owner).state["annotations"]["file-a"]["mark-1"]["annotation"]["contents"] == "Check bore"
    with pytest.raises(OnyxError) as error:
        apply_workspace_command(session, row.id, owner, edit.model_copy(update={"action": "undo"}))
    assert error.value.status_code == 409


def test_user_and_agent_share_history_with_version_checks(session: Session) -> None:
    owner = uuid4()
    row = create_workspace(session, owner, [describe_pdf(document(), "file-a", "drawing.pdf")])
    result = apply_workspace_command(session, row.id, owner, command(), actor="agent")
    assert result.can_undo
    undone = apply_workspace_command(session, row.id, owner, command(1, action="undo"))
    assert undone.state["annotations"] == {}
    assert undone.can_redo
    redone = apply_workspace_command(session, row.id, owner, command(2, action="redo"))
    assert redone.state == result.state
    with pytest.raises(OnyxError) as error:
        apply_workspace_command(session, row.id, owner, command())
    assert error.value.status_code == 409


def test_other_owner_and_invalid_geometry_are_rejected(session: Session) -> None:
    owner = uuid4()
    row = create_workspace(session, owner, [describe_pdf(document(), "file-a", "drawing.pdf")])
    with pytest.raises(OnyxError) as error:
        apply_workspace_command(session, row.id, uuid4(), command())
    assert error.value.status_code == 404
    edit = command()
    edit.annotation.rect.origin.x = 10000
    with pytest.raises(OnyxError) as error:
        apply_workspace_command(session, row.id, owner, edit)
    assert error.value.status_code == 400
    assert owned_workspace(session, row.id, owner).version == 0


def test_anchor_correction_and_native_deletion_are_durable(session: Session) -> None:
    owner = uuid4()
    row = create_workspace(session, owner, [describe_pdf(document(), "file-a", "drawing.pdf")])
    anchor = Anchor(page=1, x=.1, y=.2, width=.3, height=.2)
    corrected = apply_workspace_command(session, row.id, owner, command(action="set_anchor", issue_id="C01", anchor=anchor))
    assert corrected.state["anchors"]["file-a:C01"]["page"] == 1
    deleted = apply_workspace_command(session, row.id, owner, command(1, action="delete_annotation"))
    assert deleted.state["annotations"]["file-a"]["mark-1"]["deleted"]
    with pytest.raises(ValidationError):
        Anchor(page=1, x=.9, y=0, width=.2, height=.1)


def test_region_crop_renders_requested_size() -> None:
    from PIL import Image
    image = render_region(document(), Anchor(page=1, x=.1, y=.1, width=.2, height=.2))
    with Image.open(BytesIO(image)) as crop:
        assert crop.size == (360, 240)


def test_native_comment_retains_its_original_region() -> None:
    from pypdf.annotations import Text
    writer = PdfWriter(clone_from=BytesIO(document()))
    writer.add_annotation(0, Text(rect=(60, 200, 180, 280), text="Check bore"))
    output = BytesIO()
    writer.write(output)
    _, comments = pdf_comments(output.getvalue())
    box = comments[1][0].box
    assert box is not None
    assert box.x == pytest.approx(.1)
    assert box.y == pytest.approx(.3)
    assert box.width == pytest.approx(.2)
