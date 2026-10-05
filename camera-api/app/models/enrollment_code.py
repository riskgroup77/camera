"""Guruh (yoki bo'lim) uchun ro'yxatdan o'tish kodi.

NIMA UCHUN KERAK. Ochiq ro'yxatdan o'tish sahifasida odam o'zini
JSHSHIR bilan topadi. JSHSHIR — SIR EMAS: u hujjatda yozilgan, kadrlar
ro'yxatida bor va uni bilish qiyin emas. Tiriklik tekshiruvi esa
"kameraning oldida tirik odam turibdi"ni isbotlaydi, "AYNAN SHU odam
turibdi"ni emas. Ya'ni birovning JSHSHIRini bilgan odam o'z yuzini
uning nomiga bog'lab, davomatda va turniketda o'sha odam bo'lib
ko'rinardi, haqiqiy egasi esa keyin "siz allaqachon ro'yxatdan
o'tgansiz" degan javob olardi.

Kod shu teshikni yopadi: u faqat guruhga (yoki bo'limga) og'zaki
aytiladi yoxud chop etilgan QR kartada beriladi. Kodsiz topshirish
qabul qilinmaydi, ya'ni hujum qilish uchun endi JSHSHIRni bilishning
o'zi yetmaydi — o'sha guruhning kodi ham kerak bo'ladi.

QAMROV (scope):
  * 'guruh'   — talabalar guruhi (StudentGroup.name / group_or_position);
  * 'bolim'   — xodimning bo'limi (fakultet nomi);
  * 'umumiy'  — butun institut uchun bitta zaxira kod. U FAQAT o'z kodi
                yo'q yozuvlarga qo'llaniladi (fakulteti belgilanmagan
                xodim, o'zini o'zi qo'shgan odam). Guruhning o'z kodi
                bo'lsa — faqat o'sha kod ishlaydi.

Kodning muddati (expires_at) ixtiyoriy: semestr boshida tarqatilgan kod
semestr oxirida o'zi ishdan chiqishi mumkin. Kodni yangilash eskisini
bir zumda bekor qiladi (qator ustiga yoziladi).
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EnrollmentCode(Base):
    __tablename__ = "enrollment_codes"
    __table_args__ = (
        CheckConstraint("scope IN ('guruh', 'bolim', 'umumiy')", name="ck_enrollment_codes_scope"),
        # Bitta guruhda bitta kod: yangilash yangi qator qo'shmaydi,
        # borini almashtiradi — shunda eski kod hech qayerda qolmaydi.
        UniqueConstraint("scope", "unit_key", name="uq_enrollment_codes_scope_unit"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Solishtirish uchun tozalangan nom (kichik harf, ortiqcha bo'sh
    #: joylarsiz). 'umumiy' uchun — bo'sh satr.
    unit_key: Mapped[str] = mapped_column(String(160), nullable=False)
    #: Ekranda ko'rsatiladigan nom — admin qaysi guruh haqida ekanini ko'radi.
    unit_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    #: NULL — muddatsiz.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
