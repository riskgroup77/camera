"""Davomat va tizim sog'ligi diagnostikasi — faqat O'QIYDI.

Shaxsiy ma'lumot chiqarmaydi: ism, JSHSHIR, pasport yo'q — faqat sanoqlar,
kamera nomlari va vaqtlar.

Serverda:
    cd /opt/camera/camera-api
    docker compose -f docker-compose.yml -f docker-compose.override.yml \
        exec -T api python scripts/attendance_diagnostics.py

Javob beradigan savollar:
  1. Deploy o'tdimi — migratsiya boshi, modullar holati, qavat qamrovi.
  2. AI sweep'lar tirikmi — oxirgi ishga tushish vaqtlari, xatolar.
  3. Davomat yozilyaptimi — 14 kunlik kesim, check-in/check-out qamrovi.
  4. Yozilmasa QAYERDA uzilyapti — ro'yxatdan o'tganlar (biometrika),
     kamera kadr beryaptimi, yuz ko'rinyaptimi, o'xshashlik yetyaptimi.
"""

import asyncio
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select, text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AIModuleConfig,
    AttendanceRecord,
    Building,
    Camera,
    LessonAttendance,
    LessonSession,
    PresenceVisit,
    StudentStaff,
)
from app.timezone import local_now  # noqa: E402

DAYS = 14


def ago(moment: datetime | None) -> str:
    if moment is None:
        return "-"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    minutes = (datetime.now(timezone.utc) - moment).total_seconds() / 60
    if minutes < 90:
        return f"{minutes:.0f} daq oldin"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f} soat oldin"
    return f"{hours / 24:.1f} kun oldin"


def section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


async def deploy_state(db) -> None:
    section("1. DEPLOY HOLATI")
    version = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
    print(f"Migratsiya boshi: {version}")

    modules = (
        await db.execute(
            select(AIModuleConfig.code, AIModuleConfig.name, AIModuleConfig.active, AIModuleConfig.mode)
            .order_by(AIModuleConfig.code)
        )
    ).all()
    working = [f"#{c}" for c, _n, a, m in modules if a and m == "ishchi"]
    trial = [f"#{c}" for c, _n, a, m in modules if a and m == "sinov"]
    off = [f"#{c}" for c, _n, a, _m in modules if not a]
    print(f"Ishchi modullar ({len(working)}): {', '.join(working) or '-'}")
    print(f"Sinov modullari ({len(trial)}): {', '.join(trial) or '-'}")
    print(f"O'chirilgan ({len(off)}): {', '.join(off) or '-'}")

    cameras_total = (await db.scalar(select(func.count()).select_from(Camera))) or 0
    with_floor = (await db.scalar(select(func.count()).select_from(Camera).where(Camera.floor.isnot(None)))) or 0
    no_building = (await db.scalar(select(func.count()).select_from(Camera).where(Camera.building_id.is_(None)))) or 0
    buildings = (await db.execute(select(Building.name, Building.floors).order_by(Building.sort_order, Building.name))).all()
    print(f"\nKameralar: {cameras_total} ta; qavati belgilangan {with_floor}, belgilanmagan {cameras_total - with_floor}")
    print(f"Binoga biriktirilmagan kameralar: {no_building}")
    for name, floors in buildings:
        print(f"  {name[:40]} — qavatlar soni: {floors if floors is not None else 'kiritilmagan'}")

    lock = (
        await db.scalar(
            text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = 1444344025")
        )
    ) or 0
    print(f"\nAI leader qulfi ushlanganmi: {'ha' if lock else 'YOQ (sweep ishlamayapti!)'}")


