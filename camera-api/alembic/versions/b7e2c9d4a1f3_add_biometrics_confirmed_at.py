"""students_staff jadvaliga yuz tasdiqlangan aniq vaqtni qo'shish

Shu paytgacha yuz tasdiqlanganda faqat holat ("tasdiqlangan"), rasm va
vektor saqlanardi — QACHON tasdiqlangani hech qayerga yozilmasdi. Ochiq
ro'yxatdan o'tish sahifasi audit jurnaliga ham yozmaydi. Natijada "bu
odam soat nechida yuzini tasdiqlagan?" degan savolga javob yo'q edi.

Ustun bo'sh (NULL) holda qo'shiladi va migratsiyada to'ldirilmaydi:
eski tasdiqlashlar uchun aniq vaqtning yagona ishonchli manbai — yuz
rasmining MinIO'ga yuklangan payti, uni esa migratsiya ichidan o'qib
bo'lmaydi. Admin paneli bu vaqtni so'ralganda o'zi o'qiydi va "rasm
saqlangan vaqtdan tiklandi" deb belgilaydi (app/routers/students_staff.py).

Revision ID: b7e2c9d4a1f3
Revises: a2b3c4d5e6f7
Create Date: 2026-09-14
"""

from alembic import op
import sqlalchemy as sa

revision = "b7e2c9d4a1f3"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "students_staff",
        sa.Column("biometrics_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("students_staff", "biometrics_confirmed_at")
