"""Kunlik video tahlil: holat, ishga tushirish, natijalar va NVR sozlamasi.

Tahlilni o'zi ai-worker (leader) bajaradi (app/jobs/video_analysis.py) —
API faqat navbatga qo'yadi va natijani o'qiydi.
"""

from __future__ import annotations

import uuid
from datetime import date as date_type, datetime, time as time_type, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.config import settings
from app.crypto import encrypt
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import (
    Camera,
    DailyPersonCriteria,
    NvrDevice,
    StudentStaff,
    VideoAnalysisJob,
    VideoAnalysisRun,
)
from app.pagination import Page, PageParams, build_page
from app.schemas.video_analysis import (
    AnalysisStatusOut,
    AutoMapOut,
    CameraNvrIn,
    CriteriaSummaryOut,
    DailyCriteriaRowOut,
    EvidenceOut,
    JobErrorOut,
    JobSummaryOut,
    NvrChannelOut,
    NvrIn,
    NvrOut,
    NvrPatch,
    NvrTestOut,
    RunCreateIn,
    RunDetailOut,
    RunOut,
)
from app.services.nvr import NvrError, isapi_for
from app.services.nvr.sources import FolderSource
from app.timezone import INSTITUTE_TZ, business_date, business_today, to_local

router = APIRouter(prefix="/api/video-tahlil", tags=["video-tahlil"])

Admin = Annotated[CurrentUser, Depends(require_permission("systemSettings"))]
Reader = Annotated[
    CurrentUser, Depends(require_permission("viewReports", "manageAttendance", "systemSettings"))
]
Db = Annotated[AsyncSession, Depends(get_db)]

ACTIVE = ("navbatda", "ishlamoqda", "agregatsiya")


def _iso(moment: datetime | None) -> str | None:
    return to_local(moment).isoformat(timespec="seconds") if moment else None


def run_out(run: VideoAnalysisRun) -> RunOut:
    progress = (run.jobs_done + run.jobs_failed) / run.jobs_total if run.jobs_total else (1.0 if run.status == "tugadi" else 0.0)
    if run.status == "tugadi":
        progress = 1.0
    return RunOut(
        id=str(run.id),
        day=run.day.isoformat(),
        status=run.status,
        window_start=_iso(run.window_start) or "",
        window_end=_iso(run.window_end) or "",
        created_at=_iso(run.created_at),
        started_at=_iso(run.started_at),
        finished_at=_iso(run.finished_at),
        jobs_total=run.jobs_total,
        jobs_done=run.jobs_done,
        jobs_failed=run.jobs_failed,
        jobs_no_video=run.jobs_no_video,
        frames_planned=run.frames_planned,
        frames_analyzed=run.frames_analyzed,
        faces_detected=run.faces_detected,
        observations=run.observations,
        progress=round(min(1.0, progress), 4),
        stats=run.stats,
        error=run.error,
        triggered_by=run.triggered_by,
    )


async def _live_counters(db: AsyncSession, run: VideoAnalysisRun) -> None:
    """Ishlayotgan tahlil uchun hisoblagichlar bazadan (worker ularni
    vaqti-vaqti bilan yozadi — sahifa esa har necha soniyada so'raydi)."""
    if run.status not in ACTIVE:
        return
    rows = (
        await db.execute(
            select(VideoAnalysisJob.status, func.count(), func.coalesce(func.sum(VideoAnalysisJob.frames), 0))
            .where(VideoAnalysisJob.run_id == run.id)
            .group_by(VideoAnalysisJob.status)
        )
    ).all()
    counts = {row[0]: row[1] for row in rows}
    run.jobs_done = counts.get("tugadi", 0) + counts.get("yozuv_yoq", 0)
    run.jobs_failed = counts.get("xato", 0)
    run.jobs_no_video = counts.get("yozuv_yoq", 0)
    run.frames_analyzed = int(sum(row[2] for row in rows))


