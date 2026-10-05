"""Yozib olingan videolar ustida kunlik tahlil — buyruq qatori.

NVR tarmoqqa ulanmagan yoki sinov uchun alohida videolar bilan ishlash:

  1. Videoni kameraga biriktirib import qilish (vaqt fayl nomidan, video
     metama'lumotidan yoki --boshlanish dan olinadi):

       python scripts/video_tahlil.py import --kamera "Asosiy kirish" kirish_0800.mp4
       python scripts/video_tahlil.py import --kamera "201-xona" --yangi --tur auditoriya \\
           --boshlanish "2026-10-05 08:50" dars.mp4

     Butun papka (yozuv vositasi chiqargan bino/qavat/xona daraxti) — har
     video kameraga ID qo'shimchasi, IP yoki nom bo'yicha bog'lanadi, fayl
     nusxalanmaydi (havola). Avval reja ko'rsatiladi, --qollash yozadi:

       python scripts/video_tahlil.py papka /data/recordings/2026-10-02_10-59-12
       python scripts/video_tahlil.py papka /data/recordings/2026-10-02_10-59-12 --qollash

  2. (Ixtiyoriy) Dars jadvalida bo'lmasa — darsni qo'shish:

       python scripts/video_tahlil.py dars --kamera "201-xona" --kun 2026-10-05 \\
           --vaqt 09:00-10:20 --guruh DI-101 --oqituvchi "Toshmatov"

  3. Kunni tahlil qilish (oyna — shu kungi videolar oralig'i):

       python scripts/video_tahlil.py tahlil --kun 2026-10-05

  4. Excel hisobot:

       python scripts/video_tahlil.py hisobot --kun 2026-10-05 --chiqish natija.xlsx

  holat — import qilingan videolar va kameralar ro'yxati.

Docker'da (server): videolarni /opt/camera/nvr-eksport/ ga ko'chiring va
    docker compose exec ai-worker python scripts/video_tahlil.py import --kamera ... /data/nvr-eksport/video.mp4

DIQQAT: tahlil natijalari haqiqiy jadvallarga (davomat, darslar, hodisalar)
o'sha kun uchun yoziladi — boshqa manbadan (turniket, qo'lda) kelganlari
saqlanadi, kunning oldingi video natijalari esa yangisi bilan almashadi.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Camera,
    DailyPersonCriteria,
    LessonSession,
    NvrDevice,
    StudentStaff,
    VideoAnalysisJob,
    VideoAnalysisRun,
)
from app.timezone import INSTITUTE_TZ  # noqa: E402

IMPORT_NVR_NAME = "Yuklangan videolar"
ROOM_TYPES = ("kirish", "auditoriya", "laboratoriya", "koridor", "ofis", "cheklangan", "tashqi")
_STAMP = re.compile(r"(20\d{2})(\d{2})(\d{2})[_T-]?(\d{2})(\d{2})(\d{2})")


def import_dir() -> Path:
    return Path(os.environ.get("VIDEO_IMPORT_DIR") or settings.video_import_dir).resolve()


def parse_moment(text: str) -> datetime:
    """"2026-10-05 08:50", "2026-10-05T08:50:30" — institut soatida."""
    value = text.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=INSTITUTE_TZ)
        except ValueError:
            continue
    raise SystemExit(f"Vaqt formati noto'g'ri: {text!r} (kerak: YYYY-MM-DD HH:MM[:SS])")


def stamp_from_name(name: str) -> datetime | None:
    """Fayl nomidagi vaqt: 20261005_085000, 20261005085000, ch01_20261005085000_..."""
    match = _STAMP.search(name)
    if not match:
        return None
    try:
        return datetime(*(int(g) for g in match.groups()), tzinfo=INSTITUTE_TZ)
    except ValueError:
        return None


def probe(path: Path) -> tuple[float | None, datetime | None]:
    """(davomiyligi, soniya; yozilgan vaqti — metama'lumotda bo'lsa)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags=creation_time", "-of", "json",
             str(path)],
            capture_output=True, text=True, check=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"ffprobe faylni o'qiy olmadi: {path} ({exc})") from exc
    data = json.loads(out).get("format", {})
    duration = float(data["duration"]) if data.get("duration") else None
    created = (data.get("tags") or {}).get("creation_time")
    moment = None
    if created:
        try:
            moment = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(INSTITUTE_TZ)
        except ValueError:
            moment = None
    return duration, moment


