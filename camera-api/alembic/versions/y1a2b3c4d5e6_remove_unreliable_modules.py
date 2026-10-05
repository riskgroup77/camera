"""Ishonchsiz evristik AI modullarini olib tashlash.

Buyurtmachi qarori (2026-09-24): oq xalat (10), niqob/qo'lqop (13), janjal
(14), chekish (15), tartibsizlik (17) va yong'in (23) — o'qitilgan model emas,
qo'lda sozlangan rang/harakat qoidalari edi; real videoda sinalmagan va
yolg'on signal berardi. Kodi olib tashlandi, bu migratsiya ularning
sozlamalari va o'chirish yozuvlarini tozalaydi. O'tgan hodisalar tarix
sifatida qoladi (module_name hodisaning o'zida saqlangan).

Bir vaqtda o'lchanmagan "aniqlik" raqamlari (96,4 / 98,6 / 99,2 / 65)
nolga tushiriladi: haqiqiy aniqlik operator tasdiqlaridan hisoblanadi.

Revision ID: y1a2b3c4d5e6
Revises: x1a2b3c4d5e6
"""

from alembic import op

revision = "y1a2b3c4d5e6"
down_revision = "x1a2b3c4d5e6"
branch_labels = None
depends_on = None

REMOVED = (10, 13, 14, 15, 17, 23)


def upgrade() -> None:
    codes = ", ".join(str(code) for code in REMOVED)
    op.execute(f"DELETE FROM module_camera_suppressions WHERE module_code IN ({codes})")
    op.execute(f"DELETE FROM ai_modules WHERE code IN ({codes})")
    # Bildirishnoma qoidalaridagi ro'yxatdan ham chiqariladi (JSONB massiv).
    op.execute(
        f"""
        UPDATE notification_rules
        SET module_codes = COALESCE(
            (SELECT jsonb_agg(value) FROM jsonb_array_elements(module_codes) AS value
             WHERE value::text::int NOT IN ({codes})),
            '[]'::jsonb)
        WHERE module_codes IS NOT NULL AND jsonb_typeof(module_codes) = 'array'
        """
    )
    op.execute("UPDATE ai_modules SET accuracy = 0 WHERE ROUND(accuracy::numeric, 1) IN (96.4, 98.6, 99.2, 65.0)")


def downgrade() -> None:
    # Modullar kodi olib tashlangan — qaytarish ma'nosiz; seed yangi
    # o'rnatishda ularni yaratmaydi.
    pass
