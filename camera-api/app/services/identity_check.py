"""Ro'yxatdan o'tayotgan odam — AYNAN o'sha odammi (HEMIS surati bilan 1:1).

Muammo: ochiq ro'yxatdan o'tish sahifasida shaxs JSHSHIR (yoki pasport)
bilan topiladi. JSHSHIR sir emas — hujjatlarda, ro'yxatlarda bor. Tiriklik
tekshiruvi "tirik odam"ni isbotlaydi, "AYNAN SHU odam"ni emas. Shuning uchun
begona odam birovning JSHSHIRi bilan o'z yuzini uning nomiga bog'lab qo'yishi
mumkin edi.

Yechim: institut ro'yxatidagi (HEMIS) odamning HEMIS'dagi rasmi bor
(StudentStaff.hemis_photo_url). Topshirilgan yuz shu rasm bilan solishtiriladi:
mos kelsa — avtomatik tasdiq, mos kelmasa yoki rasm bo'lmasa — administrator
ko'radi. HEMIS rasmi faqat TEKSHIRISH uchun ishlatiladi: u tanish bazasiga
qo'shilmaydi va saqlanmaydi (institut qarori: tanish faqat 3 tomonlama
ro'yxatdan o'tgan yuz bo'yicha).
"""

from __future__ import annotations

import logging

import httpx
import numpy as np

from app.models import StudentStaff

logger = logging.getLogger("app.identity_check")


def _unit(vector) -> np.ndarray | None:
    arr = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    return arr / norm if norm > 0 else None


async def hemis_similarity(person: StudentStaff, embedding: list[float]) -> tuple[float | None, str | None]:
    """(o'xshashlik, None) yoki (None, nega solishtirib bo'lmadi)."""
    from app.jobs.hemis_photos import PhotoTooLarge, _embed_photo, allowed_photo_host, fetch_photo
    from app.services.face_recognition import NoFaceDetectedError

    url = person.hemis_photo_url or ""
    if not url:
        return None, "HEMIS'da surati yo'q"
    if not allowed_photo_host(url):
        return None, "HEMIS surati manzili HEMIS domenidan emas"
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            code, content_type, body = await fetch_photo(client, url)
    except PhotoTooLarge:
        return None, "HEMIS surati juda katta"
    except httpx.HTTPError as error:
        logger.warning("HEMIS photo download failed", extra={"person_id": str(person.id), "error": type(error).__name__})
        return None, "HEMIS surati yuklanmadi"
    if code != 200 or not content_type.startswith("image/"):
        return None, f"HEMIS surati yuklanmadi ({code})"
    try:
        reference, _height = await _embed_photo(body)
    except NoFaceDetectedError:
        return None, "HEMIS suratida yuz aniqlanmadi"
    a, b = _unit(reference), _unit(embedding)
    if a is None or b is None:
        return None, "Yuz vektori bo'sh"
    return float(a @ b), None
