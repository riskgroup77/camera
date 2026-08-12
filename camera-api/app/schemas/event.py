from typing import Literal

from app.schemas.base import CamelModel


class EventOut(CamelModel):
    """Matches src/types/index.ts `AIEvent` exactly."""

    id: str
    timestamp: str
    camera_id: str
    camera_name: str
    building: str
    module_code: int
    module_name: str
    group: Literal["A", "B", "C", "D", "E", "F"]
    confidence: int
    severity: Literal["past", "o'rta", "yuqori"]
    status: Literal["yangi", "tasdiqlangan", "rad_etilgan"]
    person_name: str | None = None
    reviewed_by: str | None = None


class EventCreateIn(CamelModel):
    """Submitted by an AI inference service when it detects something —
    not by a human admin through the UI."""

    camera_id: str
    module_code: int
    module_name: str
    group: Literal["A", "B", "C", "D", "E", "F"]
    confidence: int
    severity: Literal["past", "o'rta", "yuqori"]
    person_name: str | None = None


class EventReviewIn(CamelModel):
    status: Literal["tasdiqlangan", "rad_etilgan"]
