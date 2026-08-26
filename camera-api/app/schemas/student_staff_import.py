import csv
import io
from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel


class StudentStaffImportRowIn(CamelModel):
    full_name: str = Field(min_length=5)
    type: Literal["talaba", "xodim"]
    faculty: str
    group_or_position: str = Field(min_length=1)


class StudentStaffImportErrorOut(CamelModel):
    row: int
    message: str


class StudentStaffImportResultOut(CamelModel):
    imported: int
    skipped: int
    errors: list[StudentStaffImportErrorOut]