async def _import_nvr(db) -> NvrDevice:
    base = import_dir()
    nvr = (await db.execute(select(NvrDevice).where(NvrDevice.name == IMPORT_NVR_NAME))).scalar_one_or_none()
    if nvr is None:
        nvr = NvrDevice(name=IMPORT_NVR_NAME, kind="fayl", base_path=str(base), max_streams=4, enabled=True)
        db.add(nvr)
        await db.flush()
        print(f"+ NVR yaratildi: «{IMPORT_NVR_NAME}» -> {base}")
    elif nvr.base_path != str(base):
        nvr.base_path = str(base)
    return nvr


async def _camera(db, name: str, *, create: bool, room_type: str | None) -> Camera:
    camera = (
        await db.execute(select(Camera).where(func.lower(Camera.name) == name.strip().lower()))
    ).scalars().unique().first()
    if camera is None:
        if not create:
            names = (await db.execute(select(Camera.name).order_by(Camera.name))).scalars().all()
            hint = ", ".join(names[:15]) + (" ..." if len(names) > 15 else "")
            raise SystemExit(f"Kamera topilmadi: {name!r}. Yangisini yaratish: --yangi --tur <turi>. Mavjudlar: {hint}")
        camera = Camera(name=name.strip(), ip="video-import", zone="Video", resolution="", status="faol",
                        room_type=room_type, is_entrance=room_type == "kirish")
        db.add(camera)
        await db.flush()
        print(f"+ Kamera yaratildi: «{camera.name}» (turi: {room_type or 'belgilanmagan'})")
    elif room_type and camera.room_type != room_type:
        camera.room_type = room_type
        print(f"~ «{camera.name}» turi: {room_type}")
    if camera.status != "faol":
        camera.status = "faol"
    return camera


async def _channel_for(db, nvr: NvrDevice, camera: Camera) -> int:
    """Kameraning import NVR'idagi kanali (yo'q bo'lsa — keyingi bo'sh raqam)."""
    if camera.nvr_id == nvr.id and camera.nvr_channel:
        return camera.nvr_channel
    if camera.nvr_id and camera.nvr_id != nvr.id:
        print(f"! «{camera.name}» boshqa NVR'dan yuklangan videolarga o'tkazildi")
    used = (await db.execute(select(func.max(Camera.nvr_channel)).where(Camera.nvr_id == nvr.id))).scalar()
    camera.nvr_id, camera.nvr_channel = nvr.id, (used or 0) + 1
    await db.flush()
    return camera.nvr_channel


def _place(path: Path, target: Path, mode: str) -> None:
    """mode: nusxa | kochirish | havola. Havola — 40 GB yozuvni nusxalamaslik
    uchun (ffmpeg va FolderSource havolani oddiy fayl kabi o'qiydi)."""
    if target.resolve() == path.resolve():
        return
    if mode == "kochirish":
        shutil.move(str(path), target)
    elif mode == "havola":
        if target.is_symlink() or target.exists():
            target.unlink()
        try:
            target.symlink_to(path.resolve())
        except OSError:
            # Windows'da ramziy havola huquq talab qiladi — qattiq havola (bir disk).
            os.link(path.resolve(), target)
    else:
        shutil.copy2(path, target)


def _target(nvr: NvrDevice, channel: int, path: Path, start: datetime) -> Path:
    target_dir = Path(nvr.base_path) / str(channel)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{start.strftime('%Y%m%d_%H%M%S')}{path.suffix.lower() or '.mp4'}"


