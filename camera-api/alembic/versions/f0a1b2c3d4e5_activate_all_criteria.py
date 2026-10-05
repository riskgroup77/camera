"""Barcha 19 ta kriteriyani yoqish

Buyurtmachi talabi (2026-09-07): topshiriladigan hujjatda kriteriyalar
"o'chirilgan" holatida turmasligi kerak.

Bu shunchaki hujjatdagi yozuvni almashtirish emas — modullar HAQIQATAN
yoqiladi, chunki hujjatda yozilgan narsa tizimdagi holat bilan mos
kelishi shart. Yoqish xavfsiz, chunki har bir kriteriyaning ortida
haqiqiy aniqlash kodi bor (has_detector = true — bu ustun aynan shu
farqni ajratish uchun kiritilgan).

Yoqilgan modul avtomatik ravishda signal beradi degani emas. Ko'pchiligi
kirish ma'lumotiga bog'liq va u kelmaguncha jim turadi:

  #2  — kamera uchun taqiqlangan zona poligoni chizilmagan
  #10, #12, #13, #15 — biometrikasi tasdiqlangan xodim ro'yxati kerak
  #19, #21, #22, #26 — dars jadvali (LessonSession) kerak

Ya'ni ular uchun "yoqilgan" — bu "ma'lumot kelishi bilan darhol ishlay
boshlaydi" degani, "hozir signal yog'diradi" degani emas. Aksincha, #14
(jang/nizolashish) va #15 (chekish) yoqilgach darhol signal berishi
mumkin va ular tizimdagi eng qo'pol evristikalar — shu sabab ularning
signallari operator tasdig'isiz monitoring devoriga chiqmaydi
(app/routers/events.py, status='tasdiqlangan' filtri).

Revision ID: f0a1b2c3d4e5
Revises: d8e9f0a1b2c3
Create Date: 2026-09-07
"""

from alembic import op
import sqlalchemy as sa

revision = "f0a1b2c3d4e5"
down_revision = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # has_detector = false bo'lgan qator qolmagan, lekin shart baribir
    # yoziladi: kelajakda aniqlash kodisiz registr qatori qo'shilsa, bu
    # migratsiya uni yoqib yubormaydi.
    op.execute(sa.text("UPDATE ai_modules SET active = true WHERE has_detector = true"))


def downgrade() -> None:
    """Avvalgi holatni tiklamaydi.

    Qaysi modul qachon va nima uchun o'chirilgani hech qayerda
    saqlanmagan (ai_modules.active — oddiy bayroq, tarixi yo'q), ya'ni
    "avvalgidek qilish" uchun ma'lumot yo'q. To'g'ri xatti-harakat —
    hech narsa qilmaslik: administrator kerakli modulni panel orqali
    o'chiradi.
    """
    pass
