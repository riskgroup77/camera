"""HEMIS integratsiyasi va turniket/kirish nazorati sxemalari
(src/lib/integrationsApi.ts bilan maydonma-maydon mos)."""

from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel

DeviceKind = Literal["hikvision", "zkteco", "webhook"]
DeviceDirection = Literal["kirish", "chiqish", "ikkalasi"]
DeviceStatus = Literal["onlayn", "oflayn", "xato", "kutilmoqda", "ochirilgan"]


# ── HEMIS ──


class SyncRunOut(CamelModel):
    id: str
    source: str
    status: Literal["ishlamoqda", "muvaffaqiyatli", "xato"]
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: int | None = None
    triggered_by: str
    stats: dict | None = None
    error: str | None = None


class HemisStatusOut(CamelModel):
    configured: bool
    # Faqat manzil — token hech qachon qaytarilmaydi.
    base_url: str | None = None
    sync_interval_hours: int
    deactivate_missing: bool
    page_size: int
    running: SyncRunOut | None = None
    last_run: SyncRunOut | None = None
    last_success_at: str | None = None


class HemisEntityTestOut(CamelModel):
    ok: bool
    total: int | None = None
    error: str | None = None


class HemisTestOut(CamelModel):
    ok: bool
    error: str | None = None
    entities: dict[str, HemisEntityTestOut] = Field(default_factory=dict)


class SyncStartedOut(CamelModel):
    run_id: str


# ── Turniketlar ──


class AccessDeviceOut(CamelModel):
    id: str
    name: str
    kind: DeviceKind
    ip: str | None = None
    port: int | None = None
    username: str | None = None
    has_password: bool
    has_api_key: bool
    direction: DeviceDirection
    building_id: str | None = None
    building_name: str | None = None
    marks_attendance: bool
    enabled: bool
    status: DeviceStatus
    last_event_at: str | None = None
    last_poll_at: str | None = None
    last_error: str | None = None
    webhook_path: str | None = None
    created_at: str | None = None


class AccessDeviceCreatedOut(AccessDeviceOut):
    # Faqat yaratishda / kalit almashtirilganda BIR MARTA ko'rsatiladi.
    api_key: str | None = None


class AccessDeviceCreateIn(CamelModel):
    name: str = Field(min_length=1, max_length=100)
    kind: DeviceKind
    ip: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=100)
    password: str | None = Field(default=None, max_length=200)
    direction: DeviceDirection = "kirish"
    building_id: str | None = None
    marks_attendance: bool = True
    enabled: bool = True


class AccessDeviceUpdateIn(CamelModel):
    """Ko'rsatilmagan maydon o'zgarmaydi. password: bo'sh qator — o'chiriladi."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    ip: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=100)
    password: str | None = Field(default=None, max_length=200)
    direction: DeviceDirection | None = None
    building_id: str | None = None
    marks_attendance: bool | None = None
    enabled: bool | None = None


class ApiKeyOut(CamelModel):
    api_key: str
    webhook_path: str


class DeviceTestOut(CamelModel):
    ok: bool
    message: str
    info: dict[str, str | None] | None = None


class AccessEventOut(CamelModel):
    id: str
    device_id: str | None = None
    device_name: str | None = None
    occurred_at: str
    card_number: str | None = None
    employee_no: str | None = None
    person_id: str | None = None
    person_name: str | None = None
    person_type: str | None = None
    person_unit: str | None = None
    direction: str | None = None
    granted: bool


class AccessSummaryOut(CamelModel):
    date: str
    total: int
    entries: int
    exits: int
    denied: int
    unmatched: int
    # Turniketdan o'tgan tanilgan (biriktirilgan) odamlar soni.
    people: int


class UnmatchedCredentialOut(CamelModel):
    card_number: str | None = None
    employee_no: str | None = None
    count: int
    denied_count: int
    first_seen: str
    last_seen: str
    last_device_name: str | None = None


class WebhookResultOut(CamelModel):
    accepted: int
    duplicates: int
    matched: int
    attendance: int
    rejected: list[dict] = Field(default_factory=list)
