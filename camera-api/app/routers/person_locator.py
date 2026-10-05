"""Ruxsatli nazoratchi uchun shaxsning oxirgi kamera kuzatuvi.

Bu "hozir qayerda" degan mutlaq da'vo qilmaydi: kamera odamni oxirgi
qachon va qayerda ko'rganini qaytaradi. Qidiruv POST bo'lgani uchun ism
brauzer tarixi va reverse-proxy URL loglariga tushmaydi.
"""

import asyncio
import uuid
from datetime import date as date_type, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import Building, Camera, PresenceVisit, StudentStaff, UnknownSighting
from app.schemas.person_locator import (
    PersonLocationOut,
    PersonLocationSearchIn,
    PersonRouteOut,
    PhotoPersonMatch,
    PhotoSearchOut,
    PhotoSightingMatch,
    RouteStopOut,
)
from app.services import face_matching, face_recognition
from app.services.access_scope import camera_column_filter
from app.services.person_search import VisitRow, group_stops, score_embeddings, top_people
from app.timezone import INSTITUTE_TZ, local_now
from app.timezone import business_today, day_start

router = APIRouter(prefix="/api/person-locator", tags=["person-locator"])
ReadDep = Annotated[CurrentUser, Depends(require_permission("viewLive"))]


def _initials(name: str) -> str:
    return "".join(part[0] for part in name.split()[:2]).upper() or "?"


@router.post("/search", response_model=list[PersonLocationOut])
async def search_person_location(
    body: PersonLocationSearchIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReadDep,
) -> list[PersonLocationOut]:
    """Ism bo'yicha faqat faol shaxslar va ularning eng so'nggi tashrifini qaytaradi."""
    # Har odam uchun eng so'nggi tashrif — LATERAL + LIMIT 1 (odam, last_seen
    # indeksi bo'yicha bir nechta qator o'qiladi). Ilgari row_number() butun
    # presence_visits jadvali (yil bo'yi, millionlab qator) ustida har qidiruvda
    # hisoblanardi — ism filtri va LIMIT unga tushmasdi.
    latest = (
        select(PresenceVisit.camera_id.label("camera_id"), PresenceVisit.last_seen_at.label("last_seen_at"))
        .where(PresenceVisit.student_staff_id == StudentStaff.id)
        # Bino doirasi: cheklangan foydalanuvchi faqat o'z binolaridagi kuzatuvni ko'radi.
        .where(camera_column_filter(current_user, PresenceVisit.camera_id))
        .order_by(PresenceVisit.last_seen_at.desc())
        .limit(1)
        .lateral("latest")
    )
    terms = [term for term in body.query.split() if term]
    stmt = (
        select(StudentStaff, latest.c.camera_id, latest.c.last_seen_at, Camera.name, Building.name, Camera.floor, Camera.zone)
        .select_from(StudentStaff)
        .outerjoin(latest, true())
        .outerjoin(Camera, Camera.id == latest.c.camera_id)
        .outerjoin(Building, Building.id == Camera.building_id)
        .where(StudentStaff.active.is_(True))
        .order_by(StudentStaff.full_name.asc())
        .limit(body.limit)
    )
    for term in terms:
        stmt = stmt.where(StudentStaff.full_name.ilike(f"%{term}%"))

    now = local_now()
    rows = (await db.execute(stmt)).all()
    return [
        PersonLocationOut(
            id=str(person.id),
            full_name=person.full_name,
            type=person.type,
            faculty=person.faculty.name if person.faculty else None,
            group_or_position=person.group_or_position,
            initials=_initials(person.full_name),
            camera_id=str(camera_id) if camera_id else None,
            camera_name=camera_name,
            building=building_name,
            floor=floor,
            zone=zone,
            last_seen_at=last_seen_at,
            currently_visible=bool(last_seen_at and last_seen_at >= now - timedelta(minutes=5)),
            # Yuzi tasdiqlanmagan odamni kameralar tanimaydi — "hali ko'rilmagan"
            # emas, "yuzsiz" deb aytish kerak.
            has_face=person.biometrics_status == "tasdiqlangan" and person.biometric_embedding is not None,
            photo_url=_presign(person.biometric_photo_key),
        )
        for person, camera_id, last_seen_at, camera_name, building_name, floor, zone in rows
    ]


