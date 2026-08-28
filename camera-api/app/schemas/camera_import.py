from app.schemas.base import CamelModel


class CameraImportErrorOut(CamelModel):
    row: int
    message: str


class CameraImportResultOut(CamelModel):
    imported: int
    skipped: int
    skipped_recorders: int
    errors: list[CameraImportErrorOut]
