"""O'zini o'zi ro'yxatdan o'tkazganlar — tasdiqlanguncha tanilmaydi

Ochiq /api/public/enrollment/register orqali istalgan odam o'ziga yozuv
yaratib, yuzini qo'shib, darhol "tasdiqlangan" bo'lardi: u davomatga
tushar, "begona shaxs" tekshiruvi esa uni tanish deb o'tkazib yuborardi.

Endi bunday yozuvlar belgilanadi va yuzi administrator tasdiqlaguncha
tanish ro'yxatiga (app/services/face_matching.py) kirmaydi. Mavjud
yozuvlarning hammasi false — ular qanday yaratilganini bilib bo'lmaydi va
bugungi xatti-harakat o'zgarmaydi.

Revision ID: o8c9d0e1f2a3
Revises: n7b8c9d0e1f2
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op

revision = "o8c9d0e1f2a3"
down_revision = "n7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "students_staff",
        sa.Column("self_registered", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("students_staff", "self_registered")
