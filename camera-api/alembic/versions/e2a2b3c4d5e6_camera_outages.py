"""Kamera uzilishlari jadvali (uptime va uzilishlar tarixi uchun).

Revision ID: e2a2b3c4d5e6
Revises: d2a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e2a2b3c4d5e6"
down_revision = "d2a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "camera_outages",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_camera_outages_camera_started", "camera_outages", ["camera_id", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_camera_outages_camera_started", table_name="camera_outages")
    op.drop_table("camera_outages")
