from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel


class EnrollmentLookupIn(CamelModel):
    """Uzbek passport format: 2-letter series + 7-digit number — see
    StudentStaff.passport_series/passport_number."""

    passport_series: str = Field(min_length=2, max_length=4)
    passport_number: str = Field(min_length=5, max_length=10)


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
    passport_series: str = Field(min_length=2, max_length=4)
    passport_number: str = Field(min_length=5, max_length=10)


class EnrollmentFacultyOut(CamelModel):
    id: str
    name: str
