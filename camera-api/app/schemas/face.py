from app.schemas.base import CamelModel


class FaceCompareOut(CamelModel):
    matched: bool
    confidence: float
    similarity: float
    faces_detected_a: int
    faces_detected_b: int
