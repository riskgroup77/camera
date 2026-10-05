"""events.reviewed_at — operator qaror qilgan payt

Hodisalar jurnali "o'rtacha ko'rib chiqish vaqti"ni ko'rsatadi: jiddiy
signal kelgandan operator tasdiqlagan/rad etganiga qadar qancha vaqt
o'tgani — xavfsizlik markazi uchun asosiy ko'rsatkichlardan biri. Ilgari
faqat kim ko'rib chiqqani (reviewed_by) yozilardi, qachonligi emas.

Mavjud ko'rib chiqilgan hodisalarda NULL qoladi: ularning haqiqiy vaqti
noma'lum, taxminiy qiymat esa o'rtachani buzardi.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-15
"""

import sqlalchemy as sa
from alembic import op

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "reviewed_at")
