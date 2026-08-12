from app.schemas.base import CamelModel


class UploadedFileOut(CamelModel):
    """Matches the frontend's UploadedFile shape (camera/src/lib/fileUpload.ts)
    — id/url/name — so wiring the real endpoint in requires no reshaping."""

    id: str
    url: str
    name: str
