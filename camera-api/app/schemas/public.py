from app.schemas.base import CamelModel


class PublicCameraOut(CamelModel):
    """Deliberately excludes ip/port/rtsp_path/credentials — this endpoint
    has no auth, so only what's safe to hand to an anonymous visitor of the
    public Monitoring page is exposed."""

    id: str
    name: str
    building: str
    zone: str
    status: str
    stream_url: str | None = None


class PublicStatsOut(CamelModel):
    total_students: int
    present: int
    absent: int
    late: int
    sleep_incidents: int
    violations: int
    live_cameras: int
    offline_cameras: int
    buildings: list[str]


class PublicTopStudentOut(CamelModel):
    id: str
    name: str
    group: str
    attendance_rate: int


class DetectedFaceOut(CamelModel):
    """One face found in a live-detection snapshot — see
    app/routers/public.py's get_live_detection() for how this differs from
    the persistent attendance/sleep pipeline."""

    bbox: list[float]  # [x1, y1, x2, y2], pixel coordinates in the source frame
    person_name: str | None = None
    asleep: bool = False


class LiveDetectionOut(CamelModel):
    frame_width: int
    frame_height: int
    faces: list[DetectedFaceOut]
