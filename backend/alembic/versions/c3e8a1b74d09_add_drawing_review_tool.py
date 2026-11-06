"""add drawing review tool

Revision ID: c3e8a1b74d09
Revises: b7d2e4f1a9c3
Create Date: 2026-11-01 14:10:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "c3e8a1b74d09"
down_revision = "b7d2e4f1a9c3"
branch_labels = None
depends_on = None

DRAWING_REVIEW_TOOL = {
    "name": "review_drawing",
    "display_name": "Drawing Review",
    "description": (
        "Review a mechanical drawing. Pass dxf_file_id for measurements, layers, "
        "blocks, and text from a DXF file. Pass sheet_file_id for comments on a "
        "plotted PDF, PNG, JPEG, or WEBP sheet. At least one file id is required. "
        "DWG is not accepted. Export DXF. Do not treat sheet comments as measurements."
    ),
    "in_code_tool_id": "DrawingReviewTool",
    "enabled": True,
}


def upgrade() -> None:
    conn = op.get_bind()
    existing = conn.execute(
        sa.text("SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": DRAWING_REVIEW_TOOL["in_code_tool_id"]},
    ).fetchone()

    if existing:
        conn.execute(
            sa.text("""
                UPDATE tool
                SET name = :name,
                    display_name = :display_name,
                    description = :description,
                    enabled = :enabled
                WHERE in_code_tool_id = :in_code_tool_id
                """),
            DRAWING_REVIEW_TOOL,
        )
        return

    conn.execute(
        sa.text("""
            INSERT INTO tool (name, display_name, description, in_code_tool_id, enabled)
            VALUES (:name, :display_name, :description, :in_code_tool_id, :enabled)
            """),
        DRAWING_REVIEW_TOOL,
    )


def downgrade() -> None:
    conn = op.get_bind()
    in_code_tool_id = DRAWING_REVIEW_TOOL["in_code_tool_id"]
    conn.execute(
        sa.text("""
            DELETE FROM persona__tool
            WHERE tool_id IN (
                SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id
            )
            """),
        {"in_code_tool_id": in_code_tool_id},
    )
    conn.execute(
        sa.text("DELETE FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": in_code_tool_id},
    )
