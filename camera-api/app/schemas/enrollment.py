from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.base import CamelModel


def _clean_pinfl(value: str | None) -> str | None:
    """JSHSHIR dan raqamdan boshqa hamma narsani olib tashlaydi.

    Tozalash TEKSHIRUVDAN OLDIN bajarilishi kerak: odam raqamni
    ko'chirib qo'yganda bo'sh joy va chiziqcha qo'shilib qolishi juda
    tez-tez uchraydi, va uzunlik sharti ularni ham sanab, to'g'ri
    raqamni rad etardi."""
    if value is None:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits or None


class EnrollmentLookupIn(CamelModel):
    """Shaxsni ikki yo'ldan biri bilan aniqlash mumkin.

    JSHSHIR (14 raqam) — institut kadrlar ro'yxatidagi asosiy raqam.
    Ommaviy import qilingan xodimlarda aynan shu bor va pasport
    ma'lumotlari umuman yo'q, ya'ni ular uchun bu yagona yo'l.

    Pasport seriyasi va raqami — ilgari shu yo'l bilan ro'yxatdan
    o'tganlar uchun saqlanadi. Ikkalasidan biri yetarli; ikkalasi ham
    berilsa JSHSHIR ustun turadi, chunki u unikal va aniqroq.
    """

    pinfl: str | None = Field(default=None, max_length=32)
    passport_series: str | None = Field(default=None, min_length=2, max_length=4)
    passport_number: str | None = Field(default=None, min_length=5, max_length=10)

    @field_validator("pinfl", mode="before")
    @classmethod
    def _normalize_pinfl(cls, value):
        cleaned = _clean_pinfl(value if isinstance(value, str) else None)
        if cleaned is not None and not (13 <= len(cleaned) <= 14):
            raise ValueError("JSHSHIR 14 raqamdan iborat bo'lishi kerak")
        return cleaned

    @model_validator(mode="after")
    def _at_least_one(self) -> "EnrollmentLookupIn":
        if self.pinfl:
            return self
        if self.passport_series and self.passport_number:
            return self
        raise ValueError("JSHSHIR yoki pasport seriyasi va raqami kiritilishi kerak")


class EnrollmentLookupOut(CamelModel):
    record_id: str
    full_name: str
    type_label: str  # "Talaba" / "Xodim" — precomputed so the frontend doesn't need its own type->label map
    group_or_position: str
    already_enrolled: bool


class EnrollmentSubmitOut(CamelModel):
    full_name: str
    biometrics_status: str


class EnrollmentRegisterIn(CamelModel):
    """O'zini o'zi ro'yxatdan o'tkazish — tizimda yozuvi yo'q odam uchun.

    faculty_id ixtiyoriy: xodimning fakulteti bo'lmasligi mumkin, va
    ro'yxatdan o'tayotgan odam o'z fakultetini bilmasa ham jarayon
    to'xtab qolmasligi kerak (StudentStaff.faculty_id ham nullable).
    """

    full_name: str = Field(min_length=3, max_length=120)
    type: Literal["talaba", "xodim"]
    group_or_position: str = Field(min_length=1, max_length=120)
    faculty_id: str | None = None
    pinfl: str | None = Field(default=None, max_length=32)
    passport_series: str | None = Field(default=None, min_length=2, max_length=4)
    passport_number: str | None = Field(default=None, min_length=5, max_length=10)

    @field_validator("pinfl", mode="before")
    @classmethod
    def _normalize_pinfl(cls, value):
        cleaned = _clean_pinfl(value if isinstance(value, str) else None)
        if cleaned is not None and not (13 <= len(cleaned) <= 14):
            raise ValueError("JSHSHIR 14 raqamdan iborat bo'lishi kerak")
        return cleaned

    @model_validator(mode="after")
    def _at_least_one(self) -> "EnrollmentRegisterIn":
        if self.pinfl:
            return self
        if self.passport_series and self.passport_number:
            return self
        raise ValueError("JSHSHIR yoki pasport seriyasi va raqami kiritilishi kerak")


class EnrollmentFacultyOut(CamelModel):
    id: str
    name: str
