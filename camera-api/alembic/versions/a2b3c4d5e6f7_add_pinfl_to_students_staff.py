"""students_staff jadvaliga JSHSHIR (PINFL) maydonini qo'shish

Institutning kadrlar ro'yxati JSHSHIR bilan yuritiladi va unda pasport
seriyasi umuman yo'q. Ommaviy import qilingan xodim uchun "bu qator
menman" degan savolga javob beradigan yagona ma'lumot — shu raqam.

Ustun UNIKAL: bir xil raqamli ikkita xodim bo'lishi mumkin emas. Bu
faqat ma'lumot yaxlitligi emas, import skriptining takroriy ishga
tushirilishidan ham himoya — skript mavjud qatorni yangilaydi,
ikkinchisini yaratmaydi.

NULL qiymatlar unikal cheklovga tushmaydi (PostgreSQL qoidasi), ya'ni
JSHSHIRi kiritilmagan mavjud qatorlar (talabalar, qo'lda qo'shilganlar)
o'z holicha qolaveradi.

Revision ID: a2b3c4d5e6f7
Revises: f0a1b2c3d4e5
Create Date: 2026-09-07
"""

from alembic import op
import sqlalchemy as sa

revision = "a2b3c4d5e6f7"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("students_staff", sa.Column("pinfl", sa.String(length=14), nullable=True))
    op.create_index("ix_students_staff_pinfl", "students_staff", ["pinfl"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_students_staff_pinfl", table_name="students_staff")
    op.drop_column("students_staff", "pinfl")
