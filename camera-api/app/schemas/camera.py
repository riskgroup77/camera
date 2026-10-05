from typing import Literal

from pydantic import Field, model_validator

from app.schemas.base import CamelModel
from app.schemas.ptz import PtzProtocol

# app/services/camera_roles.py ROOM_TYPES bilan bir xil (model CheckConstraint ham).
RoomType = Literal["kirish", "auditoriya", "laboratoriya", "koridor", "ofis", "cheklangan", "tashqi"]
FaceDirection = Literal["kirish", "chiqish"]


class CameraOut(CamelModel):
    """Matches src/types/index.ts `CameraConfig` (plus streamUrl already
    added to the frontend type for the LiveVideoPlayer integration).

    port/rtsp_path are included so the edit form can pre-fill them accurately
    — without this, re-saving a camera after editing an unrelated field (e.g.
    zone) would silently reset port back to the form's default and clear
    rtsp_path, since CameraUpdateIn overwrites both unconditionally.
    rtsp_username/rtsp_password stay write-only (never echoed back) since
    those are real secrets, not merely non-default config."""

    id: str
    name: str
    ip: str
    port: int
    rtsp_path: str | None = None
    building: str  # full Building.name
    department: str = ""  # Department.name; biriktirilmagan bo'lsa bo'sh
    zone: str
    # Qavat raqami — Video Monitoring Markazi kesimi shu bo'yicha quriladi
    # (app/models/camera.py Camera.floor). None = belgilanmagan.
    floor: int | None = None
    resolution: str
    fps: int | None
    status: Literal["faol", "nofaol", "tamirda"]
    stream_url: str | None = None
    # Observed, not configured — see Camera.last_seen_at's docstring.
    # `status='faol'` is the admin's intent; this is whether
    # app/jobs/camera_health.py's periodic TCP sweep actually reached it
    # recently. The two can disagree (e.g. status='faol' but a cable is
    # unplugged), and that disagreement is the whole point of this field.
    is_reachable: bool = False
    # List of [x, y] pairs, each normalized 0-1 against frame width/height —
    # see app/models/camera.py's Camera.restricted_zone_polygon docstring.
    # None/empty means app/jobs/zone_entry_ai.py skips this camera entirely.
    restricted_zone_polygon: list[list[float]] | None = None
    # AIModuleConfig.code integers this camera is EXCLUDED from — see
    # app/models/camera.py's Camera.excluded_module_codes docstring. Empty/
    # None means every active module still runs on this camera (today's
    # behavior, unchanged).
    excluded_module_codes: list[int] | None = None
    # See app/models/camera.py's Camera.is_entrance docstring —
    # app/jobs/attendance_ai.py grabs a multi-frame burst from this
    # camera instead of a single frame.
    is_entrance: bool = False
    # See app/models/camera.py's Camera.is_perimeter docstring — hovli/
    # tashqi hudud belgisi (endi hech qanday sweepni cheklamaydi).
    is_perimeter: bool = False
    # See app/models/camera.py's Camera.is_exit docstring — only a sighting
    # on a camera flagged this way ever advances AttendanceRecord.check_out.
    is_exit: bool = False
    # Set only by app/services/camera_import.py — null for hand-added cameras.
    mac_address: str | None = None
    # Xona turi (admin belgilagan) va AMALDAGI turi (belgilanmagan bo'lsa
    # kirish/perimetr bayrog'idan) — app/services/camera_roles.py.
    room_type: RoomType | None = None
    effective_room_type: RoomType | None = None
    # Dars jadvalidagi xona raqami (normallashtirilgan).
    room_code: str | None = None
    # Kirish kamerasining eshik hududi (yuz faqat shu yerda qidiriladi) va
    # kamera kirayotganlarning yoki chiqayotganlarning yuzini ko'rishi.
    face_roi: list[list[float]] | None = None
    face_direction: FaceDirection | None = None
    # PTZ boshqaruvi (app/services/ptz.py). onvif_port — kameraning HTTP
    # porti (ONVIF va ISAPI uchun ham); None = 80.
    ptz_enabled: bool = False
    ptz_protocol: PtzProtocol | None = None
    onvif_port: int | None = None