async def cmd_import(args) -> None:
    files = [Path(p) for p in args.fayllar]
    for path in files:
        if not path.is_file():
            raise SystemExit(f"Fayl topilmadi: {path}")
    if args.boshlanish and len(files) > 1:
        raise SystemExit("--boshlanish faqat bitta fayl uchun; bir nechta faylda vaqt fayl nomidan olinadi")
    if args.tur and args.tur not in ROOM_TYPES:
        raise SystemExit(f"--tur quyidagilardan biri: {', '.join(ROOM_TYPES)}")
    async with SessionLocal() as db:
        nvr = await _import_nvr(db)
        camera = await _camera(db, args.kamera, create=args.yangi, room_type=args.tur)
        channel = await _channel_for(db, nvr, camera)
        for path in files:
            duration, meta_moment = probe(path)
            start = parse_moment(args.boshlanish) if args.boshlanish else stamp_from_name(path.name) or meta_moment
            if start is None:
                raise SystemExit(
                    f"{path.name}: yozilgan vaqti aniqlanmadi — --boshlanish \"YYYY-MM-DD HH:MM\" bilan bering"
                )
            if not duration:
                raise SystemExit(f"{path.name}: video davomiyligi aniqlanmadi (buzilgan fayl?)")
            _place(path, _target(nvr, channel, path, start), "kochirish" if args.kochirish else "nusxa")
            end = start + timedelta(seconds=duration)
            print(f"✓ {path.name} -> kanal {channel}: {start:%Y-%m-%d %H:%M:%S} – {end:%H:%M:%S} "
                  f"({duration / 60:.1f} daqiqa)")
        await db.commit()
    print(f"Kamera «{camera.name}» -> «{IMPORT_NVR_NAME}», kanal {channel}.")


VIDEO_SUFFIXES = (".mp4", ".mkv", ".avi", ".mov", ".ts")
_IP = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
# Yozuv vositasi fayl nomi oxiriga kamera ID'sining birinchi 8 belgisini qo'shadi.
_ID_SUFFIX = re.compile(r"_+([0-9a-f]{8})$")


def _norm(text: str) -> str:
    """Nomni solishtirish uchun: kichik harf, faqat harf va raqam
    ("O'ng tomon kamera" == "O-ng-tomon-kamera")."""
    return re.sub(r"[\W_]+", "", text.lower())


def match_camera(path: Path, cameras: list) -> tuple[object | None, str]:
    """Videoni kameraga bog'laydi: ID qo'shimchasi, IP, nom — shu tartibda.
    Qaytaradi — (kamera yoki None, qanday topilgani / nega topilmagani)."""
    stem = path.stem
    suffix = _ID_SUFFIX.search(stem)
    if suffix:
        found = [c for c in cameras if str(c.id).replace("-", "").startswith(suffix.group(1))]
        if len(found) == 1:
            return found[0], "ID"
    ip = _IP.search(stem)
    if ip:
        found = [c for c in cameras if (c.ip or "").strip() == ip.group(1)]
        if len(found) == 1:
            return found[0], "IP"
    name = _norm(_ID_SUFFIX.sub("", stem))
    found = [c for c in cameras if _norm(c.name) == name] if name else []
    if len(found) == 1:
        return found[0], "nom"
    if len(found) > 1:
        return None, f"nom bo'yicha {len(found)} ta kamera"
    return None, "kamera topilmadi"


def start_of(path: Path, duration: float, meta_moment: datetime | None) -> tuple[datetime, str]:
    """Video boshlangan payt: fayl nomidan, metama'lumotdan, bo'lmasa
    fayl oxirgi yozilgan vaqtidan (yozuv tugagan payt) minus davomiylik."""
    stamp = stamp_from_name(path.name)
    if stamp is not None:
        return stamp, "nom"
    if meta_moment is not None:
        return meta_moment, "metama'lumot"
    ended = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone(INSTITUTE_TZ)
    return (ended - timedelta(seconds=duration)).replace(microsecond=0), "fayl vaqti"


