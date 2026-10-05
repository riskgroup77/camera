"""Kelib-ketish qoidalari (ish vaqti, kechikish chegarasi).

Revision ID: t1a2b3c4d5e6
Revises: s1a2b3c4d5e6
Create Date: 2026-09-19
"""

import sqlalchemy as sa
from alembic import op

revision = "t1a2b3c4d5e6"
down_revision = "s1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attendance_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("staff_start", sa.Time(), nullable=False),
        sa.Column("student_start", sa.Time(), nullable=False),
        sa.Column("grace_minutes", sa.Integer(), nullable=False),
        sa.Column("work_end", sa.Time(), nullable=False),
        sa.Column("work_days", sa.String(), nullable=False),
        sa.Column("track_last_seen", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.execute(
        "INSERT INTO attendance_policy (id, staff_start, student_start, grace_minutes, work_end, work_days, track_last_seen)"
        " VALUES (1, '08:00', '08:00', 10, '17:00', '1,2,3,4,5,6', true)"
    )


def downgrade() -> None:
    op.drop_table("attendance_policy")
