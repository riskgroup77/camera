"""Qavat rejalari: rasmni tekshirish va kameralarning reja holati.

Router (app/routers/floor_plans.py) faqat HTTP qatlami — bu yerda
ikkalasi ham ishlatadigan va alohida test qilinadigan mantiq:

* Rasm turi mijoz yuborgan Content-Type'ga emas, faylning o'z sehrli
  baytlariga qarab aniqlanadi — aks holda "plan.png" deb nomlangan
  ixtiyoriy fayl omborga tushib, keyin brauzerga imzolangan havola bilan
  berilardi.
* O'lcham sarlavhadan o'qiladi (piksellar dekodlanmaydi): 15 MB'lik
  rasmni to'liq ochish API ishchisini keraksiz band qilardi, bizga esa
  faqat eni va bo'yi kerak (mijoz rejaning nisbatini oldindan biladi).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.camera_health import is_reachable, is_video_flowing
from app.models import Camera, Event
from app.models.platform import FloorPlan
from app.services.event_scope import NOT_SUPPRESSED, OPERATOR_EVENTS
from app.services.image_size import jpeg_dimensions

# nginx API uchun 50M qo'yadi (deploy/nginx/*api*.conf); qavat chizmasi
# uchun 15 MB yetarli — undan kattasi brauzerda ham sekin ochiladi.
MAX_PLAN_BYTES = 15 * 1024 * 1024
# Brauzer juda katta rasmni (masalan 30000x30000) xotiraga sig'dira
# olmaydi — sahifa qotadi. Chizmani eksport qilishda shu chegara ichida
# qolish qiyin emas.
MAX_PLAN_SIDE = 16384
MIN_PLAN_SIDE = 16

# "Ochiq" signal — hali yopilmagan ish: yangi (ko'rilmagan) yoki
# jarayonda (kimgadir tayinlangan). Tasdiqlangan/rad etilgan/hal qilingan
# signal markerni qizartirmaydi.
OPEN_EVENT_STATUSES = ("yangi", "jarayonda")
OPEN_EVENTS_WINDOW = timedelta(hours=24)


class PlanImageError(ValueError):
    """Rasm qabul qilinmaydi — xabar foydalanuvchiga ko'rsatiladi."""


@dataclass(frozen=True)
class PlanImage:
    content_type: str
    extension: str
    width: int
    height: int


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    # 8 bayt imzo, keyin birinchi bo'lak doim IHDR: uzunlik(4) tur(4)
    # en(4) bo'y(4), big-endian.
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30:
        return None
    chunk = data[12:16]
    if chunk == b"VP8 ":
        # Kalit kadr: 3 bayt teg, 9D 01 2A boshlanish kodi, keyin 14 bitli
        # en va bo'y (little-endian, yuqori 2 bit — masshtab).
        if data[23:26] != b"\x9d\x01\x2a":
            return None
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return width, height
    if chunk == b"VP8L":
        # Yo'qotishsiz: 0x2F imzo, keyin 14+14 bit (en-1, bo'y-1).
        if data[20] != 0x2F:
            return None
        b0, b1, b2, b3 = data[21], data[22], data[23], data[24]
        width = 1 + (((b1 & 0x3F) << 8) | b0)
        height = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
        return width, height
    if chunk == b"VP8X":
        # Kengaytirilgan: 4 bayt bayroqlar, keyin 24 bitli (en-1), (bo'y-1).
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    return None


def inspect_plan_image(data: bytes) -> PlanImage:
    """PNG/JPEG/WebP ekanini sehrli baytlardan aniqlaydi va o'lchamini
    sarlavhadan o'qiydi. Yaroqsiz bo'lsa PlanImageError."""
    if not data:
        raise PlanImageError("Fayl bo'sh")
    if len(data) > MAX_PLAN_BYTES:
        raise PlanImageError(f"Rasm juda katta — ko'pi bilan {MAX_PLAN_BYTES // (1024 * 1024)} MB")

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        kind, dims = ("image/png", "png"), _png_dimensions(data)
    elif data.startswith(b"\xff\xd8\xff"):
        kind, dims = ("image/jpeg", "jpg"), jpeg_dimensions(data)
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind, dims = ("image/webp", "webp"), _webp_dimensions(data)
    else:
        raise PlanImageError("Faqat PNG, JPEG yoki WebP rasm qabul qilinadi")

    if dims is None:
        raise PlanImageError("Rasm o'lchamini aniqlab bo'lmadi — fayl buzilgan bo'lishi mumkin")
    width, height = dims
    if width < MIN_PLAN_SIDE or height < MIN_PLAN_SIDE:
        raise PlanImageError("Rasm juda kichik")
    if width > MAX_PLAN_SIDE or height > MAX_PLAN_SIDE:
        raise PlanImageError(f"Rasm tomonlari {MAX_PLAN_SIDE} pikseldan oshmasligi kerak")
    return PlanImage(content_type=kind[0], extension=kind[1], width=width, height=height)


