"""add comment review tool

Revision ID: b4c8e2a91d07
Revises: c3e8a1b74d09
Create Date: 2026-11-03 18:10:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "b4c8e2a91d07"
down_revision = "c3e8a1b74d09"
branch_labels = None
depends_on = None

COMMENT_REVIEW_TOOL = {
    "name": "verify_drawing_comments",
    "display_name": "Comment Review",
    "description": (
        "Check each comment on a marked-up drawing against a new drawing. "
        "Pass commented_sheet_file_id for the marked-up PDF, PNG, JPEG, or WEBP. "
        "Pass revised_sheet_file_id for the new sheet. "
        "Pass dxf_file_id for the new drawing's DXF. "
        "A number in a comment is not a measurement. "
        "DWG and STEP are not accepted."
    ),
    "in_code_tool_id": "CommentReviewTool",
    "enabled": True,
}


def upgrade() -> None:
    conn = op.get_bind()
    existing = conn.execute(
        sa.text("SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": COMMENT_REVIEW_TOOL["in_code_tool_id"]},
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
            COMMENT_REVIEW_TOOL,
        )
    else:
        conn.execute(
            sa.text("""
                INSERT INTO tool (name, display_name, description, in_code_tool_id, enabled)
                VALUES (:name, :display_name, :description, :in_code_tool_id, :enabled)
                """),
            COMMENT_REVIEW_TOOL,
        )

    conn.execute(
        sa.text("""
            INSERT INTO persona__tool (persona_id, tool_id)
            SELECT review_link.persona_id, comment_tool.id
            FROM persona__tool AS review_link
            JOIN tool AS review_tool ON review_tool.id = review_link.tool_id
            JOIN tool AS comment_tool
              ON comment_tool.in_code_tool_id = 'CommentReviewTool'
            WHERE review_tool.in_code_tool_id = 'DrawingReviewTool'
            AND NOT EXISTS (
                SELECT 1
                FROM persona__tool AS existing
                WHERE existing.persona_id = review_link.persona_id
                  AND existing.tool_id = comment_tool.id
            )
            """)
    )
    # The default assistant is persona 0. Attach the check there so a short
    # "verify" on the desktop chat can call it.
    conn.execute(
        sa.text("""
            INSERT INTO persona__tool (persona_id, tool_id)
            SELECT persona.id, comment_tool.id
            FROM persona
            JOIN tool AS comment_tool
              ON comment_tool.in_code_tool_id = 'CommentReviewTool'
            WHERE persona.id = 0
            AND NOT EXISTS (
                SELECT 1
                FROM persona__tool AS existing
                WHERE existing.persona_id = persona.id
                  AND existing.tool_id = comment_tool.id
            )
            """)
    )


def downgrade() -> None:
    conn = op.get_bind()
    in_code_tool_id = COMMENT_REVIEW_TOOL["in_code_tool_id"]
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
