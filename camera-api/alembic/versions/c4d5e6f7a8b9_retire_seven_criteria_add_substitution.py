"""Yettita kriteriyani nafaqaga chiqarish va #26 (o'qituvchi almashinuvi) qo'shish

Buyurtmachi qarori (2026-09-07): #4 (egasiz qoldirilgan buyum), #5 (olomon
zichligi), #11 (bosh kiyim), #16 (imtihonda telefon), #18 (talaba
kiyim-boshi), #24 (yiqilib tushish), #25 (hovlida transport) kerak emas.
Ularning sweep kodi ham shu commitda o'chirildi.

Nima uchun konfiguratsiya qatorlari O'CHIRILADI, `active = false` emas:
admin paneldagi "AI modullar" ro'yxati aynan shu jadvaldan o'qiladi, ya'ni
o'chirilgan kriteriya u yerda ko'rinib turaverardi va uni yoqish tugmasi
ham ishlayverardi — lekin ortida hech qanday kod qolmagan. "Yoqilgan,
ammo hech narsa qilmaydigan" modul har qanday o'chirilganidan yomonroq.

Hodisalar (events) esa O'CHIRILMAYDI. Ular tarixiy yozuv: institut o'sha
paytda haqiqatan shu signalni olgan va operator uni ko'rgan. Event jadvali
module_code'ni matn sifatida saqlaydi (ai_modules ga foreign key
yo'q), shuning uchun konfiguratsiya qatori ketgach ham hodisa o'z nomi
bilan ko'rinaveradi. Yagona istisno — hech qachon operator ko'rmagan,
"yangi" holatidagi signallar: ular endi hech kim ko'rib chiqmaydigan
navbatda abadiy qolib ketardi, shuning uchun rad_etilgan deb belgilanadi.
(Qiymat AYNAN shunday — pastki chiziq bilan: events.ck_events_status
cheklovi 'yangi', 'tasdiqlangan', 'rad_etilgan' dan boshqasini qabul
qilmaydi.)

Revision ID: c4d5e6f7a8b9
Revises: e1f2a3b4c5d6
Create Date: 2026-09-07
"""

from alembic import op
import sqlalchemy as sa

revision = "c4d5e6f7a8b9"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None

RETIRED = (4, 5, 11, 16, 18, 24, 25)

SUBSTITUTION = {
    "code": 26,
    "group": "E",
    "name": "O'qituvchi o'rniga boshqasi kirgani",
    "description": (
        "Jadvalga ko'ra dars o'tishi kerak bo'lgan o'qituvchi o'rniga BOSHQA "
        "ro'yxatdan o'tgan xodim auditoriyada bo'lsa signal. #22 bilan bitta "
        "kadr, bitta detect_faces() chaqiruvidan foydalanadi. Uch holat aniq "
        "ajratiladi: o'qituvchi joyida (hodisa yo'q), boshqa xodim joyida "
        "(#26), hech kim tanilmadi (#22 kelmagan)."
    ),
    "method": (
        "InsightFace + xodimlar bo'yicha to'liq moslik qidiruvi + LessonSession "
        "jadvali (app/jobs/teacher_punctuality_ai.py)"
    ),
    "accuracy": 0,
    "threshold": 70,
    "sensitivity": "o'rta",
    "camera_count": 0,
    "active": True,
}


def upgrade() -> None:
    codes = ", ".join(str(c) for c in RETIRED)

    # Ko'rilmagan signallarni yopamiz — ularni ko'rib chiqadigan modul endi yo'q.
    op.execute(
        sa.text(
            f"UPDATE events SET status = 'rad_etilgan' "
            f"WHERE module_code IN ({codes}) AND status = 'yangi'"
        )
    )

    op.execute(sa.text(f"DELETE FROM ai_modules WHERE code IN ({codes})"))

    # Kameralarning modul-istisno ro'yxatidan ham tozalaymiz: mavjud
    # bo'lmagan kodni istisno qilib turish keyinchalik o'qiganni
    # chalg'itadi (JSONB massiv, shuning uchun elementma-element).
    op.execute(
        sa.text(
            "UPDATE cameras SET excluded_module_codes = COALESCE(("
            "  SELECT jsonb_agg(elem) FROM jsonb_array_elements(excluded_module_codes) elem"
            f"  WHERE (elem)::int NOT IN ({codes})"
            "), '[]'::jsonb) "
            "WHERE excluded_module_codes IS NOT NULL "
            "AND jsonb_typeof(excluded_module_codes) = 'array'"
        )
    )

    # #26 — INSERT ... ON CONFLICT: seed_all() ham uni qo'shishi mumkin
    # (bo'sh jadvalda), ikkalasi ham xatosiz o'tishi kerak.
    op.execute(
        sa.text(
            "INSERT INTO ai_modules "
            '(code, "group", name, description, method, accuracy, threshold, '
            "sensitivity, camera_count, active) "
            "VALUES (:code, :group, :name, :description, :method, :accuracy, "
            ":threshold, :sensitivity, :camera_count, :active) "
            "ON CONFLICT (code) DO NOTHING"
        ).bindparams(**SUBSTITUTION)
    )


def downgrade() -> None:
    """Faqat #26 ni olib tashlaydi.

    Olib tashlangan yettita kriteriyani QAYTA TIKLAMAYDI: ularning sweep
    kodi ham o'chirilgan, ya'ni konfiguratsiya qatorini qaytarish
    "yoqilgan, ammo ortida kod yo'q" holatini yaratardi — aynan shu
    holatning oldini olish uchun bu migratsiya yozilgan.
    """
    op.execute(sa.text("DELETE FROM ai_modules WHERE code = 26"))
