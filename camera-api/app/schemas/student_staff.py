from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel


class StudentStaffOut(CamelModel):
    """Matches src/types/index.ts `StudentStaffRecord` exactly."""

    id: str
    full_name: str
    type: Literal["talaba", "xodim"]
    faculty: str  # faculty NAME (not id) — matches the frontend's plain-string field
    group_or_position: str
    biometrics_status: Literal["tasdiqlangan", "kutilmoqda", "yoq"]
    initials: str
    biometric_photo_url: str | None = None
    # Faqat talabada: group_or_position "2-kurs, DI-1625" dan ajratilgan
    course: int | None = None
    group: str | None = None
    # "14.09.2026 13:57" — yuz tasdiqlangan payt, Toshkent vaqti
    confirmed_label: str | None = None
    # Ochiq sahifada o'zini o'zi ro'yxatdan o'tkazgan; awaiting_approval —
    # yuzi yuborilgan va administrator qarorini kutmoqda.
    self_registered: bool = False
    awaiting_approval: bool = False
    # Xodim: HEMIS bo'linmasi nomi va lavozimi.
    org_unit: str | None = None
    position: str | None = None
    # Ro'yxatdan o'tishda saqlangan tomonlar soni (old, chap, o'ng): 0..3.
    photo_angles: int = 0
    biometric_photo_left_url: str | None = None
    biometric_photo_right_url: str | None = None
    # Tekshiruvga nega qoldi va HEMIS surati (solishtirish uchun) — faqat kutayotganlarda.
    review_reason: str | None = None
    hemis_photo_url: str | None = None


class StudentStaffCreateIn(CamelModel):
    """Matches AddStudentStaffModal.tsx step-1 fields plus the biometric
    enrollment outcome computed by the frontend's face-match step."""

    full_name: str = Field(min_length=5)
    type: Literal["talaba", "xodim"]
    faculty: str
    group_or_position: str = Field(min_length=1)
    biometrics_status: Literal["tasdiqlangan", "kutilmoqda", "yoq"] = "yoq"
    # Bazada o'xshash ismli odam bo'lsa ham yaratish — admin "bu boshqa odam"
    # deb aniq tasdiqlaganda. Aks holda 409 (students_staff.create).
    allow_duplicate: bool = False
    # Ota-ona xabarnomasi (faqat talaba) va turniket kartasi — ixtiyoriy.
    parent_phone: str | None = Field(default=None, max_length=32)
    parent_notify_enabled: bool = False
    card_number: str | None = Field(default=None, max_length=64)


class StudentStaffUpdateIn(CamelModel):
    """Matches EditStudentStaffModal.tsx fields.

    Talabada kurs va guruh ALOHIDA keladi (course, group) va server ularni
    "2-kurs, DI-1625" shakliga o'zi yig'adi — import ham shu shaklni yozadi
    (staff_export.split_course). Xodimda group_or_position = lavozim.

    pinfl / passport_series / passport_number: maydon umuman yuborilmasa —
    o'zgarmaydi; bo'sh satr — o'chiriladi."""

    full_name: str = Field(min_length=5)
    type: Literal["talaba", "xodim"]
    faculty: str
    group_or_position: str = ""
    course: int | None = Field(default=None, ge=1, le=10)
    group: str | None = None
    pinfl: str | None = None
    passport_series: str | None = None
    passport_number: str | None = None
    # Xuddi shu qoida: yuborilmasa — o'zgarmaydi; bo'sh satr — o'chiriladi.
    parent_phone: str | None = Field(default=None, max_length=32)
    parent_notify_enabled: bool | None = None
    card_number: str | None = Field(default=None, max_length=64)


class StudentStaffDetailOut(StudentStaffOut):
    """Tahrirlash oynasi uchun: ro'yxatda ko'rsatilmaydigan shaxsiy
    identifikatorlar. Faqat bitta yozuv so'ralganda qaytariladi."""

    pinfl: str | None = None
    passport_series: str | None = None
    passport_number: str | None = None
    # Ota-ona xabarnomasi va turniket kartasi. parent_telegram_linked —
    # faqat o'qiladi: ota-ona botga "/start <kod>" yuborganda bog'lanadi
    # (POST /api/students-staff/{id}/parent-telegram-link).
    parent_phone: str | None = None
    parent_notify_enabled: bool = False
    parent_telegram_linked: bool = False
    card_number: str | None = None


