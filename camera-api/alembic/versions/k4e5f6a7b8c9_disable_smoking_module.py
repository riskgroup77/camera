"""#15 (Chekish / elektron sigareta) modulini o'chirish

Buyurtmachi qarori (2026-09-16): "chekish hozircha kerak emas".

Modul o'chiriladi, lekin O'CHIRIB TASHLANMAYDI: konfiguratsiya qatori,
tarixiy signallar va sozlamalar joyida qoladi. Kerak bo'lganda admin
"AI Modullari" sahifasidan qayta yoqadi.

Amalda bu sweepni butunlay to'xtatadi — app/jobs/smoking_ai.py ish
boshlashdan oldin is_module_active() ni tekshiradi, ya'ni kadr ham
olinmaydi, model ham chaqirilmaydi.

Revision ID: k4e5f6a7b8c9
Revises: j3d4e5f6a7b8
Create Date: 2026-09-16
"""

from alembic import op
import sqlalchemy as sa

revision = "k4e5f6a7b8c9"
down_revision = "j3d4e5f6a7b8"
branch_labels = None
depends_on = None

SMOKING_CODE = 15


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE ai_modules SET active = false WHERE code = :code").bindparams(code=SMOKING_CODE)
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE ai_modules SET active = true WHERE code = :code").bindparams(code=SMOKING_CODE)
    )
