"""add drawing workspace operations

Revision ID: 2f284338abf9
Revises: ccd8339ba2d1
Create Date: 2026-11-06 11:28:46.817543

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "2f284338abf9"
down_revision = "ccd8339ba2d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drawing_workspace",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column("documents", postgresql.JSONB(), nullable=False),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("undo_stack", postgresql.JSONB(), nullable=False),
        sa.Column("redo_stack", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("owner_id", "source_key"),
    )
    op.create_index("ix_drawing_workspace_owner_id", "drawing_workspace", ["owner_id"])
    op.create_table(
        "drawing_workspace_operation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drawing_workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("command", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("workspace_id", "command_id"),
    )
    op.create_index(
        "ix_drawing_workspace_operation_workspace_id",
        "drawing_workspace_operation",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_table("drawing_workspace_operation")
    op.drop_table("drawing_workspace")