def default_plan_name(building_name: str, floor: int) -> str:
    return f"{building_name}, {floor}-qavat"


def on_plan_filter(plan: FloorPlan):
    """Rejaga tegishli kameralar: xuddi shu bino va qavat."""
    return and_(Camera.building_id == plan.building_id, Camera.floor == plan.floor)


def unassigned_candidate_filter(plan: FloorPlan):
    """Rejaga qo'yilganda shu qavatga biriktirilishi mumkin bo'lgan
    kameralar: binosi yo'q, yoki shu binoda, lekin qavati belgilanmagan.

    Boshqa bino/qavatdagi kamera bu yerga kirmaydi ATAYLAB: uni rejada
    sudrab qo'yish orqali jimgina boshqa qavatga ko'chirib yuborish
    xato bo'lardi — buning uchun kameralar sahifasidagi joylashuv
    tahriri bor."""
    return or_(
        Camera.building_id.is_(None),
        and_(Camera.building_id == plan.building_id, Camera.floor.is_(None)),
    )


def is_on_plan(camera: Camera, plan: FloorPlan) -> bool:
    return camera.building_id == plan.building_id and camera.floor == plan.floor


def is_unassigned_candidate(camera: Camera, plan: FloorPlan) -> bool:
    return camera.building_id is None or (camera.building_id == plan.building_id and camera.floor is None)


async def plan_camera_counts(
    db: AsyncSession, building_id: uuid.UUID | None = None
) -> dict[tuple[uuid.UUID, int], tuple[int, int]]:
    """(bino, qavat) -> (kameralar soni, rejaga qo'yilganlari) — bitta GROUP BY."""
    stmt = (
        select(
            Camera.building_id,
            Camera.floor,
            func.count(),
            func.count().filter(and_(Camera.plan_x.isnot(None), Camera.plan_y.isnot(None))),
        )
        .where(Camera.building_id.isnot(None), Camera.floor.isnot(None))
        .group_by(Camera.building_id, Camera.floor)
    )
    if building_id is not None:
        stmt = stmt.where(Camera.building_id == building_id)
    rows = (await db.execute(stmt)).all()
    return {(b, f): (total, placed) for b, f, total, placed in rows}


async def open_event_counts(db: AsyncSession, camera_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Kamera -> oxirgi 24 soatdagi ochiq signallar soni.

    Doira devor va hodisalar navbati bilan bir xil (event_scope): sinov
    signallari, reestrdan chiqarilgan modullar va avtomatik o'chirilgan
    kamera×modul juftligining eski signallari hisobga kirmaydi."""
    if not camera_ids:
        return {}
    since = datetime.now(timezone.utc) - OPEN_EVENTS_WINDOW
    rows = (
        await db.execute(
            select(Event.camera_id, func.count())
            .where(Event.camera_id.in_(camera_ids))
            .where(OPERATOR_EVENTS)
            .where(NOT_SUPPRESSED)
            .where(Event.status.in_(OPEN_EVENT_STATUSES))
            .where(Event.occurred_at >= since)
            .group_by(Event.camera_id)
        )
    ).all()
    return {camera_id: count for camera_id, count in rows}


def camera_health(camera: Camera) -> tuple[bool, bool]:
    """(onlayn, tasvir kelyapti) — Monitoring devori bilan bir xil
    semantika (app/routers/public.py _to_public_camera)."""
    online = camera.status == "faol" and is_reachable(camera.last_seen_at)
    return online, online and is_video_flowing(camera.last_frame_at)
