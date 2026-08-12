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


class BuildingCreateIn(CamelModel):
    name: str
    camera_count: int = 0
