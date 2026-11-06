"""Add durable private engineering reviews.

Revision ID: ccd8339ba2d1
Revises: b4c8e2a91d07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "ccd8339ba2d1"
down_revision = "b4c8e2a91d07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "engineering_review",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("original_blob", sa.Text(), nullable=False),
        sa.Column("revised_blob", sa.Text(), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("revised_name", sa.String(255), nullable=False),
        sa.Column("original_sha256", sa.String(64), nullable=False),
        sa.Column("revised_sha256", sa.String(64), nullable=False),
        sa.Column("page_order_confirmed", sa.Boolean(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("model_name", sa.String(255), nullable=True),
        sa.Column("pipeline_version", sa.String(32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("owner_id", "request_key"),
    )
    op.create_index(
        "ix_engineering_review_owner_id", "engineering_review", ["owner_id"]
    )
    op.create_index(
        "ix_engineering_review_claim", "engineering_review", ["status", "lease_until"]
    )
    op.create_table(
        "engineering_review_decision",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "review_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("engineering_review.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("finding_id", sa.String(128), nullable=False),
        sa.Column("value", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_engineering_review_decision_review_id",
        "engineering_review_decision",
        ["review_id"],
    )


def downgrade() -> None:
    op.drop_table("engineering_review_decision")
    op.drop_table("engineering_review")
