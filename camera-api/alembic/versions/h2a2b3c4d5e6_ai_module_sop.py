"""AI modul uchun operator ko'rsatmasi (SOP) — hodisa ochilganda qadamlar.

Bo'sh (NULL) bo'lsa kodda yozilgan standart matn ishlatiladi
(app/services/sop.py), shuning uchun backfill kerak emas.

Revision ID: h2a2b3c4d5e6
Revises: f2a2b3c4d5e6
"""

import sqlalchemy as sa
from alembic import op

revision = "h2a2b3c4d5e6"
down_revision = "f2a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_modules", sa.Column("sop", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_modules", "sop")