class CameraCreateIn(CamelModel):
    name: str = Field(min_length=2)
    ip: str
    port: int = 554
    rtsp_path: str | None = None
    rtsp_username: str | None = None
    rtsp_password: str | None = None
    building: str  # building NAME, resolved server-side like StudentStaff.faculty
    department: str | None = None
    """Kafedra NOMI — bino kabi serverda yechiladi.

    Bo'sh qoldirilsa kamera kafedrasiz qoladi va faqat bino bo'yicha
    filtrlanadi. Mavjud 107 kameraning barchasi shu holatda."""
    zone: str = Field(min_length=1)
    floor: int | None = Field(default=None, ge=-5, le=50)
    """Qavat raqami; bo'sh qoldirilsa kamera "Qavat belgilanmagan" guruhida qoladi."""
    resolution: str = Field(min_length=2)
    fps: int | None = None
    status: Literal["faol", "nofaol", "tamirda"] = "nofaol"
    is_entrance: bool = False
    is_perimeter: bool = False
    is_exit: bool = False
    room_type: RoomType | None = None
    room_code: str | None = Field(default=None, max_length=32)
    ptz_enabled: bool = False
    ptz_protocol: PtzProtocol | None = None
    onvif_port: int | None = Field(default=None, ge=1, le=65535)
    """Kameraning HTTP (ONVIF/ISAPI) porti; bo'sh — 80."""

    @model_validator(mode="after")
    def _ptz_needs_protocol(self):
        if self.ptz_enabled and self.ptz_protocol is None:
            raise ValueError("PTZ yoqilgan bo'lsa, protokolni tanlang (ONVIF yoki Hikvision ISAPI)")
        return self


class CameraUpdateIn(CameraCreateIn):
    """PTZ maydonlari (ptzEnabled, ptzProtocol, onvifPort) qavat kabi faqat
    YUBORILGANDA o'zgaradi — ularni bilmaydigan eski mijoz PTZ sozlamasini
    jimgina o'chirib yubormasin. "Yoqilgan, lekin protokolsiz" holati
    router'da, bazadagi qiymat bilan birga tekshiriladi."""

    @model_validator(mode="after")
    def _ptz_needs_protocol(self):
        if "ptz_enabled" in self.model_fields_set and "ptz_protocol" in self.model_fields_set:
            if self.ptz_enabled and self.ptz_protocol is None:
                raise ValueError("PTZ yoqilgan bo'lsa, protokolni tanlang (ONVIF yoki Hikvision ISAPI)")
        return self


class CameraSummaryOut(CamelModel):
    """Kameralar sahifasining yuqori ko'rsatkichlari — BITTA so'rovda.

    Ilgari sahifa har ro'yxat yangilanganda holat bo'yicha uchta
    qo'shimcha so'rov yuborardi (`?status=...&pageSize=1`), ya'ni filtr
    bosilgan sayin to'rtta so'rov ketardi."""

    total: int = 0
    faol: int = 0
    nofaol: int = 0
    tamirda: int = 0
    reachable: int = 0
    """Oxirgi tekshiruvda javob bergan faol kameralar."""
    without_floor: int = 0
    """Qavati belgilanmagan kameralar — monitoring kesimi uchun muhim."""


class CameraLocationIn(CamelModel):
    """Bitta kameraning joylashuvi — PATCH /api/cameras/{id}/location.

    Ulanishga taalluqli maydonlar (ip, port, rtsp, login/parol) bu yerda
    ATAYLAB yo'q: ular umuman yuborilmaydi, demak tasodifan buzilmaydi
    ham. Yuborilmagan maydon o'zgarmaydi."""

    name: str | None = Field(default=None, min_length=2)
    building: str | None = None
    floor: int | None = Field(default=None, ge=-5, le=50)
    clear_floor: bool = False
    zone: str | None = Field(default=None, min_length=1)
    department: str | None = None
    """Kafedra NOMI. Olib tashlash uchun — `clear_department`."""
    clear_department: bool = False
    room_type: RoomType | None = None
    """Xona turi. Olib tashlash uchun — `clear_room_type`."""
    clear_room_type: bool = False
    room_code: str | None = Field(default=None, max_length=32)
    """Dars jadvalidagi xona raqami. Olib tashlash uchun — `clear_room_code`."""
    clear_room_code: bool = False
    face_direction: FaceDirection | None = None
    """Kirish kamerasi kimning yuzini ko'radi. Olib tashlash — `clear_face_direction`."""
    clear_face_direction: bool = False


