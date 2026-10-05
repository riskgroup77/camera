"""Kamera: eshik hududi (face_roi) va yuzlar yo'nalishi (face_direction)

Kirish kameralarida yuz faqat eshik atrofida qidiriladi (to'liq sifatda,
kadrning qolgan qismisiz) va kamera kirayotganlarni yoki chiqayotganlarni
ko'rishi belgilanadi — kelish va ketish shu bo'yicha ajratiladi.

Revision ID: r2b3c4d5e6f7
Revises: q1a2b3c4d5e6
Create Date: 2026-09-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "r2b3c4d5e6f7"
down_revision = "q1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("face_roi", postgresql.JSONB(), nullable=True))
    op.add_column("cameras", sa.Column("face_direction", sa.String(), nullable=True))
    op.create_check_constraint(
        "ck_cameras_face_direction", "cameras", "face_direction IS NULL OR face_direction IN ('kirish', 'chiqish')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_cameras_face_direction", "cameras", type_="check")
    op.drop_column("cameras", "face_direction")
    op.drop_column("cameras", "face_roi")
