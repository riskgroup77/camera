"""#7 (Talaba davomati) modulini vaqtincha to'xtatish

Buyurtmachi qarori (2026-09-16). Sabab productionda o'lchandi: 5935 ta
talabadan atigi BITTASINING yuzi ro'yxatdan o'tgan. Ya'ni modul ishlab
tursa ham hech kimni tanay olmaydi — kirish kameralaridagi yuzlarning
aksariyati bazada yo'q odamlarga tegishli, hisobotlarda esa talabalar
davomati abadiy 0% bo'lib ko'rinadi.

Modul o'chiriladi, o'chirib tashlanmaydi: talabalar biometrikasi
yig'ilgach admin "AI Modullari" sahifasidan qayta yoqadi. Xodimlar
davomati (#6) o'z holicha ishlashda davom etadi — davomat sweepi ikkala
kriteriyaga xizmat qiladi va faqat ikkalasi ham o'chirilganda to'xtaydi.

Tarixiy yozuvlarga tegilmaydi.

Revision ID: l5f6a7b8c9d0
Revises: k4e5f6a7b8c9
Create Date: 2026-09-16
"""

from alembic import op
import sqlalchemy as sa

revision = "l5f6a7b8c9d0"
down_revision = "k4e5f6a7b8c9"
branch_labels = None
depends_on = None

STUDENT_ATTENDANCE_CODE = 7


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE ai_modules SET active = false WHERE code = :code").bindparams(
            code=STUDENT_ATTENDANCE_CODE
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE ai_modules SET active = true WHERE code = :code").bindparams(
            code=STUDENT_ATTENDANCE_CODE
        )
    )