# Rasm bo'yicha qidiruv chegaralari. 8 MB — telefon surati ham sig'adi,
# lekin API xotirasini katta fayl bilan to'ldirib bo'lmaydi.
MAX_SEARCH_PHOTO_BYTES = 8 * 1024 * 1024
PEOPLE_LIMIT = 8
SIGHTINGS_LIMIT = 60
# Notanish yuzlar har kuni yuzlab qator — oraliq cheklanmasa, bitta
# qidiruv butun tarixning vektorlarini xotiraga o'qib chiqardi.
MAX_RANGE_DAYS = 31
DEFAULT_RANGE_DAYS = 7


def _parse_date(value: str | None, field: str) -> date_type | None:
    if not value:
        return None
    try:
        return date_type.fromisoformat(value)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field}: sana YYYY-MM-DD ko'rinishida bo'lishi kerak")


def _presign(key: str | None) -> str | None:
    if not key:
        return None
    from app.storage import presigned_url

    try:
        return presigned_url(key)
    except Exception:
        # MinIO vaqtincha ishlamasa ham natija ro'yxati qaytishi kerak.
        return None


@router.post("/rasm", response_model=PhotoSearchOut)
async def search_by_photo(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReadDep,
    photo: Annotated[UploadFile, File(description="Qidirilayotgan odamning yuzi tushgan rasm")],
    dan: Annotated[str | None, Form()] = None,
    gacha: Annotated[str | None, Form()] = None,
    min_similarity: Annotated[float, Form(alias="min", ge=0.0, le=1.0)] = 0.35,
) -> PhotoSearchOut:
    """Rasmdagi yuzni ro'yxatdagi odamlar va kunduzgi notanish yuzlar
    bilan solishtiradi. Natija — nomzodlar, "shu odam" degan hukm emas:
    operator o'xshashlik foizini ko'rib o'zi qaror qiladi."""
    data = await photo.read(MAX_SEARCH_PHOTO_BYTES + 1)
    if len(data) > MAX_SEARCH_PHOTO_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Rasm 8 MB dan oshmasligi kerak")

    date_to = _parse_date(gacha, "gacha") or business_today()
    date_from = _parse_date(dan, "dan") or date_to - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    if date_from > date_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Boshlanish sanasi tugashidan keyin")
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Oraliq {MAX_RANGE_DAYS} kundan oshmasin")

    try:
        embedding = await face_recognition.extract_embedding(data)
    except face_recognition.NoFaceDetectedError as exc:
        # Rasm o'qilmasa xizmat o'z xabarini beradi ("Rasm formatini ...");
        # aks holda yuz yo'q — operatorga nima qilish kerakligini aytamiz.
        message = str(exc) if str(exc).startswith("Rasm") else "Rasmda yuz topilmadi — yuz aniq ko'ringan rasm yuklang"
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message) from exc

    # Ro'yxatdagi odamlar: sweep keshi — 10k qatorni har so'rovda
    # bazadan qayta o'qimaslik uchun. Matritsa ko'paytmasi CPU ishi.
    matrix = await face_matching.load_candidate_matrix_for_sweep(db)
    ranked = await asyncio.to_thread(top_people, matrix, embedding, PEOPLE_LIMIT, min_similarity)
    people: list[PhotoPersonMatch] = []
    if ranked:
        ids = [uuid.UUID(pid) for pid, _ in ranked]
        persons = {
            str(p.id): p
            for p in (await db.execute(select(StudentStaff).where(StudentStaff.id.in_(ids)))).scalars().all()
        }
        last_seen = {
            person_id: seen
            for person_id, seen in (
                await db.execute(
                    select(PresenceVisit.student_staff_id, func.max(PresenceVisit.last_seen_at))
                    .where(PresenceVisit.student_staff_id.in_(ids))
                    .where(camera_column_filter(current_user, PresenceVisit.camera_id))
                    .group_by(PresenceVisit.student_staff_id)
                )
            ).all()
        }
        for pid, similarity in ranked:
            person = persons.get(pid)
            if person is None:
                continue
            people.append(
                PhotoPersonMatch(
                    id=pid,
                    full_name=person.full_name,
                    type=person.type,
                    group_or_position=person.group_or_position,
                    similarity=round(similarity, 4),
                    photo_url=_presign(person.biometric_photo_key),
                    last_seen_at=last_seen.get(person.id),
                )
            )

    rows = (
        await db.execute(
            select(
                UnknownSighting.id,
                UnknownSighting.embedding,
                UnknownSighting.crop_key,
                UnknownSighting.camera_id,
                Camera.name.label("camera_name"),
                UnknownSighting.first_seen_at,
                UnknownSighting.last_seen_at,
                UnknownSighting.hits,
            )
            .outerjoin(Camera, Camera.id == UnknownSighting.camera_id)
            .where(UnknownSighting.day >= date_from, UnknownSighting.day <= date_to)
            .where(camera_column_filter(current_user, UnknownSighting.camera_id))
        )
    ).all()
    scores = await asyncio.to_thread(score_embeddings, embedding, [row.embedding for row in rows])
    matched = sorted(
        ((score, row) for score, row in zip(scores, rows, strict=True) if score >= min_similarity),
        key=lambda item: item[0],
        reverse=True,
    )[:SIGHTINGS_LIMIT]
    sightings = [
        PhotoSightingMatch(
            id=str(row.id),
            similarity=round(score, 4),
            crop_url=_presign(row.crop_key),
            camera_id=str(row.camera_id) if row.camera_id else None,
            camera_name=row.camera_name,
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
            hits=row.hits,
        )
        for score, row in matched
    ]

    # Qidiruv — shaxsiy ma'lumotga murojaat: kim, qachon qidirgani iz qoldiradi.
    await log_action(
        db,
        request,
        current_user.id,
        f"Rasm bo'yicha qidiruv: {date_from.isoformat()} – {date_to.isoformat()}, "
        f"{len(people)} ta odam, {len(sightings)} ta notanish",
        "Shaxs qidirish",
    )
    await db.commit()
    return PhotoSearchOut(
        people=people, sightings=sightings, date_from=date_from.isoformat(), date_to=date_to.isoformat()
    )


