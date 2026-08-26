from app.schemas.base import CamelModel


class ResourceAlertOut(CamelModel):
    metric: str
    level: str  # "warning" | "critical"
    message: str


class SystemResourcesOut(CamelModel):
    cpu: int
    ram: int
    disk: int
    ffmpeg_process_count: int
    stream_reader_count: int
    alerts: list[ResourceAlertOut]
