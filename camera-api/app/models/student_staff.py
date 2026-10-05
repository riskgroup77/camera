import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, false, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.org import Faculty


class StudentStaff(Base):
    __tablename__ = "students_staff"
    __table_args__ = (
        CheckConstraint("type IN ('talaba', 'xodim')", name="ck_students_staff_type"),
        CheckConstraint(
            "biometrics_status IN ('tasdiqlangan', 'kutilmoqda', 'yoq')",
            name="ck_students_staff_biometrics_status",
        ),
        # Ro'yxat har doim tur bo'yicha filtrlanib F.I.Sh. bo'yicha saralanadi,
        # qamrov esa tur va yuz holati bo'yicha guruhlanadi (g8b9c0d1e2f3).
        Index("ix_students_staff_type_full_name", "type", "full_name"),
        Index("ix_students_staff_type_biometrics", "type", "biometrics_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    # Used only to self-identify for the public self-service face-enrollment
    # flow (app/routers/enrollment.py) — an admin-imported record has no
    # login/password, so passport series+number is the one piece of
    # information the person themselves can supply to prove "this row is
    # me". Uzbek passport format: 2-letter series (e.g. "AD") + 7-digit
    # number. Nullable — existing/bulk-imported rows won't have this until
    # the Excel import that populates it is run.
    passport_series: Mapped[str | None] = mapped_column(String(4), nullable=True)
    passport_number: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # JSHSHIR (PINFL) — 14 raqamli shaxsiy identifikatsiya raqami.
    #
    # Institutning kadrlar ro'yxati aynan shu raqam bilan yuritiladi va
    # pasport seriyasi u yerda umuman yo'q. Ya'ni ommaviy import qilingan
    # xodim uchun "bu qator menman" degan savolga javob beradigan yagona
    # ma'lumot — shu. Pasport maydonlari o'z holicha qoldirildi: ular
    # ilgari ro'yxatdan o'tganlar uchun ishlashda davom etadi.
    #
    # UNIKAL: bir xil raqamli ikkita xodim bo'lishi mumkin emas, va bu
    # import skriptining takroriy ishga tushirilishidan ham himoya qiladi
    # — u mavjud qatorni yangilaydi, ikkinchisini yaratmaydi.
    pinfl: Mapped[str | None] = mapped_column(String(14), nullable=True, unique=True, index=True)
    faculty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("faculties.id", ondelete="SET NULL"), nullable=True, index=True
    )
    group_or_position: Mapped[str] = mapped_column(String, nullable=False)
    # Xodim: tuzilmadagi bo'linmasi (app/models/org.py OrgUnit) va lavozimi
    # (HEMIS staffPosition: "Assistent", "Farrosh", ...). Talabada bo'sh.
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    position: Mapped[str | None] = mapped_column(String, nullable=True)
    biometrics_status: Mapped[str] = mapped_column(String, nullable=False, default="yoq")
    # S3/MinIO object key (not a URL — presigned URLs expire, so the key is
    # the stable handle and app/routers/students_staff.py generates a fresh
    # presigned URL on every read). embedding is the raw 512-d ArcFace
    # vector from app/services/face_recognition.py, JSON-encoded — no
    # pgvector extension is set up, so this is stored for future use
    # (e.g. a real "search by face" feature) rather than queried today.
    biometric_photo_key: Mapped[str | None] = mapped_column(String, nullable=True)
    biometric_embedding: Mapped[str | None] = mapped_column(String, nullable=True)
    # Ro'yxatdan o'tishdagi uch tomonlama rasm: biometric_photo_key — to'g'ri,
    # bular — chapga va o'ngga burilgan (app/routers/enrollment.py).
    biometric_photo_left_key: Mapped[str | None] = mapped_column(String, nullable=True)
    biometric_photo_right_key: Mapped[str | None] = mapped_column(String, nullable=True)
    # Yuz tasdiqlangan aniq payt. Ochiq ro'yxatdan o'tish sahifasi ham,
    # admin paneli ham tasdiqlaganda yozadi. Bu ustun paydo bo'lishidan
    # oldin tasdiqlaganlarda NULL — ular uchun vaqt yuz rasmining
    # saqlangan paytidan tiklanadi (students_staff.biometrics_confirmation).
    biometrics_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Ochiq sahifada o'zini o'zi ro'yxatdan o'tkazgan (institut ro'yxatida
    # bo'lmagan) odam. Uning yuzi administrator tasdiqlagunicha
    # "kutilmoqda" bo'lib turadi va tanish ro'yxatiga kirmaydi.
    self_registered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- Platforma kengaytmasi (2026-09-19, alembic s1a2b3c4d5e6) ---
    # Ota-ona xabarnomasi (app/services/notifications): SMS raqami va/yoki
    # Telegram bot orqali bog'langan chat. telegram_link_code — ota-ona botga
    # "/start <kod>" yuborib o'zini bog'laydigan kod.
    parent_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    parent_telegram_chat_id: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_notify_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    telegram_link_code: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    telegram_link_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Turniket/kirish kartasi raqami (app/services/integrations/access_control.py).
    card_number: Mapped[str | None] = mapped_column(String, nullable=True, unique=True, index=True)
    # HEMIS tizimidagi identifikator (talaba: student_id_number, xodim: employee_id_number).
    hemis_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True, index=True)
    # HEMIS rasmi (image_full) — yuzi yo'q odamni shu rasmdan tanitish
    # (app/jobs/hemis_photos.py). checked_at/error — urinish natijasi.
    hemis_photo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Yuz nega administrator tekshiruviga qoldi (self_enrollment.decide_status).
    biometrics_review_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    hemis_photo_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hemis_photo_error: Mapped[str | None] = mapped_column(String, nullable=True)
    # Faol emas (bitirgan, ishdan ketgan): tanish ro'yxatiga kirmaydi,
    # biometrikasi saqlash muddatidan keyin o'chiriladi (app/jobs/cleanup.py).
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Administrator qo'lda faolsizlantirgan — HEMIS sinxroni uni qayta
    # faollashtirmaydi (HEMIS ro'yxatida hali "faol" bo'lsa ham).
    manually_deactivated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Rozilik qaytarib olingan / biometrika o'chirilgan: HEMIS suratidan
    # yuz AVTOMATIK qayta kiritilmaydi (app/jobs/hemis_photos.py).
    biometrics_opt_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Biometrik ma'lumotni qayta ishlashga rozilik (O'zR "Shaxsga doir
    # ma'lumotlar to'g'risida"gi qonun). consent_source: 'royxatdan_otish',
    # 'admin', 'hemis', 'qogoz'.
    consent_given_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_version: Mapped[str | None] = mapped_column(String, nullable=True)
    consent_source: Mapped[str | None] = mapped_column(String, nullable=True)

    faculty: Mapped[Faculty | None] = relationship("Faculty", lazy="joined")

    @property
    def awaiting_approval(self) -> bool:
        """Yuzi yuborilgan, lekin administrator hali ko'rib chiqmagan: o'zini
        o'zi qo'shgan odam YOKI yuzi boshqa odamga o'xshab qolgan har kim
        (self_enrollment.decide_status)."""
        return self.biometrics_status == "kutilmoqda" and self.biometric_embedding is not None

    @property
    def has_all_angles(self) -> bool:
        """Yuz uch burchakdan (old, chap, o'ng) olingan. Faqat shunda yuz
        "tasdiqlangan" bo'la oladi — bir burchakli yuz ishonchsiz tanitadi."""
        return bool(self.biometric_photo_key and self.biometric_photo_left_key and self.biometric_photo_right_key)
