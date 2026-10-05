from pydantic import Field

from app.schemas.base import CamelModel


class FacultyOut(CamelModel):
    id: str
    name: str
    course_count: int
    student_count: int


class FacultyCreateIn(CamelModel):
    name: str
    course_count: int = 0


class StudentGroupOut(CamelModel):
    id: str
    name: str
    faculty: str  # faculty NAME, matching src/types/index.ts StudentGroup.faculty
    course: int
    student_count: int


class StudentGroupCreateIn(CamelModel):
    name: str
    faculty_id: str
    course: int


class BuildingOut(CamelModel):
    id: str
    name: str
    camera_count: int
    floors: int | None = None
    """Qavatlar soni; monitoring kesimi kamerasiz qavatni ham shu bo'yicha chizadi."""
    sort_order: int = 0


class BuildingCreateIn(CamelModel):
    name: str = Field(min_length=1, max_length=200)
    camera_count: int = Field(default=0, ge=0)
    # Qavatlar soni monitoringdagi bino kesimini chizadi: 0, manfiy yoki
    # 900 qabul qilinsa o'sha kesim buzilardi (AddBuildingModal.tsx dagi
    # min/max atributlari faqat brauzer maslahati edi, so'rovni to'smasdi).
    floors: int | None = Field(default=None, ge=1, le=50)
    sort_order: int | None = None


class DepartmentOut(CamelModel):
    id: str
    name: str
    building_id: str | None
    building_name: str
    camera_count: int


class DepartmentCreateIn(CamelModel):
    name: str
    building_id: str | None = None
