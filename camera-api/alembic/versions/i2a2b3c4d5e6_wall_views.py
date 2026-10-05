"""Videodevor ko'rinishlari serverda (ish joylari o'rtasida umumiy).

Revision ID: i2a2b3c4d5e6
Revises: h2a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "i2a2b3c4d5e6"
down_revision = "h2a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wall_views",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False, server_default="view"),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('view', 'tour')", name="ck_wall_views_kind"),
    )
    op.create_index("ix_wall_views_owner", "wall_views", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_wall_views_owner", table_name="wall_views")
    op.drop_table("wall_views")