async def sweep_state() -> None:
    section("2. AI SWEEP HOLATI (oxirgi ishga tushishlar)")
    try:
        from app.services.runtime_snapshot import load_sweep_stats

        stats = await load_sweep_stats()
    except Exception as exc:  # pragma: no cover - diagnostika
        print(f"Sweep statistikasi o'qilmadi: {exc}")
        return
    if not stats:
        print("Ma'lumot yo'q — bu jarayon leader emas va Redis'da snapshot yo'q.")
        return
    print("nomi | interval | ishga tushgan | xato | oxirgi tugagan | davomiyligi | natija | holat")
    for row in sorted(stats, key=lambda s: s.name):
        state = "ishlamoqda" if row.running else ("pauza" if row.paused else "kutmoqda")
        print(
            f"{row.name} | {row.interval_seconds}s | {row.runs} | {row.failures} | "
            f"{ago(row.last_finished_at)} | {row.last_duration_seconds:.1f}s | {row.last_result} | {state}"
            + (f" | XATO: {row.last_error[:60]}" if row.last_error else "")
        )


async def enrollment_state(db) -> None:
    section("3. RO'YXAT VA BIOMETRIKA (davomatning maxraji)")
    rows = (
        await db.execute(
            select(StudentStaff.type, StudentStaff.biometrics_status, func.count())
            .group_by(StudentStaff.type, StudentStaff.biometrics_status)
        )
    ).all()
    per_type: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for person_type, status, count in rows:
        per_type[person_type][status] = count
    for person_type, statuses in per_type.items():
        total = sum(statuses.values())
        confirmed = statuses.get("tasdiqlangan", 0)
        print(
            f"{person_type}: jami {total}, tasdiqlangan {confirmed} ({confirmed * 100 // total if total else 0}%), "
            f"kutilmoqda {statuses.get('kutilmoqda', 0)}, yo'q {statuses.get('yoq', 0)}"
        )
    with_embedding = (
        await db.scalar(select(func.count()).select_from(StudentStaff).where(StudentStaff.biometric_embedding.isnot(None)))
    ) or 0
    print(f"Yuz vektori saqlangan: {with_embedding} ta odam — AI faqat shularni taniy oladi.")


async def attendance_state(db) -> None:
    section(f"4. DAVOMAT YOZUVLARI (oxirgi {DAYS} kun)")
    today = local_now().date()
    since = today - timedelta(days=DAYS - 1)
    rows = (
        await db.execute(
            select(
                AttendanceRecord.date,
                func.count(),
                func.count().filter(AttendanceRecord.status == "keldi"),
                func.count().filter(AttendanceRecord.status == "kech_keldi"),
                func.count().filter(AttendanceRecord.status == "kelmadi"),
                func.count().filter(AttendanceRecord.status == "dam_olish"),
                func.count().filter(AttendanceRecord.check_in.isnot(None)),
                func.count().filter(AttendanceRecord.check_out.isnot(None)),
            )
            .where(AttendanceRecord.date >= since)
            .group_by(AttendanceRecord.date)
            .order_by(AttendanceRecord.date.desc())
        )
    ).all()
    if not rows:
        print(f"{since} dan beri birorta davomat yozuvi yo'q.")
    else:
        print("sana | jami | keldi | kechikdi | kelmadi | dam | check_in bor | check_out bor")
        for date_value, total, came, late, absent, rest, has_in, has_out in rows:
            print(f"{date_value} | {total} | {came} | {late} | {absent} | {rest} | {has_in} | {has_out}")

    first_last = (
        await db.execute(
            select(func.min(AttendanceRecord.date), func.max(AttendanceRecord.date), func.count())
            .select_from(AttendanceRecord)
        )
    ).one()
    print(f"\nButun tarix: {first_last[2]} qator, {first_last[0]} dan {first_last[1]} gacha")

    earliest = (
        await db.execute(
            select(func.min(AttendanceRecord.check_in), func.max(AttendanceRecord.check_in))
            .where(AttendanceRecord.date == today)
        )
    ).one()
    print(f"Bugun ({today}) birinchi check_in {earliest[0]}, oxirgisi {earliest[1]}")


