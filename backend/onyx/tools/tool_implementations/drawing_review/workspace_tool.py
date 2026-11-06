"""Expose the PDF editor's durable commands to the chat agent."""

import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from onyx.agents.tools import ToolExecutionMode, ToolInvocation
from onyx.db.drawing_workspace import (
    apply_workspace_command,
    create_workspace,
    owned_workspace,
    workspace_snapshot,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.engineering.pdf_locations import LocationQuery, locate_callouts
from onyx.engineering.workspace_files import authorized_source, describe_pdf
from onyx.engineering.workspace_models import WorkspaceCommand
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.tools.interface import Tool, parse_tool_arguments
from onyx.tools.models import ToolCallException, ToolContext
from onyx.utils.process_isolation import run_in_isolated_process


class WorkspaceToolArguments(BaseModel):
    action: Literal["open", "read", "edit", "locate"]
    document_id: str = Field(default="", max_length=256)
    queries: list[LocationQuery] = Field(default_factory=list, max_length=100)
    file_ids: list[str] = Field(default_factory=list, max_length=2)
    workspace_id: UUID | None = None
    command: WorkspaceCommand | None = None


class DrawingWorkspaceTool(Tool):
    NAME = "edit_drawing_workspace"
    DISPLAY_NAME = "Drawing Editor"
    DESCRIPTION = (
        "Use action locate with workspace_id, document_id and queries (id, page, request, evidence) "
        "to find native dimension text locally with pdfplumber. located_text identifies a callout, "
        "not verified geometry or a completed correction. Ambiguous matches have no anchor. "
        "Read and edit the user's PDF drawing workspace. Open with one or two attached file_ids, "
        "then read its version, document/page sizes, annotations, anchors and calibration. "
        "Edit with the same versioned commands as the manual editor: upsert_annotation, "
        "delete_annotation, set_anchor, calibrate, undo or redo. Use SDK top-left page points "
        "for annotation.rect; normalized top-left page fractions for issue anchors. "
        "First read the workspace. Target its exact document_id and expected_version. "
        "Use a new UUID command_id for a new edit and retain it on retry. "
        "A rectangle annotation has type 5, pageIndex (0-based), id, rect {origin:{x,y},size:{width,height}}, "
        "contents, color, strokeColor, strokeWidth, opacity and flags. "
        "Do not invent a precise location: use native evidence or ask the user to correct an anchor. "
        "Saved edits appear in the viewer and remain editable by the user. "
        "Text labels and PDF measurements do not modify CAD geometry or certify a drawing."
    )

    def __init__(self, tool_id: int, user: User) -> None:
        self._id = tool_id
        self._user = user

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @property
    def execution_mode(self) -> ToolExecutionMode:
        return ToolExecutionMode.SEQUENTIAL

    def tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=WorkspaceToolArguments.model_json_schema(),
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(WorkspaceToolArguments, invocation.arguments)
        with get_session_with_current_tenant() as session:
            if request.action == "open":
                if not request.file_ids:
                    raise ToolCallException(
                        message="Drawing files are missing",
                        llm_facing_message="Pass one or two PDF file_ids",
                    )
                documents = []
                for reference in request.file_ids:
                    data, name = authorized_source(session, self._user, reference)
                    documents.append(
                        run_in_isolated_process(
                            describe_pdf, data, reference, name, timeout=30
                        )
                    )
                result = workspace_snapshot(
                    create_workspace(session, self._user.id, documents)
                )
            elif request.workspace_id is None:
                raise ToolCallException(
                    message="Workspace is missing",
                    llm_facing_message="Open a workspace first and pass its workspace_id",
                )
            elif request.action == "locate":
                row = owned_workspace(session, request.workspace_id, self._user.id)
                if not any(
                    isinstance(item, dict) and item.get("id") == request.document_id
                    for item in row.documents
                ):
                    raise ToolCallException(
                        message="Drawing not found",
                        llm_facing_message="Use a document_id from this workspace",
                    )
                data, _ = authorized_source(session, self._user, request.document_id)
                locations = run_in_isolated_process(
                    locate_callouts, data, request.queries, timeout=30
                )
                return ToolResult(
                    content=json.dumps(
                        [item.model_dump(mode="json") for item in locations]
                    )
                )
            elif request.action == "read":
                result = workspace_snapshot(
                    owned_workspace(session, request.workspace_id, self._user.id)
                )
            elif request.command is not None:
                result = apply_workspace_command(
                    session,
                    request.workspace_id,
                    self._user.id,
                    request.command,
                    actor="agent",
                )
            else:
                raise ToolCallException(
                    message="Command is missing",
                    llm_facing_message="Pass a versioned workspace command",
                )
        return ToolResult(content=result.model_dump_json())
