"""Kunduzgi notanish yuzlar ro'yxati (begona shaxs moduli, ko'rib chiqish rejimi).

Revision ID: w1a2b3c4d5e6
Revises: v1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "w1a2b3c4d5e6"
down_revision = "v1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "unknown_sightings",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("embedding", sa.String(), nullable=False),
        sa.Column("crop_key", sa.String(), nullable=True),
        sa.Column("face_px", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closest_similarity", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="kutilmoqda"),
        sa.Column(
            "person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students_staff.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('kutilmoqda', 'talaba', 'begona', 'otkazildi')", name="ck_unknown_sightings_status"
        ),
    )
    op.create_index("ix_unknown_sightings_day_status", "unknown_sightings", ["day", "status"])


def downgrade() -> None:
    op.drop_index("ix_unknown_sightings_day_status", table_name="unknown_sightings")
    op.drop_table("unknown_sightings")