@router.get("/{person_id}/yol", response_model=PersonRouteOut)
async def person_route(
    person_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReadDep,
    sana: Annotated[str | None, Query()] = None,
) -> PersonRouteOut:
    """Odamning bir kunlik yo'li: kameralar bo'yicha to'xtashlar, vaqt tartibida."""
    try:
        pid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shaxs topilmadi")
    person = await db.get(StudentStaff, pid)
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shaxs topilmadi")
    day = _parse_date(sana, "sana") or business_today()
    # Kun chegarasi institut vaqtida: UTC bo'yicha olinsa, ertalabki
    # 5 soat oldingi kunga tushib qolardi (app/timezone.local_date).
    start = day_start(day)
    end = start + timedelta(days=1)

    rows = (
        await db.execute(
            select(PresenceVisit, Camera.name, Building.name, Camera.floor, Camera.zone)
            .outerjoin(Camera, Camera.id == PresenceVisit.camera_id)
            .outerjoin(Building, Building.id == Camera.building_id)
            .where(
                PresenceVisit.student_staff_id == pid,
                PresenceVisit.last_seen_at >= start,
                PresenceVisit.first_seen_at < end,
                camera_column_filter(current_user, PresenceVisit.camera_id),
            )
            .order_by(PresenceVisit.first_seen_at)
        )
    ).all()
    stops = group_stops(
        [
            VisitRow(
                camera_id=str(visit.camera_id) if visit.camera_id else None,
                camera_name=camera_name,
                building=building,
                floor=floor,
                zone=zone,
                first_seen_at=visit.first_seen_at,
                last_seen_at=visit.last_seen_at,
                sightings=visit.sightings,
                best_similarity=visit.best_similarity,
            )
            for visit, camera_name, building, floor, zone in rows
        ]
    )
    return PersonRouteOut(
        person_id=str(person.id),
        full_name=person.full_name,
        day=day.isoformat(),
        stops=[
            RouteStopOut(
                camera_id=stop.camera_id,
                camera_name=stop.camera_name,
                building=stop.building,
                floor=stop.floor,
                zone=stop.zone,
                started_at=stop.started_at,
                ended_at=stop.ended_at,
                count=stop.count,
                best_similarity=stop.best_similarity,
            )
            for stop in stops
        ],
    )