class StudentStaffFilterIn(CamelModel):
    """Qidiruv/eksport filtri SO'ROV TANASIDA — URL'da emas.

    Qidiruv matni ko'pincha JSHSHIR bo'ladi. GET so'rovning query qatori
    nginx access logida, brauzer tarixida va proksi jurnallarida saqlanib
    qoladi; POST tanasi esa hech qayerga yozilmaydi."""

    type: Literal["talaba", "xodim"] | None = None
    faculty: str | None = None
    search: str | None = Field(default=None, max_length=200)
    biometrics_status: str | None = None
    course: int | None = Field(default=None, ge=1, le=10)


class StudentStaffSearchIn(StudentStaffFilterIn):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=500)
    # name — F.I.Sh. bo'yicha; confirmed — oxirgi yuz tasdiqlaganlar birinchi;
    # faculty — fakultet, keyin F.I.Sh.
    sort: Literal["name", "confirmed", "faculty"] = "name"


class StudentStaffExportIn(StudentStaffFilterIn):
    kind: Literal["people", "stats"] = "people"


class BiometricsFacultyRowOut(CamelModel):
    """Bitta fakultet (yoki fakultetsizlar guruhi) bo'yicha qamrov."""

    faculty: str
    total: int
    confirmed: int
    pending: int
    missing: int
    percent: float | None = None
    """Qamrov foizi. None — guruhda umuman odam yo'q.

    Nol bilan aralashtirmaslik uchun ataylab: "0%" hech kim
    tasdiqlamagani, "ma'lumot yo'q" esa hisoblash uchun hech narsa
    yo'qligi. Ikkalasi turli xulosaga olib keladi."""


class BiometricsCourseRowOut(CamelModel):
    """Talabalar — bitta kurs bo'yicha qamrov."""

    course: str  # "2-kurs" yoki "Kurs ko'rsatilmagan"
    course_number: int | None = None
    total: int
    confirmed: int
    pending: int
    missing: int
    percent: float | None = None


class BiometricsCoverageOut(CamelModel):
    """Yuzni tasdiqlash qamrovi — kim tasdiqladi, kim yo'q."""

    total: int
    confirmed: int
    pending: int
    missing: int
    percent: float | None = None
    by_faculty: list[BiometricsFacultyRowOut]
    by_course: list[BiometricsCourseRowOut] = []
    """Faqat type=talaba so'ralganda to'ldiriladi."""
    awaiting_approval: int = 0
    """O'zini o'zi ro'yxatdan o'tkazib, administrator qarorini kutayotganlar."""


class BiometricsConfirmationOut(StudentStaffOut):
    """"Aniqlash" oynasi: odam yuzini aniq qachon tasdiqlagani.

    Vaqt Toshkent vaqtida, tayyor matn ko'rinishida keladi — qarang
    app/timezone.py uz_datetime_parts."""

    confirmed_at: str | None = None
    confirmed_date: str | None = None
    confirmed_weekday: str | None = None
    confirmed_time: str | None = None
    source: Literal["tizim", "rasm", "nomalum", "tasdiqlanmagan"]
    """tizim — tasdiqlash paytida yozilgan; rasm — bu yozuv paydo
    bo'lishidan oldingi tasdiqlash, vaqt yuz rasmi saqlangan paytdan
    tiklangan; nomalum — tasdiqlangan, lekin vaqtni aniqlab bo'lmadi;
    tasdiqlanmagan — odam hali yuzini tasdiqlamagan."""


class PeopleOverviewOut(CamelModel):
    """"Talabalar va Xodimlar" sahifasining tepa qismi — ikkala tur qamrovi
    bitta so'rovda (ilgari ikki alohida /biometrics-coverage so'rovi)."""

    xodim: BiometricsCoverageOut
    talaba: BiometricsCoverageOut
