from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel


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
    zone: str
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
    # See app/models/camera.py's Camera.is_perimeter docstring —
    # app/jobs/vehicle_ai.py only runs on cameras flagged this way.
    is_perimeter: bool = False
    # See app/models/camera.py's Camera.is_exit docstring — only a sighting
    # on a camera flagged this way ever advances AttendanceRecord.check_out.
    is_exit: bool = False
    # Set only by app/services/camera_import.py — null for hand-added cameras.
    mac_address: str | None = None


class CameraCreateIn(CamelModel):
    name: str = Field(min_length=2)
    ip: str
    port: int = 554
    rtsp_path: str | None = None
    rtsp_username: str | None = None
    rtsp_password: str | None = None
    building: str  # building NAME, resolved server-side like StudentStaff.faculty
    zone: str = Field(min_length=1)
    resolution: str = Field(min_length=2)
    fps: int | None = None
    status: Literal["faol", "nofaol", "tamirda"] = "nofaol"
    is_entrance: bool = False
    is_perimeter: bool = False
    is_exit: bool = False


class CameraUpdateIn(CameraCreateIn):
    pass


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


class ModuleCameraAssignmentsOut(CamelModel):
    module_code: int
    module_name: str
    cameras: list[ModuleCameraAssignmentOut]


class ModuleCameraAssignmentUpdateIn(CamelModel):
    camera_id: str
    enabled: bool


class ModuleCameraAssignmentsPatchIn(CamelModel):
    assignments: list[ModuleCameraAssignmentUpdateIn]
