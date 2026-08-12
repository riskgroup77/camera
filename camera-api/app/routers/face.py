from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.dependencies import CurrentUser, get_current_user
from app.schemas.face import FaceCompareOut
from app.services.face_recognition import NoFaceDetectedError, compare_faces

router = APIRouter(prefix="/api/face", tags=["face"])


@router.post("/compare", response_model=FaceCompareOut)
async def compare(
    _: Annotated[CurrentUser, Depends(get_current_user)],
    image_a: Annotated[UploadFile, File(description="Pasportdan olingan surat")],
    image_b: Annotated[UploadFile, File(description="Kamerada suratga olingan jonli yuz")],
) -> FaceCompareOut:
    data_a, data_b = await image_a.read(), await image_b.read()
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
