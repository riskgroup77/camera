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


class CameraUpdateIn(CameraCreateIn):
    pass


class CameraZoneOut(CamelModel):
    """A room routinely holds more than one camera (different angles) —
    this backs the zone-name autocomplete in AddCameraModal.tsx and the
    zone filter chips in CamerasZonesPage.tsx, both keyed on `zone`
    exactly (a free-text field on Camera, not its own table)."""

    zone: str
    camera_count: int


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
