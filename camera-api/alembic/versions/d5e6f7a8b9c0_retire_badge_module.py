"""#12 (ID-badge) kriteriyasini nafaqaga chiqarish

Buyurtmachi qarori (2026-09-15): beyjik evristikasi (ko'krak hududidagi
to'rtburchak kontur) bir daqiqada o'nlab past ishonchli yolg'on signal
berardi — kiyimdagi har qanday cho'ntak, tugma yoki yozuv "beyjik" bo'lib
chiqardi. Haqiqiy beyjik detektori yo'q, shuning uchun modul butunlay
olib tashlandi: sweep kodi ham shu commitda o'chirildi.

Qoidalar c4d5e6f7a8b9 bilan bir xil: konfiguratsiya qatori o'chiriladi,
hodisalar tarix sifatida qoladi, faqat hech kim ko'rmagan "yangi"
signallar rad_etilgan deb yopiladi.

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-09-15
"""

from alembic import op
import sqlalchemy as sa

revision = "d5e6f7a8b9c0"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None

BADGE_CODE = 12


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE events SET status = 'rad_etilgan' WHERE module_code = :code AND status = 'yangi'").bindparams(
            code=BADGE_CODE
        )
    )
    op.execute(sa.text("DELETE FROM ai_modules WHERE code = :code").bindparams(code=BADGE_CODE))
    op.execute(
        sa.text(
            "UPDATE cameras SET excluded_module_codes = COALESCE(("
            "  SELECT jsonb_agg(elem) FROM jsonb_array_elements(excluded_module_codes) elem"
            "  WHERE (elem)::int <> :code"
            "), '[]'::jsonb) "
            "WHERE excluded_module_codes IS NOT NULL "
            "AND jsonb_typeof(excluded_module_codes) = 'array'"
        ).bindparams(code=BADGE_CODE)
    )


def downgrade() -> None:
    """Qayta tiklamaydi: ortida kod yo'q modulni qaytarish "yoqilgan, ammo
    hech narsa qilmaydigan" holatni yaratadi."""
