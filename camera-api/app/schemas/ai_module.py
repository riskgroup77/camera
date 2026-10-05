from typing import Annotated, Literal

from pydantic import Field

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
    # Operator ko'rib chiqqan signallar asosida (oxirgi 90 kun):
    # tasdiqlangan / (tasdiqlangan + rad etilgan). Namuna kichik bo'lsa None.
    measured_precision: float | None = None
    reviewed_events: int = 0
    recent_events: int = 0  # oxirgi 90 kundagi barcha signallar
    # asosiy — model asosidagi mezon; sinov — kalibrlanmagan evristika;
    # sozlash_kerak — operatorlar signallarning yarmidan ko'pini rad etgan.
    maturity: Literal["asosiy", "sinov", "sozlash_kerak"] = "sinov"
    maturity_note: str = ""
    # ishchi | sinov — qarang app/models/ai_module.py.
    mode: Literal["ishchi", "sinov"] = "ishchi"
    # Sinovdagi modulni ishchi rejimga o'tkazish sharti bajarilganmi.
    promotion_ready: bool = False
    # Baholanmagan sinov signallari (oxirgi 90 kun).
    trial_unreviewed: int = 0


class AIModuleUpdateIn(CamelModel):
    """Registry-level config an admin can change. `active` is enforced by
    every app/jobs/*.py sweep loop (see app/jobs/module_status.py) — for
    the handful of criteria with no detector written yet (has_detector on
    AIModuleConfig), the router rejects activation outright rather than
    silently accepting a toggle that would do nothing."""

    threshold: int
    sensitivity: Literal["past", "o'rta", "yuqori"]
    active: bool
    # Berilmasa rejim o'zgarmaydi. "ishchi" ga o'tish sharti routerda tekshiriladi.
    mode: Literal["ishchi", "sinov"] | None = None


class ModuleSuppressionOut(CamelModel):
    """Avtomatik o'chirilgan kamera × modul juftligi (app/jobs/module_suppression.py)."""

    id: str
    camera_id: str
    camera_name: str
    building: str
    module_code: int
    module_name: str
    confirmed: int
    rejected: int
    precision: float | None = None
    reason: str
    created_at: str  # "2026-09-16 10:05", institut vaqti


class ModuleSopOut(CamelModel):
    """Modul uchun operator ko'rsatmasi (app/services/sop.py)."""

    code: int
    name: str
    steps: list[str]
    # True — administrator o'zgartirgan; False — standart matn.
    custom: bool
    default_steps: list[str]


class ModuleSopIn(CamelModel):
    # null yoki bo'sh ro'yxat — standart ko'rsatmaga qaytarish.
    steps: list[Annotated[str, Field(max_length=200)]] | None = Field(default=None, max_length=10)