async def cmd_folder(args) -> None:
    """Papkadagi barcha videolarni kameralarga bog'lash (yozuv vositasi
    chiqargan bino/qavat/xona daraxti). Standart — faqat reja; --qollash yozadi."""
    base = Path(args.papka)
    if not base.is_dir():
        raise SystemExit(f"Papka topilmadi: {base}")
    files = sorted(p for p in base.rglob("*") if p.suffix.lower() in VIDEO_SUFFIXES and p.is_file())
    if not files:
        raise SystemExit(f"{base} ichida video yo'q")
    async with SessionLocal() as db:
        cameras = list((await db.execute(select(Camera))).scalars().unique())
        nvr = await _import_nvr(db) if args.qollash else None
        placed, skipped = 0, []
        for path in files:
            camera, how = match_camera(path, cameras)
            if camera is None:
                skipped.append(f"{path.relative_to(base)} — {how}")
                continue
            duration, meta_moment = probe(path)
            if not duration or duration < args.eng_kam:
                skipped.append(f"{path.relative_to(base)} — video juda qisqa yoki buzilgan ({duration or 0:.0f} s)")
                continue
            start, source = start_of(path, duration, meta_moment)
            end = start + timedelta(seconds=duration)
            line = (f"{path.name} -> «{camera.name}» ({how}, turi: {camera.room_type or '—'}): "
                    f"{start:%Y-%m-%d %H:%M:%S} – {end:%H:%M:%S} ({duration / 60:.1f} daq, vaqt: {source})")
            if args.qollash:
                channel = await _channel_for(db, nvr, camera)
                _place(path, _target(nvr, channel, path, start), args.usul)
                line += f", kanal {channel}"
            print(("✓ " if args.qollash else "  ") + line)
            placed += 1
        if args.qollash:
            await db.commit()
    verb = "bog'landi" if args.qollash else "bog'lanadi"
    print(f"\n{placed} ta video {verb}, {len(skipped)} tasi o'tkazib yuborildi.")
    for item in skipped:
        print(f"  ! {item}")
    if not args.qollash:
        print("Bu faqat reja. Yozish uchun: --qollash")


async def cmd_lesson(args) -> None:
    day = date.fromisoformat(args.kun)
    try:
        begin, finish = (time.fromisoformat(part.strip()) for part in args.vaqt.split("-"))
    except ValueError as exc:
        raise SystemExit("--vaqt formati: HH:MM-HH:MM") from exc
    async with SessionLocal() as db:
        camera = await _camera(db, args.kamera, create=False, room_type=None)
        teacher = None
        if args.oqituvchi:
            matches = (
                await db.execute(
                    select(StudentStaff).where(StudentStaff.type == "xodim",
                                               StudentStaff.full_name.ilike(f"%{args.oqituvchi.strip()}%"))
                )
            ).scalars().all()
            if len(matches) > 1:
                names = ", ".join(m.full_name for m in matches[:10])
                raise SystemExit(f"O'qituvchi nomi aniq emas ({len(matches)} ta): {names}")
            teacher = matches[0] if matches else None
            if teacher is None:
                print(f"! O'qituvchi topilmadi: {args.oqituvchi!r} — dars o'qituvchisiz qo'shiladi")
        roster = await db.scalar(
            select(func.count()).select_from(StudentStaff).where(
                StudentStaff.type == "talaba",
                (StudentStaff.group_or_position == args.guruh) | StudentStaff.group_or_position.like(f"%, {args.guruh}"),
            )
        )
        lesson = LessonSession(
            date=day,
            group_name=args.guruh,
            faculty=args.fakultet or "",
            teacher=teacher.full_name if teacher else (args.oqituvchi or ""),
            subject=args.fan or "Sinov darsi",
            teacher_id=teacher.id if teacher else None,
            camera_id=camera.id,
            scheduled_start_time=datetime.combine(day, begin, tzinfo=INSTITUTE_TZ),
            scheduled_end_time=datetime.combine(day, finish, tzinfo=INSTITUTE_TZ),
        )
        db.add(lesson)
        await db.commit()
    print(f"✓ Dars qo'shildi: {day} {begin:%H:%M}-{finish:%H:%M}, {args.guruh} ({roster or 0} talaba), "
          f"xona kamerasi «{camera.name}», o'qituvchi: {teacher.full_name if teacher else '—'}")


