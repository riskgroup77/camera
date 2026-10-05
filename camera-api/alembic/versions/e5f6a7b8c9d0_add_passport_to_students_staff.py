"""add passport_series/passport_number to students_staff

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("students_staff", sa.Column("passport_series", sa.String(length=4), nullable=True))
    op.add_column("students_staff", sa.Column("passport_number", sa.String(length=10), nullable=True))
    # Partial unique index — only enforced when both are set, so existing
    # NULL rows (and future bulk-imported rows before their passport data
    # lands) never collide with each other.
    op.execute(
        "CREATE UNIQUE INDEX ix_students_staff_passport ON students_staff "
        "(passport_series, passport_number) WHERE passport_series IS NOT NULL AND passport_number IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_students_staff_passport")
    op.drop_column("students_staff", "passport_number")
    op.drop_column("students_staff", "passport_series")
