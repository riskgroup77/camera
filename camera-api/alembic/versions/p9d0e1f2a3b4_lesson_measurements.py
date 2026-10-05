"""Dars ko'rsatkichlari: "o'lchanmagan" va "0%" endi farqlanadi

Diqqat (#19) va o'qituvchi faolligi (#21) davomiy o'rtacha sifatida
yoziladi, lekin namunalar soni faqat jarayon xotirasida edi: qayta ishga
tushgach o'rtacha boshidan boshlanardi va "hali o'lchanmagan" darsni
ajratib bo'lmasdi. Qo'lda yaratilgan va import qilingan darslar esa
soxta 50% / 50% / "vaqtida keldi" bilan boshlanardi — hisobotda ular
haqiqiy o'lchovdek ko'rinardi.

Endi namunalar soni ustunlarda saqlanadi, teacher_on_time esa
tekshirilmaguncha NULL.

Mavjud qatorlar: 0 va 50 — yaratilgandagi standart qiymatlar, ya'ni
o'lchanmagan deb hisoblanadi (production'da dars jadvali deyarli bo'sh
edi). Boshqa qiymat kamida bitta o'lchov bo'lganini bildiradi.
Hech qachon tekshirilmagan darsning "vaqtida keldi" belgisi olib
tashlanadi.

Revision ID: p9d0e1f2a3b4
Revises: o8c9d0e1f2a3
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op

revision = "p9d0e1f2a3b4"
down_revision = "o8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lesson_sessions", sa.Column("attention_samples", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "lesson_sessions", sa.Column("activity_samples", sa.Integer(), nullable=False, server_default="0")
    )
    op.execute("UPDATE lesson_sessions SET attention_samples = 1 WHERE attention_score NOT IN (0, 50)")
    op.execute("UPDATE lesson_sessions SET activity_samples = 1 WHERE teacher_activity_score NOT IN (0, 50)")
    op.alter_column("lesson_sessions", "teacher_on_time", existing_type=sa.Boolean(), nullable=True)
    op.execute("UPDATE lesson_sessions SET teacher_on_time = NULL WHERE punctuality_checked_at IS NULL")


def downgrade() -> None:
    op.execute("UPDATE lesson_sessions SET teacher_on_time = TRUE WHERE teacher_on_time IS NULL")
    op.alter_column("lesson_sessions", "teacher_on_time", existing_type=sa.Boolean(), nullable=False)
    op.drop_column("lesson_sessions", "activity_samples")
    op.drop_column("lesson_sessions", "attention_samples")
