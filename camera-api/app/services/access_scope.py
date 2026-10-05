"""Bino doirasi — foydalanuvchi qaysi binolar kameralarini ko'ra oladi.

User.allowed_building_ids: NULL yoki bo'sh ro'yxat — cheklov yo'q (barcha
binolar). Aks holda kameralar, ularning hodisalari, PTZ va video arxivi
faqat shu binolar bo'yicha. Super Admin HAR DOIM cheklovsiz: u doiralarni
tayinlaydigan odam, o'zini qulflab qo'ya olmasligi kerak.

Tekshiruv hamma joyda SHU modul orqali — har endpoint o'z shartini yozsa,
bittasi esdan chiqib, doira aylanib o'tiladigan teshik qolardi.

Muhim qarorlar:
  * Binosi belgilanmagan kamera (building_id NULL) cheklangan foydalanuvchiga
    KO'RINMAYDI — u hech bir binoga tegishli emas, "ruxsat etilgan binoda"
    deb aytib bo'lmaydi. Xavfsiz tomonga xato.
  * Doiradan tashqaridagi kamera/hodisa uchun 403 emas, 404: 403 "bunday
    kamera bor, lekin sizga yopiq" deb uning mavjudligini oshkor qilardi.
  * Kamerasi yo'q hodisa (camera_id NULL) ham cheklangan foydalanuvchiga
    ko'rinmaydi — xuddi shu sababdan.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, select, true

from app.models import Camera, Event

NOT_FOUND_CAMERA = "Kamera topilmadi"
NOT_FOUND_EVENT = "Hodisa topilmadi"


def allowed_buildings(user) -> set[uuid.UUID] | None:
    """None — cheklov yo'q. Aks holda ruxsat etilgan binolar to'plami.

    `user` — CurrentUser (yoki anonim devor rejimida None: anonim so'rov
    faqat himoya ataylab o'chirilganda bu yerga yetadi, ya'ni ochiq)."""
    if user is None or getattr(user, "role", None) == "super-admin":
        return None
    raw = getattr(user, "allowed_building_ids", None)
    if not raw:
        return None
    ids: set[uuid.UUID] = set()
    for value in raw:
        try:
            ids.add(uuid.UUID(str(value)))
        except ValueError:
            # Buzilgan qiymat hech narsaga ruxsat bermaydi — lekin butun
            # doirani "cheklovsiz"ga ham aylantirmaydi.
            continue
    if not ids:
        # Ro'yxat bo'sh emas edi, lekin birortasi ham yaroqli emas: bu
        # "hammasi" EMAS, "hech narsa" — xavfsiz tomon.
        return set()
    return ids


def is_restricted(user) -> bool:
    return allowed_buildings(user) is not None


def camera_filter(user) -> ColumnElement[bool]:
    """Camera so'rovlari uchun WHERE sharti."""
    ids = allowed_buildings(user)
    if ids is None:
        return true()
    return Camera.building_id.in_(ids)


def event_filter(user) -> ColumnElement[bool]:
    """Event so'rovlari uchun WHERE sharti (hodisa kamerasi orqali)."""
    ids = allowed_buildings(user)
    if ids is None:
        return true()
    return Event.camera_id.in_(select(Camera.id).where(Camera.building_id.in_(ids)))


def camera_column_filter(user, column) -> ColumnElement[bool]:
    """Kamera ustuni bor istalgan jadval (tashriflar, notanish yuzlar,
    yuz tekshiruvi...) uchun WHERE sharti. Kamerasi yo'q (NULL) qator
    cheklangan foydalanuvchiga ko'rinmaydi."""
    ids = allowed_buildings(user)
    if ids is None:
        return true()
    return column.in_(select(Camera.id).where(Camera.building_id.in_(ids)))


async def allowed_camera_ids(db, user) -> set[uuid.UUID] | None:
    """None — cheklov yo'q; aks holda doiradagi kameralar id'lari."""
    ids = allowed_buildings(user)
    if ids is None:
        return None
    if not ids:
        return set()
    return set((await db.execute(select(Camera.id).where(Camera.building_id.in_(ids)))).scalars().all())


def camera_allowed(user, camera: Camera) -> bool:
    ids = allowed_buildings(user)
    return ids is None or (camera.building_id is not None and camera.building_id in ids)


def ensure_camera_allowed(user, camera: Camera) -> Camera:
    """Doiradan tashqaridagi kamera — 404 (mavjudligini ham oshkor qilmaymiz)."""
    if not camera_allowed(user, camera):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND_CAMERA)
    return camera
