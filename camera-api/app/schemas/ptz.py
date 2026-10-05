from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel

PtzProtocol = Literal["onvif", "isapi"]


class PtzStatusOut(CamelModel):
    """GET /api/cameras/{id}/ptz — boshqaruv panelini ko'rsatish-ko'rsatmaslik
    uchun. Kameraga murojaat qilmaydi (faqat baza), shuning uchun arzon."""

    camera_id: str
    enabled: bool
    protocol: PtzProtocol | None = None
    onvif_port: int | None = None


class PtzMoveIn(CamelModel):
    """Uzluksiz harakat tezligi, har bir o'q -1..1 oralig'ida (0 — shu o'qda
    harakat yo'q). pan > 0 — o'ngga, tilt > 0 — yuqoriga, zoom > 0 —
    yaqinlashtirish."""

    pan: float = Field(default=0.0, ge=-1.0, le=1.0)
    tilt: float = Field(default=0.0, ge=-1.0, le=1.0)
    zoom: float = Field(default=0.0, ge=-1.0, le=1.0)
    duration_ms: int | None = Field(default=None, ge=100, le=10_000)
    """Berilsa — shu vaqtdan keyin server kamerani o'zi to'xtatadi.
    Boshqaruv paneli tugma bosib turilganda buni davriy yangilab turadi:
    brauzer "to'xtash"ni yubora olmay qolsa ham kamera aylanib qolmaydi."""


class PtzPresetOut(CamelModel):
    token: str
    name: str


class PtzPresetIn(CamelModel):
    name: str = Field(min_length=1, max_length=64)


class PtzProbeIn(CamelModel):
    """Saqlangan kamerani tekshirish — forma hali saqlanmagan qiymatlarini
    (protokol, port, yangi login/parol) sinab ko'rish uchun ixtiyoriy
    ustama qiymatlar. Bo'sh qoldirilganlari bazadan olinadi; protokol
    bo'sh bo'lsa avtomatik aniqlanadi."""

    protocol: PtzProtocol | None = None
    onvif_port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = None
    password: str | None = None


class PtzAdhocProbeIn(CamelModel):
    """Hali saqlanmagan kamera ("Yangi kamera qo'shish" formasi)."""

    ip: str = Field(min_length=1, max_length=255)
    protocol: PtzProtocol | None = None
    onvif_port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = None
    password: str | None = None


class PtzProbeOut(CamelModel):
    success: bool
    message: str
    protocol: PtzProtocol | None = None
    """Ishlagan (yoki oxirgi sinalgan) protokol — forma shuni tanlab qo'yadi."""
    reachable: bool = False
    authenticated: bool = False
    ptz_supported: bool = False
    presets_supported: bool = False
    preset_count: int | None = None
    device_info: str | None = None
    latency_ms: int | None = None
    tried: list[PtzProtocol] = []
