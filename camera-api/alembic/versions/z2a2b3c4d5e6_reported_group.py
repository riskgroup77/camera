"""Talabaning o'zi yozgan guruhi (students_staff.reported_group).

HEMIS'da topilmagan talaba guruhi "HEMIS'da topilmadi" bo'ladi — Nazoratda
yuzlab bir kishilik soxta guruh ("20.26 gurux") o'rniga bitta ro'yxat. U
qo'lda yozgan matn yo'qolmasin: bo'limdan so'rab to'g'irlashda kerak
(app/services/hemis_reconcile.py, scripts/hemis_moslash.py belgilash).

Revision ID: z2a2b3c4d5e6
Revises: z1a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "z2a2b3c4d5e6"
down_revision = "z1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("students_staff", sa.Column("reported_group", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("students_staff", "reported_group")
