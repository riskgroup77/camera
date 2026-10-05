"""Kunduzgi notanish yuzlar — /api/notanishlar.

Ko'rib chiqish oqimi uchun: ro'yxat, "talaba" (odamga biriktirish),
"begona" (hodisa) va "o'tkazish". Mantiq app/services/unknown_sightings.py
da; bu yerda faqat HTTP, huquq va audit.
"""

import uuid
from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, has_any_permission, require_permission
from app.models import Camera, StudentStaff, UnknownSighting
from app.services.access_scope import allowed_camera_ids, camera_column_filter
from app.services.face_matching import announce_roster_change
from app.schemas.base import CamelModel
from app.services.unknown_clusters import assign_group, dismiss_group, lookalikes, recurring_clusters
from app.services.unknown_sightings import ResolveError, assign_to_person, dismiss, mark_stranger
from app.timezone import local_now
from app.timezone import business_today

router = APIRouter(prefix="/api/notanishlar", tags=["notanishlar"])

ReviewDep = Annotated[CurrentUser, Depends(require_permission("reviewEvents"))]

STATUSES = ("kutilmoqda", "talaba", "begona", "otkazildi")


class SightingOut(CamelModel):
    id: str
    day: str
    camera_id: str | None
    camera_name: str | None
    first_seen_at: str
    last_seen_at: str
    hits: int
    crop_url: str | None
    face_px: int
    closest_similarity: float | None
    status: str
    person_id: str | None
    person_name: str | None


class SightingListOut(CamelModel):
    items: list[SightingOut]
    total: int
    pending: int
    day: str


class AssignIn(CamelModel):
    person_id: str


class ResolveOut(CamelModel):
    item: SightingOut
    message: str


def _to_out(row: UnknownSighting, camera_name: str | None, person_name: str | None) -> SightingOut:
    from app.storage import presigned_url

    crop_url = None
    if row.crop_key:
        try:
            crop_url = presigned_url(row.crop_key)
        except Exception:
            crop_url = None
    return SightingOut(
        id=str(row.id),
        day=row.day.isoformat(),
        camera_id=str(row.camera_id) if row.camera_id else None,
        camera_name=camera_name,
        first_seen_at=row.first_seen_at.isoformat(),
        last_seen_at=row.last_seen_at.isoformat(),
        hits=row.hits,
        crop_url=crop_url,
        face_px=row.face_px,
        closest_similarity=row.closest_similarity,
        status=row.status,
        person_id=str(row.person_id) if row.person_id else None,
        person_name=person_name,
    )


async def _names(db: AsyncSession, row: UnknownSighting) -> tuple[str | None, str | None]:
    camera = await db.get(Camera, row.camera_id) if row.camera_id else None
    person = await db.get(StudentStaff, row.person_id) if row.person_id else None
    return (camera.name if camera else None, person.full_name if person else None)


def _parse_day(value: str | None) -> date_type:
    if not value:
        return business_today()
    try:
        return date_type.fromisoformat(value)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Sana YYYY-MM-DD ko'rinishida bo'lishi kerak")