def _next_run_at(now: datetime) -> datetime:
    start = time_type.fromisoformat(settings.video_analysis_start)
    today = business_date(now)
    candidate = datetime.combine(today, start, tzinfo=INSTITUTE_TZ)
    if candidate <= now:
        candidate = datetime.combine(today + timedelta(days=1), start, tzinfo=INSTITUTE_TZ)
    return candidate


@router.get("/holat", response_model=AnalysisStatusOut)
async def analysis_status(db: Db, _: Reader) -> AnalysisStatusOut:
    now = datetime.now(timezone.utc)
    current = (
        await db.execute(
            select(VideoAnalysisRun).where(VideoAnalysisRun.status.in_(ACTIVE)).order_by(VideoAnalysisRun.created_at).limit(1)
        )
    ).scalar_one_or_none()
    if current is not None:
        await _live_counters(db, current)
    last = (
        await db.execute(
            select(VideoAnalysisRun)
            .where(VideoAnalysisRun.status.not_in(ACTIVE))
            .order_by(VideoAnalysisRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    nvr_count = await db.scalar(select(func.count()).select_from(NvrDevice).where(NvrDevice.enabled.is_(True)))
    mapped = await db.scalar(
        select(func.count()).select_from(Camera).where(Camera.nvr_id.is_not(None), Camera.nvr_channel.is_not(None))
    )
    active = await db.scalar(select(func.count()).select_from(Camera).where(Camera.status == "faol"))
    return AnalysisStatusOut(
        mode=settings.analysis_mode,
        start_time=settings.video_analysis_start,
        day_start=settings.video_analysis_day_start,
        next_run_at=_iso(_next_run_at(now)) if settings.analysis_mode == "kunlik" else None,
        nvr_count=nvr_count or 0,
        mapped_cameras=mapped or 0,
        active_cameras=active or 0,
        current=run_out(current) if current else None,
        last=run_out(last) if last else None,
    )


@router.get("/ishlar", response_model=list[RunOut])
async def list_runs(db: Db, _: Reader, limit: int = Query(30, ge=1, le=200)) -> list[RunOut]:
    runs = (
        await db.execute(select(VideoAnalysisRun).order_by(VideoAnalysisRun.created_at.desc()).limit(limit))
    ).scalars().all()
    for run in runs:
        await _live_counters(db, run)
    return [run_out(run) for run in runs]


@router.get("/ishlar/{run_id}", response_model=RunDetailOut)
async def get_run(run_id: uuid.UUID, db: Db, _: Reader) -> RunDetailOut:
    run = await db.get(VideoAnalysisRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tahlil topilmadi")
    await _live_counters(db, run)
    jobs = (
        await db.execute(
            select(
                VideoAnalysisJob.kind,
                VideoAnalysisJob.status,
                func.count(),
                func.coalesce(func.sum(VideoAnalysisJob.frames), 0),
            )
            .where(VideoAnalysisJob.run_id == run.id)
            .group_by(VideoAnalysisJob.kind, VideoAnalysisJob.status)
            .order_by(VideoAnalysisJob.kind, VideoAnalysisJob.status)
        )
    ).all()
    errors = (
        await db.execute(
            select(VideoAnalysisJob, Camera.name)
            .outerjoin(Camera, Camera.id == VideoAnalysisJob.camera_id)
            .where(VideoAnalysisJob.run_id == run.id, VideoAnalysisJob.status.in_(("xato", "yozuv_yoq")))
            .order_by(VideoAnalysisJob.start_at)
            .limit(50)
        )
    ).all()
    base = run_out(run)
    return RunDetailOut(
        **base.model_dump(),
        jobs=[JobSummaryOut(kind=k, status=s, count=c, frames=int(f)) for k, s, c, f in jobs],
        errors=[
            JobErrorOut(
                camera_name=name, kind=job.kind, status=job.status, error=job.error, start_at=_iso(job.start_at) or ""
            )
            for job, name in errors
        ],
    )


@router.post("/ishlar", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def start_run(body: RunCreateIn, request: Request, db: Db, user: Admin) -> RunOut:
    """Kunni (qayta) tahlil qilish. Bugungi kun uchun oyna hozirgacha."""
    if body.day > business_today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Kelajakdagi kunni tahlil qilib bo'lmaydi")
    if body.day < business_today() - timedelta(days=60):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "NVR odatda 60 kundan eski yozuvni saqlamaydi")
    from app.jobs.video_analysis import create_run, lock_runs

    await lock_runs(db)  # tekshiruv va yaratish orasida ikkinchi so'rov kira olmaydi
    busy = await db.scalar(select(func.count()).select_from(VideoAnalysisRun).where(VideoAnalysisRun.status.in_(ACTIVE)))
    if busy:
        raise HTTPException(status.HTTP_409_CONFLICT, "Boshqa tahlil hali tugamagan")

    run = await create_run(db, body.day, triggered_by="qolda")
    await log_action(db, request, user.id, f"Video tahlil ishga tushirildi: {body.day.isoformat()}", "Video tahlil")
    await db.commit()
    return run_out(run)


@router.post("/ishlar/{run_id}/bekor", response_model=RunOut)
async def cancel_run(run_id: uuid.UUID, request: Request, db: Db, user: Admin) -> RunOut:
    run = await db.get(VideoAnalysisRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tahlil topilmadi")
    if run.status not in ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tahlil allaqachon tugagan")
    run.cancel_requested = True
    if run.status == "navbatda" and run.started_at is None:
        run.status = "bekor"
        run.finished_at = datetime.now(timezone.utc)
    await db.commit()
    await log_action(db, request, user.id, f"Video tahlil bekor qilindi: {run.day.isoformat()}", "Video tahlil")
    await db.commit()
    return run_out(run)


# ── natijalar ───────────────────────────────────────────────────────────


def _findings(row: DailyPersonCriteria) -> list[dict]:
    return list((row.details or {}).get("dalillar") or [])


def _evidence_out(items: list[dict], camera_names: dict[str, str]) -> list[EvidenceOut]:
    from app.storage import presigned_url

    out = []
    for item in items:
        try:
            at = _iso(datetime.fromisoformat(item["vaqt"])) or ""
        except (KeyError, TypeError, ValueError):
            continue
        out.append(
            EvidenceOut(
                code=int(item.get("kod") or 0),
                reason=str(item.get("sabab") or ""),
                at=at,
                camera_name=camera_names.get(str(item.get("kamera_id"))),
                clip_url=presigned_url(item["klip"]) if item.get("klip") else None,
                clip_error=item.get("klip_xato"),
            )
        )
    return out


def _row_out(
    row: DailyPersonCriteria, person: StudentStaff, camera_names: dict[str, str] | None = None
) -> DailyCriteriaRowOut:
    findings = _findings(row)
    return DailyCriteriaRowOut(
        person_id=str(person.id),
        full_name=person.full_name,
        type=person.type,
        group_or_position=person.group_or_position,
        day=row.day.isoformat(),
        attendance_status=row.attendance_status,
        arrived_at=_iso(row.arrived_at),
        left_at=_iso(row.left_at),
        late_minutes=row.late_minutes,
        early_leave=row.early_leave,
        sightings=row.sightings,
        cameras_seen=row.cameras_seen,
        lessons_total=row.lessons_total,
        lessons_attended=row.lessons_attended,
        lessons_late=row.lessons_late,
        lessons_left_early=row.lessons_left_early,
        lessons_unmeasured=row.lessons_unmeasured,
        attention_score=row.attention_score,
        coat_status=row.coat_status,
        coat_samples=row.coat_samples,
        coat_white_samples=row.coat_white_samples,
        smoking_events=row.smoking_events,
        teacher_lessons=row.teacher_lessons,
        teacher_on_time=row.teacher_on_time,
        teacher_late=row.teacher_late,
        teacher_absent=row.teacher_absent,
        teacher_activity=row.teacher_activity,
        evidence_count=len(findings),
        evidence=_evidence_out(findings, camera_names) if camera_names is not None else [],
    )


async def _camera_names(db: AsyncSession, rows: list[DailyPersonCriteria]) -> dict[str, str]:
    ids = {uuid.UUID(item["kamera_id"]) for row in rows for item in _findings(row) if item.get("kamera_id")}
    if not ids:
        return {}
    return {
        str(camera_id): name
        for camera_id, name in (await db.execute(select(Camera.id, Camera.name).where(Camera.id.in_(ids)))).all()
    }


FILTERS = {
    "kech": DailyPersonCriteria.late_minutes > 0,
    "kelmadi": DailyPersonCriteria.attendance_status == "kelmadi",
    "erta_ketdi": DailyPersonCriteria.early_leave == "erta_ketdi",
    "darsga_kech": DailyPersonCriteria.lessons_late > 0,
    "darsdan_erta": DailyPersonCriteria.lessons_left_early > 0,
    "xalatsiz": DailyPersonCriteria.coat_status == "kiymagan",
    "chekish": DailyPersonCriteria.smoking_events > 0,
    "diqqat_past": DailyPersonCriteria.attention_score < 60,
    "oqituvchi_kech": or_(DailyPersonCriteria.teacher_late > 0, DailyPersonCriteria.teacher_absent > 0),
    # Kamida bitta aniqlangan holat (dalil bilan) bor odamlar.
    "holatli": func.jsonb_array_length(DailyPersonCriteria.details["dalillar"]) > 0,
}


@router.get("/natijalar", response_model=Page[DailyCriteriaRowOut])
async def list_results(
    db: Db,
    _: Reader,
    day: date_type | None = None,
    person_type: Annotated[str | None, Query(alias="type", pattern="^(talaba|xodim)$")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    criterion: Annotated[str | None, Query(alias="filter")] = None,
    page: PageParams = Depends(),
) -> Page[DailyCriteriaRowOut]:
    target = day or await _latest_day(db)
    if target is None:
        return build_page([], 0, page)
    stmt = (
        select(DailyPersonCriteria, StudentStaff)
        .join(StudentStaff, StudentStaff.id == DailyPersonCriteria.student_staff_id)
        .where(DailyPersonCriteria.day == target)
    )
    if person_type:
        stmt = stmt.where(StudentStaff.type == person_type)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(StudentStaff.full_name.ilike(like), StudentStaff.group_or_position.ilike(like)))
    if criterion:
        clause = FILTERS.get(criterion)
        if clause is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Noma'lum filtr")
        stmt = stmt.where(clause)
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = (
        await db.execute(stmt.order_by(StudentStaff.full_name).limit(page.page_size).offset(page.offset))
    ).all()
    return build_page([_row_out(row, person) for row, person in rows], total or 0, page)


async def _latest_day(db: AsyncSession) -> date_type | None:
    return await db.scalar(select(func.max(DailyPersonCriteria.day)))


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/natijalar/export.xlsx")
async def export_results(
    request: Request,
    db: Db,
    user: Annotated[CurrentUser, Depends(require_permission("exportData"))],
    day: date_type | None = None,
    person_type: Annotated[str | None, Query(alias="type", pattern="^(talaba|xodim)$")] = None,
) -> Response:
    """Kun natijalari Excel'da (shaxsiy ma'lumot — exportData huquqi)."""
    import asyncio

    from app.services.video_analysis_export import build_criteria_workbook

    target = day or await _latest_day(db)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hali tahlil natijasi yo'q")
    stmt = (
        select(DailyPersonCriteria, StudentStaff)
        .join(StudentStaff, StudentStaff.id == DailyPersonCriteria.student_staff_id)
        .where(DailyPersonCriteria.day == target)
    )
    if person_type:
        stmt = stmt.where(StudentStaff.type == person_type)
    rows = [(row, person) for row, person in (await db.execute(stmt)).all()]
    suffix = {"talaba": " (talabalar)", "xodim": " (xodimlar)"}.get(person_type or "", "")
    names = await _camera_names(db, [row for row, _person in rows])
    content = await asyncio.to_thread(build_criteria_workbook, target, rows, title_suffix=suffix, camera_names=names)
    await log_action(db, request, user.id, f"Video tahlil natijalari eksport qilindi: {target.isoformat()}", "Video tahlil")
    await db.commit()
    return Response(
        content=content,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="kunlik-tahlil-{target.isoformat()}.xlsx"'},
    )


@router.get("/natijalar/xulosa", response_model=CriteriaSummaryOut)
async def results_summary(db: Db, _: Reader, day: date_type | None = None) -> CriteriaSummaryOut:
    target = day or await _latest_day(db) or business_today()
    d = DailyPersonCriteria
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(d.attendance_status.in_(("keldi", "kech_keldi"))),
                func.count().filter(d.attendance_status == "kech_keldi"),
                func.count().filter(d.attendance_status == "kelmadi"),
                func.count().filter(d.early_leave == "erta_ketdi"),
                func.coalesce(func.sum(d.lessons_late), 0),
                func.coalesce(func.sum(d.lessons_left_early), 0),
                func.avg(d.attention_score),
                func.count().filter(d.coat_status == "kiygan"),
                func.count().filter(d.coat_status == "kiymagan"),
                func.count().filter(d.coat_status == "aniqlanmadi"),
                func.coalesce(func.sum(d.smoking_events), 0),
                func.coalesce(func.sum(d.teacher_on_time), 0),
                func.coalesce(func.sum(d.teacher_late), 0),
                func.coalesce(func.sum(d.teacher_absent), 0),
                func.avg(d.teacher_activity),
            ).where(d.day == target)
        )
    ).one()
    run = (
        await db.execute(
            select(VideoAnalysisRun).where(VideoAnalysisRun.day == target).order_by(VideoAnalysisRun.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    return CriteriaSummaryOut(
        day=target.isoformat(),
        people=row[0],
        present=row[1],
        late=row[2],
        absent=row[3],
        early_leave=row[4],
        lessons_late=int(row[5]),
        lessons_left_early=int(row[6]),
        attention_avg=round(float(row[7])) if row[7] is not None else None,
        coat_yes=row[8],
        coat_no=row[9],
        coat_unknown=row[10],
        smoking=int(row[11]),
        teacher_on_time=int(row[12]),
        teacher_late=int(row[13]),
        teacher_absent=int(row[14]),
        teacher_activity_avg=round(float(row[15])) if row[15] is not None else None,
        run=run_out(run) if run else None,
    )


@router.get("/natijalar/odam/{person_id}", response_model=list[DailyCriteriaRowOut])
async def person_results(
    person_id: uuid.UUID,
    db: Db,
    _: Reader,
    date_from: Annotated[date_type | None, Query(alias="from")] = None,
    date_to: Annotated[date_type | None, Query(alias="to")] = None,
) -> list[DailyCriteriaRowOut]:
    person = await db.get(StudentStaff, person_id)
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Odam topilmadi")
    end = date_to or business_today()
    start = date_from or end - timedelta(days=30)
    rows = (
        await db.execute(
            select(DailyPersonCriteria)
            .where(
                DailyPersonCriteria.student_staff_id == person_id,
                DailyPersonCriteria.day >= start,
                DailyPersonCriteria.day <= end,
            )
            .order_by(DailyPersonCriteria.day.desc())
        )
    ).scalars().all()
    names = await _camera_names(db, list(rows))
    return [_row_out(row, person, names) for row in rows]


# ── NVR ─────────────────────────────────────────────────────────────────


async def _nvr_out(db: AsyncSession, nvr: NvrDevice) -> NvrOut:
    cameras = await db.scalar(select(func.count()).select_from(Camera).where(Camera.nvr_id == nvr.id))
    return NvrOut(
        id=str(nvr.id),
        name=nvr.name,
        kind=nvr.kind,
        ip=nvr.ip,
        http_port=nvr.http_port,
        rtsp_port=nvr.rtsp_port,
        username=nvr.username,
        has_password=bool(nvr.password),
        stream=nvr.stream,
        fetch_mode=nvr.fetch_mode,
        max_streams=nvr.max_streams,
        local_time=nvr.local_time,
        rtsp_path_template=nvr.rtsp_path_template,
        base_path=nvr.base_path,
        enabled=nvr.enabled,
        last_check_at=_iso(nvr.last_check_at),
        last_error=nvr.last_error,
        channel_count=nvr.channel_count,
        cameras=cameras or 0,
    )


def _validate_nvr(kind: str, ip: str | None, base_path: str | None) -> None:
    if kind == "hikvision" and not (ip or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "NVR IP manzili kerak")
    if kind == "fayl" and not (base_path or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Yozuvlar papkasi kerak")


@router.get("/nvr", response_model=list[NvrOut])
async def list_nvrs(db: Db, _: Admin) -> list[NvrOut]:
    nvrs = (await db.execute(select(NvrDevice).order_by(NvrDevice.name))).scalars().all()
    return [await _nvr_out(db, nvr) for nvr in nvrs]


@router.post("/nvr", response_model=NvrOut, status_code=status.HTTP_201_CREATED)
async def create_nvr(body: NvrIn, request: Request, db: Db, user: Admin) -> NvrOut:
    _validate_nvr(body.kind, body.ip, body.base_path)
    nvr = NvrDevice(
        name=body.name.strip(),
        kind=body.kind,
        ip=(body.ip or "").strip() or None,
        http_port=body.http_port,
        rtsp_port=body.rtsp_port,
        username=(body.username or "").strip() or None,
        password=encrypt(body.password) if body.password else None,
        stream=body.stream,
        fetch_mode=body.fetch_mode,
        max_streams=body.max_streams,
        local_time=body.local_time,
        base_path=(body.base_path or "").strip() or None,
        enabled=body.enabled,
    )
    if body.rtsp_path_template:
        nvr.rtsp_path_template = body.rtsp_path_template.strip()
    db.add(nvr)
    await db.commit()
    await log_action(db, request, user.id, f"NVR qo'shildi: {nvr.name}", "Video tahlil")
    await db.commit()
    return await _nvr_out(db, nvr)


async def _get_nvr(db: AsyncSession, nvr_id: uuid.UUID) -> NvrDevice:
    nvr = await db.get(NvrDevice, nvr_id)
    if nvr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "NVR topilmadi")
    return nvr


@router.patch("/nvr/{nvr_id}", response_model=NvrOut)
async def update_nvr(nvr_id: uuid.UUID, body: NvrPatch, request: Request, db: Db, user: Admin) -> NvrOut:
    nvr = await _get_nvr(db, nvr_id)
    data = body.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    for field, value in data.items():
        if isinstance(value, str):
            value = value.strip() or None
        if field in ("name", "rtsp_path_template") and value is None:
            continue
        setattr(nvr, field, value)
    if password:
        nvr.password = encrypt(password)
    _validate_nvr(nvr.kind, nvr.ip, nvr.base_path)
    await db.commit()
    await log_action(db, request, user.id, f"NVR o'zgartirildi: {nvr.name}", "Video tahlil")
    await db.commit()
    return await _nvr_out(db, nvr)


@router.delete("/nvr/{nvr_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_nvr(nvr_id: uuid.UUID, request: Request, db: Db, user: Admin) -> None:
    nvr = await _get_nvr(db, nvr_id)
    name = nvr.name
    # Kameralar bog'lanishi ham olib tashlanadi (FK SET NULL faqat nvr_id ga).
    for camera in (await db.execute(select(Camera).where(Camera.nvr_id == nvr.id))).scalars().unique():
        camera.nvr_id = None
        camera.nvr_channel = None
    await db.delete(nvr)
    await db.commit()
    await log_action(db, request, user.id, f"NVR o'chirildi: {name}", "Video tahlil")
    await db.commit()


async def _channels(nvr: NvrDevice):
    from app.services.nvr.isapi import NvrChannel

    if nvr.kind == "fayl":
        from pathlib import Path

        base = Path(nvr.base_path or "")
        if not base.is_dir():
            raise NvrError(f"Papka topilmadi: {base}")
        return [
            NvrChannel(channel=int(path.name), name=f"Papka {path.name}", ip=None, online=True)
            for path in sorted(base.iterdir(), key=lambda p: p.name)
            if path.is_dir() and path.name.isdigit()
        ]
    return await isapi_for(nvr).list_channels()


@router.post("/nvr/{nvr_id}/tekshirish", response_model=NvrTestOut)
async def test_nvr(nvr_id: uuid.UUID, db: Db, _: Admin) -> NvrTestOut:
    nvr = await _get_nvr(db, nvr_id)
    nvr.last_check_at = datetime.now(timezone.utc)
    try:
        model = None
        if nvr.kind == "hikvision":
            info = await isapi_for(nvr).device_info()
            model = info.get("model")
        channels = await _channels(nvr)
    except NvrError as exc:
        nvr.last_error = str(exc)
        await db.commit()
        return NvrTestOut(ok=False, message=str(exc))
    nvr.last_error = None
    nvr.channel_count = len(channels)
    await db.commit()
    return NvrTestOut(ok=True, message=f"Ulanildi: {len(channels)} ta kanal", model=model, channels=len(channels))


@router.get("/nvr/{nvr_id}/kanallar", response_model=list[NvrChannelOut])
async def nvr_channels(nvr_id: uuid.UUID, db: Db, _: Admin) -> list[NvrChannelOut]:
    nvr = await _get_nvr(db, nvr_id)
    try:
        channels = await _channels(nvr)
    except NvrError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    mapped = {
        camera.nvr_channel: camera
        for camera in (await db.execute(select(Camera).where(Camera.nvr_id == nvr.id))).scalars().unique()
    }
    return [
        NvrChannelOut(
            channel=channel.channel,
            name=channel.name,
            ip=channel.ip,
            online=channel.online,
            camera_id=str(mapped[channel.channel].id) if channel.channel in mapped else None,
            camera_name=mapped[channel.channel].name if channel.channel in mapped else None,
        )
        for channel in channels
    ]


@router.post("/nvr/{nvr_id}/avto-boglash", response_model=AutoMapOut)
async def auto_map(nvr_id: uuid.UUID, request: Request, db: Db, user: Admin) -> AutoMapOut:
    """NVR kanallarini tizimdagi kameralarga IP manzil bo'yicha bog'laydi
    (topilmasa — nom bo'yicha aynan moslik)."""
    nvr = await _get_nvr(db, nvr_id)
    try:
        channels = await _channels(nvr)
    except NvrError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    cameras = (await db.execute(select(Camera))).scalars().unique().all()
    by_ip = {camera.ip.strip(): camera for camera in cameras if camera.ip}
    by_name = {camera.name.strip().lower(): camera for camera in cameras}
    mapped = 0
    unmatched: list[int] = []
    for channel in channels:
        camera = by_ip.get((channel.ip or "").strip()) if channel.ip else None
        if camera is None:
            camera = by_name.get(channel.name.strip().lower())
        if camera is None:
            unmatched.append(channel.channel)
            continue
        camera.nvr_id = nvr.id
        camera.nvr_channel = channel.channel
        mapped += 1
    await db.commit()
    unmapped = await db.scalar(select(func.count()).select_from(Camera).where(Camera.nvr_id.is_(None)))
    await log_action(db, request, user.id, f"NVR kanallari bog'landi: {nvr.name} ({mapped})", "Video tahlil")
    await db.commit()
    return AutoMapOut(mapped=mapped, unmatched_channels=unmatched, unmapped_cameras=unmapped or 0)


@router.put("/kameralar/{camera_id}/nvr", status_code=status.HTTP_204_NO_CONTENT)
async def set_camera_nvr(camera_id: uuid.UUID, body: CameraNvrIn, db: Db, _: Admin) -> None:
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")
    if body.nvr_id is None:
        camera.nvr_id, camera.nvr_channel = None, None
    else:
        nvr = await _get_nvr(db, uuid.UUID(body.nvr_id))
        if body.channel is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Kanal raqami kerak")
        camera.nvr_id, camera.nvr_channel = nvr.id, body.channel
    await db.commit()