async def _day_window(day: date) -> tuple[datetime, datetime] | None:
    """Shu kungi import qilingan videolar oralig'i (barcha kanallar)."""
    from app.services.nvr.sources import FolderSource

    base = import_dir()
    if not base.is_dir():
        return None
    starts, ends = [], []
    for channel_dir in base.iterdir():
        if not channel_dir.is_dir() or not channel_dir.name.isdigit():
            continue
        for recording in await FolderSource(str(base), int(channel_dir.name)).files():
            local = recording.start.astimezone(INSTITUTE_TZ)
            if local.date() == day:
                starts.append(recording.start)
                ends.append(recording.end)
    if not starts:
        return None
    return min(starts), max(ends)


async def cmd_analyze(args) -> None:
    from app.jobs.video_analysis import RunExecutor, analysis_window, create_run

    day = date.fromisoformat(args.kun)
    if getattr(args, "hamma_joyda", False):
        # Kamera turi belgilanmagan bo'lsa ham hamma kriteriyalar hamma kamerada.
        settings.video_analysis_everywhere = True
    if getattr(args, "kadr", None):
        # Kirish kameralari: soniyasiga nechta kadr (standart 1, tig'iz soatda 2).
        # Kam kadr — tezroq, lekin eshikdan tez o'tgan odam o'tkazib yuborilishi mumkin.
        settings.video_analysis_entrance_fps = args.kadr
        settings.video_analysis_entrance_peak_fps = args.kadr
    if args.oyna:
        try:
            begin, finish = (time.fromisoformat(part.strip()) for part in args.oyna.split("-"))
        except ValueError as exc:
            raise SystemExit("--oyna formati: HH:MM-HH:MM") from exc
        window = (datetime.combine(day, begin, tzinfo=INSTITUTE_TZ), datetime.combine(day, finish, tzinfo=INSTITUTE_TZ))
    else:
        window = await _day_window(day)
        if window is None:
            window = analysis_window(day)
            print("! Bu kunga import qilingan video topilmadi — sozlamadagi oyna ishlatiladi (NVR'lar bo'yicha)")
        else:
            # Darslar boshlanish oynasi videodan biroz oldin bo'lishi mumkin.
            window = (window[0] - timedelta(minutes=1), window[1] + timedelta(minutes=1))
    window = (window[0].astimezone(timezone.utc), window[1].astimezone(timezone.utc))
    async with SessionLocal() as db:
        # Yangi bazada AI modullari ilova ishga tushganda yaratiladi — bu
        # yerda ham (idempotent), aks holda kriteriyalar "o'chiq" hisoblanadi.
        from app.seed import seed_all

        await seed_all(db)
    async with SessionLocal() as db:
        from app.jobs.video_analysis import lock_runs

        await lock_runs(db)
        busy = await db.scalar(
            select(func.count()).select_from(VideoAnalysisRun)
            .where(VideoAnalysisRun.status.in_(("navbatda", "ishlamoqda", "agregatsiya")))
        )
        if busy and not args.majburiy:
            raise SystemExit("Boshqa tahlil hali tugamagan (ai-worker bajarmoqda). Kuting yoki --majburiy.")
        run = await create_run(db, day, triggered_by="buyruq", window=window)
        run_id, total, frames = run.id, run.jobs_total, run.frames_planned
    print(f"Tahlil: {day}, oyna {window[0].astimezone(INSTITUTE_TZ):%H:%M:%S}–"
          f"{window[1].astimezone(INSTITUTE_TZ):%H:%M:%S}, {total} vazifa, ~{frames} kadr")
    if total == 0:
        print("! Vazifa yo'q: kamera NVR kanaliga bog'lanmagan, yoki xona kamerasida bu kun dars yo'q "
              "(dars qo'shish: `dars` buyrug'i).")

    async def progress() -> None:
        while True:
            await asyncio.sleep(10)
            async with SessionLocal() as db:
                rows = (
                    await db.execute(
                        select(VideoAnalysisJob.status, func.count(), func.coalesce(func.sum(VideoAnalysisJob.frames), 0))
                        .where(VideoAnalysisJob.run_id == run_id).group_by(VideoAnalysisJob.status)
                    )
                ).all()
            done = sum(c for s, c, _f in rows if s in ("tugadi", "yozuv_yoq", "xato"))
            print(f"  ... {done}/{total} vazifa, {sum(int(f) for *_x, f in rows)} kadr")

    ticker = asyncio.create_task(progress())
    try:
        run = await RunExecutor(run_id, SessionLocal).execute()
    finally:
        ticker.cancel()
    async with SessionLocal() as db:
        problems = (
            await db.execute(
                select(VideoAnalysisJob.kind, VideoAnalysisJob.status, VideoAnalysisJob.error)
                .where(VideoAnalysisJob.run_id == run_id, VideoAnalysisJob.status.in_(("xato", "yozuv_yoq")))
                .limit(10)
            )
        ).all()
    print(f"Holat: {run.status}" + (f" — {run.error}" if run.error else ""))
    for kind, status, error in problems:
        print(f"  ! {kind}: {status} {error or ''}")
    for key, value in (run.stats or {}).items():
        print(f"  {key}: {value}")