@router.get("", response_model=SightingListOut)
async def list_sightings(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
    sana: Annotated[str | None, Query()] = None,
    holat: Annotated[str, Query()] = "kutilmoqda",
    limit: Annotated[int, Query(ge=1, le=300)] = 120,
) -> SightingListOut:
    """Bir kunlik notanish yuzlar. Standart — bugungi, ko'rib chiqilmaganlar;
    eng ko'p ko'ringani birinchi (tez-tez keladigan odam — ehtimol talaba)."""
    day = _parse_day(sana)
    if holat not in (*STATUSES, "hammasi"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Noma'lum holat")

    query = (
        select(UnknownSighting, Camera.name, StudentStaff.full_name)
        .outerjoin(Camera, Camera.id == UnknownSighting.camera_id)
        .outerjoin(StudentStaff, StudentStaff.id == UnknownSighting.person_id)
        .where(UnknownSighting.day == day)
        .where(camera_column_filter(current_user, UnknownSighting.camera_id))
    )
    if holat != "hammasi":
        query = query.where(UnknownSighting.status == holat)
    rows = (
        await db.execute(query.order_by(UnknownSighting.hits.desc(), UnknownSighting.last_seen_at.desc()).limit(limit))
    ).all()

    scope = camera_column_filter(current_user, UnknownSighting.camera_id)
    total_query = select(func.count()).select_from(UnknownSighting).where(UnknownSighting.day == day, scope)
    if holat != "hammasi":
        total_query = total_query.where(UnknownSighting.status == holat)
    total = int((await db.execute(total_query)).scalar_one())
    pending = int(
        (
            await db.execute(
                select(func.count())
                .select_from(UnknownSighting)
                .where(UnknownSighting.day == day, UnknownSighting.status == "kutilmoqda", scope)
            )
        ).scalar_one()
    )
    return SightingListOut(
        items=[_to_out(row, camera_name, person_name) for row, camera_name, person_name in rows],
        total=total,
        pending=pending,
        day=day.isoformat(),
    )


class ClusterHintOut(CamelModel):
    person_id: str
    full_name: str
    group_or_position: str
    similarity: float


class ClusterOut(CamelModel):
    key: str
    sighting_ids: list[str]
    days: int
    hits: int
    cameras: list[str]
    first_seen_at: str
    last_seen_at: str
    face_px: int
    crop_urls: list[str]
    hints: list[ClusterHintOut]


class ClusterListOut(CamelModel):
    items: list[ClusterOut]
    pending: int


class ClusterAssignIn(CamelModel):
    sighting_ids: list[str]
    person_id: str


class ClusterDismissIn(CamelModel):
    sighting_ids: list[str]


class ClusterActionOut(CamelModel):
    message: str
    count: int


def _crop_urls(rows: list[UnknownSighting], limit: int = 6) -> list[str]:
    """Eng yirik yuzlar, iloji boricha turli kunlardan (turli burchak/kiyim)."""
    from app.storage import presigned_url

    ordered = sorted(rows, key=lambda row: (row.face_px or 0), reverse=True)
    picked: list[UnknownSighting] = []
    seen_days: set = set()
    for row in ordered:
        if row.crop_key and row.day not in seen_days:
            picked.append(row)
            seen_days.add(row.day)
    for row in ordered:
        if len(picked) >= limit:
            break
        if row.crop_key and row not in picked:
            picked.append(row)
    urls = []
    for row in picked[:limit]:
        try:
            urls.append(presigned_url(row.crop_key))
        except Exception:
            continue
    return urls


class PersonPickOut(CamelModel):
    id: str
    full_name: str
    group_or_position: str
    biometrics_status: str


@router.get("/odamlar", response_model=list[PersonPickOut])
async def pick_person(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: ReviewDep,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> list[PersonPickOut]:
    """Yuzni kimga biriktirish — ism bo'yicha qisqa qidiruv (faqat ism va
    guruh). Reestr qidiruvi registerPeople talab qiladi; hodisalarni
    ko'ruvchi operator u holda hech kimni topa olmasdi."""
    stmt = select(StudentStaff).where(StudentStaff.active.is_(True))
    for word in q.replace("’", "'").replace("ʻ", "'").split():
        stmt = stmt.where(StudentStaff.full_name.ilike(f"%{word}%"))
    rows = (await db.execute(stmt.order_by(StudentStaff.full_name).limit(limit))).scalars().all()
    return [
        PersonPickOut(
            id=str(p.id),
            full_name=p.full_name,
            group_or_position=p.group_or_position or "",
            biometrics_status=p.biometrics_status,
        )
        for p in rows
    ]


@router.get("/takroriy", response_model=ClusterListOut)
async def list_recurring(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
    kun: Annotated[int, Query(ge=1, le=30)] = 14,
    min_kun: Annotated[int, Query(ge=1, le=30)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 40,
) -> ClusterListOut:
    """Takroriy notanishlar — bir odam bo'yicha guruhlangan, eng ko'p KUN
    ko'ringani birinchi (app/services/unknown_clusters.py)."""
    clusters = await recurring_clusters(db, days=kun, min_days=min_kun, limit=limit)
    allowed = await allowed_camera_ids(db, current_user)
    if allowed is not None:
        # Guruhda doiradan tashqaridagi kamera yuzi bo'lsa — butun guruh ko'rsatilmaydi.
        clusters = [c for c in clusters if all(row.camera_id in allowed for row in c.rows)]
    camera_ids = {row.camera_id for cluster in clusters for row in cluster.rows if row.camera_id}
    names = {}
    if camera_ids:
        names = dict((await db.execute(select(Camera.id, Camera.name).where(Camera.id.in_(camera_ids)))).all())
    items = []
    for cluster in clusters:
        hints = await lookalikes(db, cluster.centroid) if cluster.centroid is not None else []
        cameras = sorted({names.get(row.camera_id) for row in cluster.rows if names.get(row.camera_id)})
        items.append(
            ClusterOut(
                key=str(cluster.best.id),
                sighting_ids=[str(row.id) for row in cluster.rows],
                days=cluster.days,
                hits=cluster.hits,
                cameras=cameras[:6],
                first_seen_at=min(row.first_seen_at for row in cluster.rows).isoformat(),
                last_seen_at=max(row.last_seen_at for row in cluster.rows).isoformat(),
                face_px=int(cluster.best.face_px or 0),
                crop_urls=_crop_urls(cluster.rows),
                hints=[
                    ClusterHintOut(
                        person_id=str(person.id),
                        full_name=person.full_name,
                        group_or_position=person.group_or_position or "",
                        similarity=round(similarity, 3),
                    )
                    for person, similarity in hints
                ],
            )
        )
    pending = int(
        (
            await db.execute(
                select(func.count())
                .select_from(UnknownSighting)
                .where(UnknownSighting.status == "kutilmoqda")
                .where(camera_column_filter(current_user, UnknownSighting.camera_id))
            )
        ).scalar_one()
    )
    return ClusterListOut(items=items, pending=pending)


@router.post("/takroriy/biriktirish", response_model=ClusterActionOut)
async def assign_recurring(
    body: ClusterAssignIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
) -> ClusterActionOut:
    """Butun guruhni odamga biriktiradi: eng yirik yuz — asosiy rasm (yuzi
    bo'lmasa) yoki galereya namunasi, qolganlari galereyaga."""
    if not body.sighting_ids or len(body.sighting_ids) > 500:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Guruh bo'sh yoki juda katta")
    try:
        person = await db.get(StudentStaff, uuid.UUID(body.person_id))
    except ValueError:
        person = None
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Odam topilmadi")
    await _ensure_group_in_scope(db, current_user, body.sighting_ids)
    can_enroll = await has_any_permission(db, current_user.role, ("registerPeople",))
    try:
        kind, added = await assign_group(db, body.sighting_ids, person, current_user.id, can_enroll=can_enroll)
    except ResolveError as error:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(error))
    await log_action(
        db,
        request,
        current_user.id,
        f"Takroriy notanish ({len(body.sighting_ids)} yuz) {person.full_name} ga biriktirildi ({kind}, +{added})",
        "Xavfsizlik",
    )
    await db.commit()
    if kind != "tekshiruvda":
        # Yangi yuz / galereya namunasi — tanish ro'yxati darhol yangilansin
        # (aks holda 5 daqiqagacha eski ro'yxat bilan ishlardi).
        await announce_roster_change()
    if kind == "tekshiruvda":
        return ClusterActionOut(
            message=f"{person.full_name}: yuz registrga tekshiruvga yuborildi — tasdiqlangach kamera uni taniydi",
            count=len(body.sighting_ids),
        )
    first = "yuzi tizimga kiritildi" if kind == "asosiy" else "yangi yuz namunasi qo'shildi"
    extra = f", yana {added} ta burchak galereyaga" if added else ""
    return ClusterActionOut(
        message=f"{person.full_name}: {first}{extra} — endi kamera uni taniydi", count=len(body.sighting_ids)
    )


@router.post("/takroriy/otkazish", response_model=ClusterActionOut)
async def dismiss_recurring(
    body: ClusterDismissIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
) -> ClusterActionOut:
    if not body.sighting_ids or len(body.sighting_ids) > 500:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Guruh bo'sh yoki juda katta")
    await _ensure_group_in_scope(db, current_user, body.sighting_ids)
    try:
        count = await dismiss_group(db, body.sighting_ids, current_user.id)
    except ResolveError as error:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(error))
    await db.commit()
    return ClusterActionOut(message="O'tkazib yuborildi", count=count)


async def _load(db: AsyncSession, sighting_id: str, user: CurrentUser) -> UnknownSighting:
    try:
        key = uuid.UUID(sighting_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")
    row = await db.get(UnknownSighting, key)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")
    allowed = await allowed_camera_ids(db, user)
    if allowed is not None and row.camera_id not in allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")
    return row


async def _ensure_group_in_scope(db: AsyncSession, user: CurrentUser, sighting_ids: list[str]) -> None:
    allowed = await allowed_camera_ids(db, user)
    if allowed is None:
        return
    keys = []
    for value in sighting_ids:
        try:
            keys.append(uuid.UUID(value))
        except ValueError:
            continue
    cameras = (await db.execute(select(UnknownSighting.camera_id).where(UnknownSighting.id.in_(keys)))).scalars().all()
    if any(camera_id not in allowed for camera_id in cameras):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")


@router.post("/{sighting_id}/talaba", response_model=ResolveOut)
async def resolve_as_person(
    sighting_id: str,
    body: AssignIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
) -> ResolveOut:
    """Yuzni tanlangan odamga biriktiradi — keyingi safar kamera uni taniydi."""
    row = await _load(db, sighting_id, current_user)
    try:
        person = await db.get(StudentStaff, uuid.UUID(body.person_id))
    except ValueError:
        person = None
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Odam topilmadi")
    can_enroll = await has_any_permission(db, current_user.role, ("registerPeople",))
    try:
        kind = await assign_to_person(db, row, person, current_user.id, can_enroll=can_enroll)
    except ResolveError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error))
    await log_action(
        db, request, current_user.id, f"Notanish yuz {person.full_name} ga biriktirildi ({kind})", "Xavfsizlik"
    )
    await db.commit()
    if kind != "tekshiruvda":
        await announce_roster_change()
    camera_name, person_name = await _names(db, row)
    message = {
        "asosiy": f"{person.full_name}: yuzi tizimga kiritildi — endi kamera uni taniydi",
        "tekshiruvda": f"{person.full_name}: yuz registrga tekshiruvga yuborildi — tasdiqlangach kamera uni taniydi",
    }.get(kind, f"{person.full_name}: yangi yuz namunasi qo'shildi")
    return ResolveOut(item=_to_out(row, camera_name, person_name), message=message)


@router.post("/{sighting_id}/begona", response_model=ResolveOut)
async def resolve_as_stranger(
    sighting_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
) -> ResolveOut:
    """Haqiqiy begona — #1 hodisa yaratiladi."""
    row = await _load(db, sighting_id, current_user)
    try:
        await mark_stranger(db, row, current_user.id)
    except ResolveError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error))
    await log_action(db, request, current_user.id, "Notanish yuz begona deb tasdiqlandi", "Xavfsizlik")
    await db.commit()
    camera_name, person_name = await _names(db, row)
    return ResolveOut(item=_to_out(row, camera_name, person_name), message="Begona shaxs — hodisa yaratildi")


@router.post("/{sighting_id}/otkazish", response_model=ResolveOut)
async def resolve_as_dismissed(
    sighting_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
) -> ResolveOut:
    row = await _load(db, sighting_id, current_user)
    try:
        dismiss(row, current_user.id)
    except ResolveError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error))
    await db.commit()
    camera_name, person_name = await _names(db, row)
    return ResolveOut(item=_to_out(row, camera_name, person_name), message="O'tkazib yuborildi")
