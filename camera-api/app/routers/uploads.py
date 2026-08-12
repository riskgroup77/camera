from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.dependencies import CurrentUser, get_current_user
from app.schemas.upload import UploadedFileOut
from app.storage import presigned_url, upload_file

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

MAX_SIZE_BYTES = 10 * 1024 * 1024  # matches PassportUploadStep.tsx's MAX_SIZE_MB = 10
ALLOWED_CONTENT_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp"}


@router.post("", response_model=UploadedFileOut, status_code=status.HTTP_201_CREATED)
async def create_upload(
    _: Annotated[CurrentUser, Depends(get_current_user)],
    file: Annotated[UploadFile, File()],
    prefix: Annotated[str, Query()] = "misc",
) -> UploadedFileOut:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Qo'llab-quvvatlanmaydigan fayl turi: {file.content_type}",
        )

    data = await file.read()
    if len(data) > MAX_SIZE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Fayl hajmi 10 MB dan oshmasligi kerak")

    file_id, key = upload_file(data, file.filename or "file", file.content_type, prefix)
    return UploadedFileOut(id=file_id, url=presigned_url(key), name=file.filename or "file")