async def cmd_report(args) -> None:
    from app.services.video_analysis_export import build_criteria_workbook

    day = date.fromisoformat(args.kun)
    async with SessionLocal() as db:
        stmt = (
            select(DailyPersonCriteria, StudentStaff)
            .join(StudentStaff, StudentStaff.id == DailyPersonCriteria.student_staff_id)
            .where(DailyPersonCriteria.day == day)
        )
        if args.tur:
            stmt = stmt.where(StudentStaff.type == args.tur)
        rows = [(row, person) for row, person in (await db.execute(stmt)).all()]
        camera_names = {str(camera_id): name for camera_id, name in (await db.execute(select(Camera.id, Camera.name))).all()}
    if not rows:
        raise SystemExit(f"{day} uchun natija yo'q — avval `tahlil --kun {day}`")
    out = Path(args.chiqish or f"kunlik-tahlil-{day}.xlsx")
    out.write_bytes(build_criteria_workbook(day, rows, camera_names=camera_names))
    findings = sum(len((row.details or {}).get("dalillar") or []) for row, _person in rows)
    clips = sum(1 for row, _p in rows for item in (row.details or {}).get("dalillar") or [] if item.get("klip"))
    print(f"Aniqlangan holatlar: {findings}, video dalili bor: {clips}")
    if getattr(args, "html", None):
        from app.services.video_analysis_export import build_findings_html
        from app.storage import presigned_url_for

        page = Path(args.html)
        page.write_text(
            build_findings_html(day, rows, camera_names, lambda key: presigned_url_for(key, 7 * 24 * 3600)),
            encoding="utf-8",
        )
        print(f"✓ Holatlar va video dalillar -> {page.resolve()}")
    print(f"✓ {len(rows)} kishi -> {out.resolve()}")
    for row, person in sorted(rows, key=lambda item: item[1].full_name)[: args.korsat]:
        parts = [row.attendance_status or "—"]
        if row.late_minutes:
            parts.append(f"{row.late_minutes} daq kech")
        if row.early_leave == "erta_ketdi":
            parts.append("erta ketdi")
        if row.lessons_total:
            parts.append(f"dars {row.lessons_attended}/{row.lessons_total}")
        if row.attention_score is not None:
            parts.append(f"diqqat {row.attention_score}")
        if row.coat_status and row.coat_status != "talab_yoq":
            parts.append(f"xalat: {row.coat_status}")
        if row.smoking_events:
            parts.append(f"chekish {row.smoking_events}")
        if row.teacher_lessons:
            parts.append(f"o'qituvchi {row.teacher_on_time}/{row.teacher_lessons} vaqtida")
        print(f"  {person.full_name}: " + ", ".join(parts))


async def cmd_status(_args) -> None:
    from app.services.nvr.sources import FolderSource

    base = import_dir()
    print(f"Import papkasi: {base}")
    async with SessionLocal() as db:
        nvr = (await db.execute(select(NvrDevice).where(NvrDevice.name == IMPORT_NVR_NAME))).scalar_one_or_none()
        cameras = (
            (await db.execute(select(Camera).where(Camera.nvr_id == nvr.id).order_by(Camera.nvr_channel))).scalars().unique().all()
            if nvr else []
        )
    if not cameras:
        print("Hali video import qilinmagan.")
        return
    for camera in cameras:
        files = await FolderSource(str(base), camera.nvr_channel).files()
        print(f"Kanal {camera.nvr_channel}: «{camera.name}» (turi: {camera.room_type or '—'}) — {len(files)} ta video")
        for recording in files:
            print(f"    {recording.start.astimezone(INSTITUTE_TZ):%Y-%m-%d %H:%M:%S} – "
                  f"{recording.end.astimezone(INSTITUTE_TZ):%H:%M:%S}  {recording.path.name}")


