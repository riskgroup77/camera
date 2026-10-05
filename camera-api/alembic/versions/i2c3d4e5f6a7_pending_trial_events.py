"""Sinov rejimidagi modullarning navbatda kutayotgan eski signallari sinov namunalariga o'tadi

h1b2c3d4e5f6 faqat YANGI signallarni sinovga yo'naltirdi. Undan oldin
yozilgan, hali ko'rib chiqilmagan evristik signallar esa operator navbatida
qolib ketgan edi — shovqin navbatda turaverardi. Ko'rib chiqilganlari
(tasdiqlangan / rad etilgan) tegilmaydi: ular tarix va hisobotlar uchun.

Qaytarish kerak bo'lsa (modul bo'yicha):
    UPDATE events SET is_trial = false WHERE status = 'yangi' AND module_code = <kod>;
downgrade buni avtomatik qilmaydi — migratsiyadan keyin kelgan sinov
signallarini eskilaridan ajratib bo'lmaydi.

Revision ID: i2c3d4e5f6a7
Revises: h1b2c3d4e5f6
Create Date: 2026-09-16
"""

import sqlalchemy as sa
from alembic import op

revision = "i2c3d4e5f6a7"
down_revision = "h1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE events SET is_trial = true "
            "WHERE status = 'yangi' AND is_trial = false "
            "AND module_code IN (SELECT code FROM ai_modules WHERE mode = 'sinov')"
        )
    )


def downgrade() -> None:
    pass
