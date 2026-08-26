"""Scale indexes for attendance stats and AI sweep event dedup.

Revision ID: a1b2c3d4e5f6
Revises: p3_modules_has_detector
Create Date: 2026-08-26

P1 — 300 cameras / 10k students load profile:
- attendance_records(date): /api/public/stats WHERE date = today
- attendance_records(date, status): same path + report aggregations
- events(camera_id, module_code, occurred_at): _recently_flagged() on every sweep tick
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "p3_modules_has_detector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_attendance_records_date", "attendance_records", ["date"], unique=False)
    op.create_index(
        "ix_attendance_records_date_status",
        "attendance_records",
        ["date", "status"],
        unique=False,
    )
    op.create_index(
        "ix_events_camera_module_occurred",
        "events",
        ["camera_id", "module_code", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_events_camera_module_occurred", table_name="events")
    op.drop_index("ix_attendance_records_date_status", table_name="attendance_records")
    op.drop_index("ix_attendance_records_date", table_name="attendance_records")
