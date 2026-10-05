"""Yuz tekshiruvi navbati ("kulrang zona" mosliklari).

Revision ID: b2a2b3c4d5e6
Revises: y1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b2a2b3c4d5e6"
down_revision = "y1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "face_review_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students_staff.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("second_similarity", sa.Float(), nullable=True),
        sa.Column("embedding", sa.String(), nullable=False),
        sa.Column("crop_key", sa.String(), nullable=True),
        sa.Column("face_px", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="kutilmoqda"),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('kutilmoqda', 'tasdiqlandi', 'rad_etildi')", name="ck_face_review_items_status"
        ),
    )
    op.create_index("ix_face_review_items_day_status", "face_review_items", ["day", "status"])
    op.create_index(
        "ux_face_review_items_person_day_camera", "face_review_items", ["person_id", "day", "camera_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ux_face_review_items_person_day_camera", table_name="face_review_items")
    op.drop_index("ix_face_review_items_day_status", table_name="face_review_items")
    op.drop_table("face_review_items")