async def presence_state(db) -> None:
    section("5. TASHRIFLAR (PresenceVisit — har yuz tanish shu yerga tushadi)")
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)
    per_day = (
        await db.execute(
            select(
                func.date(func.timezone("Asia/Tashkent", PresenceVisit.first_seen_at)).label("day"),
                func.count(),
                func.count(func.distinct(PresenceVisit.student_staff_id)),
                func.count(func.distinct(PresenceVisit.camera_id)),
            )
            .where(PresenceVisit.first_seen_at >= since)
            .group_by(text("1"))
            .order_by(text("1 DESC"))
        )
    ).all()
    if not per_day:
        print("Oxirgi 7 kunda birorta tashrif yozilmagan — ya'ni AI hech kimni tanimayapti.")
    else:
        print("sana | tashriflar | turli odam | turli kamera")
        for day, visits, people, cameras in per_day:
            print(f"{day} | {visits} | {people} | {cameras}")

    # Bugungi tanishlar soat kesimida — "o'zgarish qachon boshlandi" degan
    # savolga aniq javob beradi (masalan sozlama o'zgargan yoki konteyner
    # qayta ishga tushgan payt).
    start_of_today = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
    hourly = (
        await db.execute(
            select(
                func.extract("hour", func.timezone("Asia/Tashkent", PresenceVisit.first_seen_at)),
                func.count(),
                func.count(func.distinct(PresenceVisit.student_staff_id)),
            )
            .where(PresenceVisit.first_seen_at >= start_of_today)
            .group_by(text("1"))
            .order_by(text("1"))
        )
    ).all()
    if hourly:
        print()
        print("Bugun soat kesimida (soat | tashrif | turli odam):")
        for hour, visits, people in hourly:
            print(f"{int(hour):02d}:00 | {visits} | {people}")

    top = (
        await db.execute(
            select(Camera.name, func.count(), func.count(func.distinct(PresenceVisit.student_staff_id)))
            .select_from(PresenceVisit)
            .join(Camera, Camera.id == PresenceVisit.camera_id)
            .where(PresenceVisit.first_seen_at >= since)
            .group_by(Camera.name)
            .order_by(func.count().desc())
            .limit(10)
        )
    ).all()
    if top:
        print("\nEng ko'p tanigan kameralar (7 kun): tashrif | turli odam | kamera")
        for name, visits, people in top:
            print(f"{visits} | {people} | {name[:45]}")


async def camera_state(db) -> None:
    section("6. KIRISH/CHIQISH KAMERALARI (davomat faqat shularga tayanadi)")
    cameras = (
        await db.execute(
            select(Camera)
            .where((Camera.is_entrance.is_(True)) | (Camera.is_exit.is_(True)) | (Camera.is_perimeter.is_(True)))
            .order_by(Camera.name)
        )
    ).scalars().all()
    if not cameras:
        print("Kirish/chiqish deb belgilangan kamera YO'Q — davomat sweepi burst kadr olmaydi.")
    else:
        print("kamera | rol | holat | oxirgi javob | oxirgi kadr | qavat")
        for camera in cameras:
            roles = ",".join(
                role
                for role, flag in (("kirish", camera.is_entrance), ("chiqish", camera.is_exit), ("perimetr", camera.is_perimeter))
                if flag
            )
            print(
                f"{camera.name[:35]} | {roles} | {camera.status} | {ago(camera.last_seen_at)} | "
                f"{ago(camera.last_frame_at)} | {camera.floor if camera.floor is not None else '-'}"
            )

    total = (await db.scalar(select(func.count()).select_from(Camera))) or 0
    active = (await db.scalar(select(func.count()).select_from(Camera).where(Camera.status == "faol"))) or 0
    fresh_cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.camera_health_freshness_seconds)
    reachable = (
        await db.scalar(
            select(func.count()).select_from(Camera).where(Camera.status == "faol").where(Camera.last_seen_at >= fresh_cutoff)
        )
    ) or 0
    video_cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.camera_video_stale_seconds)
    with_video = (
        await db.scalar(
            select(func.count()).select_from(Camera).where(Camera.status == "faol").where(Camera.last_frame_at >= video_cutoff)
        )
    ) or 0
    print(f"\nJami {total} kamera; faol {active}, javob berayotgan {reachable}, tasvir kelayotgan {with_video}")


