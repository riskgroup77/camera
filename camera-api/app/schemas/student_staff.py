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


class StudentStaffCreateIn(CamelModel):
    """Matches AddStudentStaffModal.tsx step-1 fields plus the biometric
    enrollment outcome computed by the frontend's face-match step."""

    full_name: str = Field(min_length=5)
    type: Literal["talaba", "xodim"]
    faculty: str
    group_or_position: str = Field(min_length=1)
    biometrics_status: Literal["tasdiqlangan", "kutilmoqda", "yoq"] = "yoq"


class StudentStaffUpdateIn(CamelModel):
    """Matches EditStudentStaffModal.tsx fields."""

    full_name: str = Field(min_length=5)
    type: Literal["talaba", "xodim"]
    faculty: str
    group_or_position: str = Field(min_length=1)