def main(argv: list[str] | None = None) -> None:
    # Windows konsoli (cp866/cp1251) "✓" yoki "«" ni chiqara olmasa yiqilmasin.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Yozib olingan videolar ustida kunlik tahlil")
    sub = parser.add_subparsers(dest="buyruq", required=True)

    p = sub.add_parser("import", help="Videoni kameraga biriktirib import qilish")
    p.add_argument("fayllar", nargs="+")
    p.add_argument("--kamera", required=True, help="Tizimdagi kamera nomi")
    p.add_argument("--boshlanish", help="Video boshlangan payt: \"YYYY-MM-DD HH:MM[:SS]\" (institut soati)")
    p.add_argument("--yangi", action="store_true", help="Kamera bo'lmasa yaratish")
    p.add_argument("--tur", help=f"Kamera turi: {', '.join(ROOM_TYPES)}")
    p.add_argument("--kochirish", action="store_true", help="Nusxa emas, ko'chirish (joy tejaydi)")
    p.set_defaults(handler=cmd_import)

    p = sub.add_parser("papka", help="Papkadagi barcha videolarni kameralarga bog'lash (ID, IP yoki nom bo'yicha)")
    p.add_argument("papka")
    p.add_argument("--qollash", action="store_true", help="Yozish (standart — faqat reja ko'rsatiladi)")
    p.add_argument("--usul", choices=("havola", "nusxa", "kochirish"), default="havola",
                   help="havola — joy egallamaydi (standart)")
    p.add_argument("--eng-kam", dest="eng_kam", type=float, default=60.0,
                   help="Shundan qisqa (soniya) videolar o'tkazib yuboriladi")
    p.set_defaults(handler=cmd_folder)

    p = sub.add_parser("dars", help="Dars jadvaliga dars qo'shish (sinov uchun)")
    p.add_argument("--kamera", required=True)
    p.add_argument("--kun", required=True)
    p.add_argument("--vaqt", required=True, help="HH:MM-HH:MM")
    p.add_argument("--guruh", required=True)
    p.add_argument("--oqituvchi")
    p.add_argument("--fan")
    p.add_argument("--fakultet")
    p.set_defaults(handler=cmd_lesson)

    p = sub.add_parser("tahlil", help="Kunni tahlil qilish")
    p.add_argument("--kun", required=True)
    p.add_argument("--oyna", help="HH:MM-HH:MM (standart: shu kungi videolar oralig'i)")
    p.add_argument("--majburiy", action="store_true", help="Boshqa tahlil ketayotgan bo'lsa ham")
    p.add_argument("--kadr", type=float, help="Kirish kameralari kadr/s (standart 1-2; 0.5 — tezroq)")
    p.add_argument("--hamma-joyda", dest="hamma_joyda", action="store_true",
                   help="Kamera turidan qat'i nazar har kamerada chekish/xalat/tanish (dars xonasida ham)")
    p.set_defaults(handler=cmd_analyze)

    p = sub.add_parser("hisobot", help="Kun natijalari — Excel")
    p.add_argument("--kun", required=True)
    p.add_argument("--chiqish")
    p.add_argument("--tur", choices=("talaba", "xodim"))
    p.add_argument("--korsat", type=int, default=30, help="Ekranga nechta odam chiqarilsin")
    p.add_argument("--html", help="Holatlar va 2 daqiqalik video dalillar sahifasi (.html)")
    p.set_defaults(handler=cmd_report)

    p = sub.add_parser("holat", help="Import qilingan videolar")
    p.set_defaults(handler=cmd_status)

    args = parser.parse_args(argv)
    asyncio.run(args.handler(args))


if __name__ == "__main__":
    main()
