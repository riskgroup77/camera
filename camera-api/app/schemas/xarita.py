"""Xarita (app/routers/xarita.py) sxemalari."""

from typing import Literal

from pydantic import Field, model_validator

from app.schemas.base import CamelModel

CameraMapStatus = Literal["online", "novideo", "offline"]


class XaritaFloorOut(CamelModel):
    floor: int
    has_plan: bool
    camera_count: int
    placed_count: int


class XaritaBuildingOut(CamelModel):
    id: str
    name: str
    floors: list[XaritaFloorOut]


class XaritaPlanOut(CamelModel):
    image_url: str | None
    """Imzolangan havola — ombor javob bermasa None."""
    width: int
    height: int
    updated_at: str


class XaritaCameraOut(CamelModel):
    id: str
    name: str
    zone: str
    status: CameraMapStatus
    """Devor bilan bir xil: online — tasvir kelyapti, novideo — tarmoqda,
    lekin kadr yo'q, offline — javob bermayapti yoki o'chirilgan."""
    x: float | None
    y: float | None
    angle: int | None
    fov: int
    open_events: int
    """Oxirgi 24 soatdagi ochiq (yangi/jarayonda, sinov emas) signallar."""
    stream_url: str | None = None
    people_now: int = 0
    """So'nggi 10 daqiqada shu kamerada tanilgan turli odamlar soni."""
    assigned: bool = True
    """False — kamera hali biror qavatga biriktirilmagan (faqat tahrir
    huquqi borlarga, `candidates` ro'yxatida)."""


class XaritaFloorViewOut(CamelModel):
    building_id: str
    building_name: str
    floor: int
    plan: XaritaPlanOut | None
    cameras: list[XaritaCameraOut]
    candidates: list[XaritaCameraOut] = []


class XaritaPlacementIn(CamelModel):
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    angle: int | None = Field(default=None, ge=0, le=359)
    fov: int | None = Field(default=None, ge=10, le=360)
    building_id: str | None = None
    """Berilsa (floor bilan) — biriktirilmagan kamera shu qavatga qo'yiladi."""
    floor: int | None = None

    @model_validator(mode="after")
    def _both_or_none(self) -> "XaritaPlacementIn":
        if (self.x is None) != (self.y is None):
            raise ValueError("x va y birga beriladi yoki ikkalasi ham bo'sh bo'ladi")
        if (self.building_id is None) != (self.floor is None):
            raise ValueError("buildingId va floor birga beriladi")
        return self
