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
