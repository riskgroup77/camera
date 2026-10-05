"""students_staff: ro'yxat va qamrov so'rovlari uchun indekslar

"Talabalar va Xodimlar" sahifasi har doim tur (xodim/talaba) bo'yicha
filtrlanadi va F.I.Sh. bo'yicha saralanadi; qamrov bloki esa tur va yuz
holati bo'yicha guruhlanadi. 6 700+ qatorli jadvalda ikkalasi ham to'liq
skan qilardi.

Revision ID: g8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-09-15
"""

import sqlalchemy as sa
from alembic import op

revision = "g8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_students_staff_type_full_name", "students_staff", "type, full_name"),
    ("ix_students_staff_type_biometrics", "students_staff", "type, biometrics_status"),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.execute(sa.text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})"))


def downgrade() -> None:
    for name, _table, _columns in INDEXES:
        op.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))
