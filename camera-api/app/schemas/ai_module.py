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
    has_detector: bool


class AIModuleUpdateIn(CamelModel):
    """Registry-level config an admin can change. `active` is enforced by
    every app/jobs/*.py sweep loop (see app/jobs/module_status.py) — for
    the handful of criteria with no detector written yet (has_detector on
    AIModuleConfig), the router rejects activation outright rather than
    silently accepting a toggle that would do nothing."""

    threshold: int
    sensitivity: Literal["past", "o'rta", "yuqori"]
    active: bool
