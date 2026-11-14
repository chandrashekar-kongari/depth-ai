"""Add the vision review action.

Revision ID: 8f19cbef7d52
Revises: 2f284338abf9
"""

from alembic import op

revision = "8f19cbef7d52"
down_revision = "2f284338abf9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
            INSERT INTO tool (name, display_name, description, in_code_tool_id, enabled)
            VALUES (
                'review_with_vision', 'Vision Review',
                'Review or compare attached PDF and image pages using the vision model.',
                'VisionReviewTool', true
            )
            """)
    op.execute("""
            INSERT INTO persona__tool (persona_id, tool_id)
            SELECT persona.id, vision_tool.id
            FROM persona
            CROSS JOIN tool AS vision_tool
            WHERE vision_tool.in_code_tool_id = 'VisionReviewTool'
              AND (
                  persona.id = 0
                  OR EXISTS (
                      SELECT 1
                      FROM persona__tool
                      JOIN tool ON tool.id = persona__tool.tool_id
                      WHERE persona__tool.persona_id = persona.id
                        AND tool.in_code_tool_id IN ('DrawingReviewTool', 'CommentReviewTool')
                  )
              )
            """)


def downgrade() -> None:
    op.execute("""
            DELETE FROM persona__tool
            WHERE tool_id IN (SELECT id FROM tool WHERE in_code_tool_id = 'VisionReviewTool')
            """)
    op.execute("DELETE FROM tool WHERE in_code_tool_id = 'VisionReviewTool'")
