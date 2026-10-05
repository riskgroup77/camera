from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.dependencies import CurrentUser, require_permission
from app.schemas.face import FaceCompareOut
from app.services.face_recognition import NoFaceDetectedError, compare_faces

router = APIRouter(prefix="/api/face", tags=["face"])

#: Har bir rasm uchun chegara — ro'yxatdan o'tish oqimidagi bilan bir xil
#: (app/routers/enrollment.py). Chegarasiz bu endpoint istalgan hajmdagi
#: faylni xotiraga o'qib, keyin uni InsightFace'ga berardi.
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024


@router.post("/compare", response_model=FaceCompareOut)
async def compare(
    _: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
    image_a: Annotated[UploadFile, File(description="Pasportdan olingan surat")],
    image_b: Annotated[UploadFile, File(description="Kamerada suratga olingan jonli yuz")],
) -> FaceCompareOut:
    data_a, data_b = await image_a.read(), await image_b.read()
    if len(data_a) > MAX_IMAGE_SIZE_BYTES or len(data_b) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Har bir rasm 10 MB dan oshmasligi kerak"
        )
    try:
        result = await compare_faces(data_a, data_b)
    except NoFaceDetectedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return FaceCompareOut(
        matched=result.matched,
        confidence=result.confidence,
        similarity=result.similarity,
        faces_detected_a=result.faces_detected_a,
        faces_detected_b=result.faces_detected_b,
    )
