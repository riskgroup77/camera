from typing import Literal

from app.schemas.base import CamelModel


class AIModuleOut(CamelModel):
    """Matches src/types/index.ts `AIModule` exactly."""

    id: str
    code: int
    group: Literal["A", "B", "C", "D", "E", "F"]
    name: str
    description: str
    method: str
    accuracy: float
    threshold: int
    sensitivity: Literal["past", "o'rta", "yuqori"]
    camera_count: int
    active: bool


class AIModuleUpdateIn(CamelModel):
    """Registry-level config an admin can change — NOT model retraining.
    Toggling `active` without a real inference worker behind this module
    is a no-op for actual detections; it only changes what the frontend
    shows as enabled. See the router docstring for the honest caveat."""

    threshold: int
    sensitivity: Literal["past", "o'rta", "yuqori"]
    active: bool