async def recognition_state() -> None:
    section("7. YUZ TANISH STATISTIKASI (bugun, kamera kesimida)")
    try:
        from app.services.runtime_snapshot import load_recognition_views

        views = await load_recognition_views()
    except Exception as exc:  # pragma: no cover - diagnostika
        print(f"Statistika o'qilmadi: {exc}")
        return
    if not views:
        print("Ma'lumot yo'q — sweep hali kadr olmagan yoki Redis snapshot bo'sh.")
        return
    print("kamera_id | kadr | yuzli kadr | yuz | kichik yuz | qat'iy | yumshoq | eng yaqin | medial px | oxirgi moslik")
    for camera_id, view in sorted(views.items(), key=lambda item: -item[1].faces):
        print(
            f"{camera_id[:8]} | {view.frames} | {view.frames_with_faces} | {view.faces} | {view.small_faces} | "
            f"{view.strict} | {view.relaxed_confirmed} | "
            f"{view.best_similarity if view.best_similarity >= 0 else '-'} | "
            f"{view.face_px_median if view.face_px_median is not None else '-'} | {ago(view.last_match_at)}"
        )
        if view.buckets:
            print(f"    o'xshashlik taqsimoti: {view.buckets}")


async def lesson_state(db) -> None:
    section("8. DARS DAVOMATI")
    today = local_now().date()
    since = today - timedelta(days=7)
    sessions = (
        await db.execute(
            select(LessonSession.date, func.count(), func.count(LessonSession.camera_id), func.count(LessonSession.teacher_id))
            .where(LessonSession.date >= since)
            .group_by(LessonSession.date)
            .order_by(LessonSession.date.desc())
        )
    ).all()
    if not sessions:
        print("Oxirgi 7 kunda dars jadvali kiritilmagan — #19/#21/#22/#26 tekshiruvi ishlamaydi.")
    else:
        print("sana | darslar | kamerasi bor | o'qituvchisi bog'langan")
        for date_value, total, with_camera, with_teacher in sessions:
            print(f"{date_value} | {total} | {with_camera} | {with_teacher}")
    rows = (await db.scalar(select(func.count()).select_from(LessonAttendance))) or 0
    print(f"Dars davomati qatorlari (jami): {rows}")


def settings_state() -> None:
    section("9. SOZLAMALAR (davomatga ta'sir qiladiganlari)")
    print(f"Yuz mosligi chegarasi (qat'iy): {settings.attendance_ai_match_threshold}")
    print(f"Yumshoq moslik chegarasi: {settings.attendance_ai_relaxed_threshold}")
    print(f"Davomat sweep intervali: {settings.attendance_ai_interval_seconds}s")
    print(f"Ish kunlari: {settings.attendance_working_weekdays}")
    for name in (
        "attendance_relaxed_confirm_window_seconds",
        "presence_visit_gap_minutes",
        "ai_entrance_use_main_stream",
        "ai_global_sweep_concurrency",
        "camera_health_freshness_seconds",
        "camera_video_stale_seconds",
        "trial_events_per_module_hour",
        "thumbnail_refresh_seconds",
    ):
        if hasattr(settings, name):
            print(f"{name}: {getattr(settings, name)}")


async def main() -> None:
    """Har bo'lim alohida himoyalangan: bittasi xato bersa (masalan
    migratsiya hali qo'llanmagan bo'lsa) qolgan tashxis baribir chiqadi."""
    async with SessionLocal() as db:
        sections = (
            ("Deploy holati", lambda: deploy_state(db)),
            ("AI sweep", sweep_state),
            ("Ro'yxat", lambda: enrollment_state(db)),
            ("Davomat", lambda: attendance_state(db)),
            ("Tashriflar", lambda: presence_state(db)),
            ("Kameralar", lambda: camera_state(db)),
            ("Yuz tanish", recognition_state),
            ("Dars davomati", lambda: lesson_state(db)),
        )
        for name, run in sections:
            try:
                await run()
            except Exception as exc:
                print()
                print(f"!!! '{name}' bo'limi xato bilan tugadi: {type(exc).__name__}: {str(exc)[:200]}")
                try:
                    await db.rollback()
                except Exception:
                    pass
    settings_state()
    print()


asyncio.run(main())