class CameraBulkLocationIn(CamelModel):
    """Bir nechta kameraga joylashuvni birdan belgilash.

    107 ta kameraga qavatni bittalab qo'yish real ish emas, shuning uchun
    admin sahifasida kameralar belgilanadi va shu endpoint bilan
    guruhlab yangilanadi. None qoldirilgan maydon O'ZGARTIRILMAYDI —
    faqat qavatni qo'yish uchun binoni qayta yuborish shart emas."""

    camera_ids: list[str] = Field(min_length=1, max_length=500)
    building: str | None = None
    floor: int | None = Field(default=None, ge=-5, le=50)
    clear_floor: bool = False
    """True — qavat belgisi olib tashlanadi (floor=None 'tegmaslik' degani)."""
    zone: str | None = None
    room_type: RoomType | None = None
    """Bir xil turdagi kameralarni (masalan barcha auditoriyalar) birdan belgilash."""
    clear_room_type: bool = False


class CameraBulkLocationOut(CamelModel):
    updated: int
    not_found: list[str] = []


class CameraZoneOut(CamelModel):
    """A room routinely holds more than one camera (different angles) —
    this backs the zone-name autocomplete in AddCameraModal.tsx and the
    zone filter chips in CamerasZonesPage.tsx, both keyed on `zone`
    exactly (a free-text field on Camera, not its own table)."""

    zone: str
    camera_count: int


class CameraZonePolygonIn(CamelModel):
    """PUT body for app/routers/cameras.py's zone-polygon endpoint.
    An empty/None polygon clears the restriction (camera stops being
    swept by app/jobs/zone_entry_ai.py)."""

    polygon: list[list[float]] | None = None


class CameraModulesIn(CamelModel):
    """PATCH body for app/routers/cameras.py's modules endpoint — a full
    replacement of the exclusion list (matches CameraZonePolygonIn's
    replace-not-merge convention), not an add/remove delta."""

    excluded_module_codes: list[int] | None = None


class ConnectionTestIn(CamelModel):
    ip: str
    port: int = 554
    rtsp_path: str | None = None
    rtsp_username: str | None = None
    rtsp_password: str | None = None


class ConnectionTestOut(CamelModel):
    success: bool
    message: str
    method: Literal["tcp-only", "rtsp-probe"]
    latency_ms: int | None = None
    video_info: str | None = None


class CameraModuleOptionOut(CamelModel):
    """Lightweight module row for CameraModulesModal — readable under
    manageCameras without configureAi (full /api/ai-modules registry)."""

    code: int
    group: Literal["A", "B", "C", "D", "E", "F"]
    name: str
    active: bool
    has_detector: bool


class ModuleCameraAssignmentOut(CamelModel):
    camera_id: str
    camera_name: str
    building: str
    zone: str
    status: Literal["faol", "nofaol", "tamirda"]
    enabled: bool
    # Kameraning xona turi bu modulga mos keladimi (app/services/camera_roles.py).
    # enabled=True, role_allowed=False — admin ruxsat bergan, lekin modul
    # baribir ishlamaydi: avval xona turini to'g'rilash kerak.
    role_allowed: bool = True
    effective_room_type: RoomType | None = None


class ModuleCameraAssignmentsOut(CamelModel):
    module_code: int
    module_name: str
    cameras: list[ModuleCameraAssignmentOut]


class ModuleCameraAssignmentUpdateIn(CamelModel):
    camera_id: str
    enabled: bool


class ModuleCameraAssignmentsPatchIn(CamelModel):
    assignments: list[ModuleCameraAssignmentUpdateIn]


class CameraRoleChangeOut(CamelModel):
    camera_id: str
    camera_name: str
    field: Literal["room_type", "room_code", "face_direction"]
    old: str | None = None
    new: str | None = None


class CameraRoleImportErrorOut(CamelModel):
    row: int
    message: str


class CameraRolesImportOut(CamelModel):
    """POST /api/cameras/roles/import — `applied=False` bo'lsa bu faqat
    oldindan ko'rish: hech narsa yozilmagan."""

    rows: int
    changes: list[CameraRoleChangeOut]
    errors: list[CameraRoleImportErrorOut]
    applied: bool
