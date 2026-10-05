"""Background camera reachability sweep.

Closes a real gap: Camera.status is a manually-set admin field ("this
camera should be active") that never reflects reality if the camera
actually goes offline — cable unplugged, IP changed, device powered off.
Before this, the Monitoring page's "Oflayn" count and the admin table's
status badge were both just echoing whatever an operator last typed in,
not anything observed. This runs a lightweight TCP check against every
'faol' camera on a timer and stamps last_seen_at on success;
is_reachable() below is computed from how fresh that stamp is and is what
app/routers/cameras.py and app/routers/public.py actually expose.

When a camera stays unreachable longer than camera_offline_alert_minutes,
an AuditLog alert is written once (deduplicated per outage) so admins
can spot chronic network failures without watching the monitoring page.

Har bir uzilish camera_outages jadvaliga ham yoziladi (_sync_outages) —
tizim sahifasidagi "Kameralar" bo'limi uptime foizini shundan hisoblaydi.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal
from app.jobs.camera_health_metrics import (
    record_camera_health_skip,
    record_camera_health_sweep,
)
from app.jobs.sweep_guard import SweepGuard
from app.models import AuditLog, Camera, CameraOutage
from app.services.frame_grabber import camera_video_source
from app.services.notifications import notify_camera_status
from app.services.stream_cache import peek_cached_frame
from app.services.connectivity import tcp_check
from app.services.thumbnail_cache import frames_seen_at

logger = logging.getLogger("app.camera_health")

_health_semaphore = asyncio.Semaphore(settings.camera_health_concurrency)
_sweep_guard = SweepGuard("camera_health")

# camera_id -> UTC moment when the current offline streak started
_offline_since: dict[str, datetime] = {}
# camera_ids that already received an alert for the current offline streak
_alerted: set[str] = set()
# Xotiradagi holat bazadagi ochiq uzilishlardan bir marta tiklanganmi.
_state_restored = False


def is_video_flowing(last_frame_at: datetime | None) -> bool:
    """Whether this camera has recently produced a usable picture.

    Deliberately separate from is_reachable(): a camera can answer on its
    RTSP port and still decode to nothing. Six of the fleet were doing
    exactly that while the wall showed them as live."""
    if last_frame_at is None:
        return False
    return (datetime.now(timezone.utc) - last_frame_at) < timedelta(
        seconds=settings.camera_video_stale_seconds
    )


def is_reachable(last_seen_at: datetime | None) -> bool:
    if last_seen_at is None:
        return False
    return (datetime.now(timezone.utc) - last_seen_at) < timedelta(
        seconds=settings.camera_health_freshness_seconds
    )


async def _check_one(camera: Camera) -> tuple[bool, float]:
    async with _health_semaphore:
        return await tcp_check(camera.ip, camera.port)


async def _maybe_raise_offline_alert(db: AsyncSession, camera: Camera, offline_since: datetime) -> None:
    alert_minutes = settings.camera_offline_alert_minutes
    if alert_minutes < 0:
        return
    camera_id = str(camera.id)
    if camera_id in _alerted:
        return
    if alert_minutes > 0 and datetime.now(timezone.utc) - offline_since < timedelta(minutes=alert_minutes):
        return

    _alerted.add(camera_id)
    if alert_minutes == 0:
        message = f"Kamera javob bermayapti: {camera.name} ({camera.ip}:{camera.port})"
    else:
        message = (
            f"Kamera {alert_minutes} daqiqadan beri javob bermayapti: "
            f"{camera.name} ({camera.ip}:{camera.port})"
        )
    logger.warning(
        "camera offline alert",
        extra={
            "camera_id": camera_id,
            "camera_name": camera.name,
            "ip": camera.ip,
            "port": camera.port,
            "offline_since": offline_since.isoformat(),
        },
    )
    db.add(
        AuditLog(
            user_id=None,
            user_name="Kamera monitoring",
            action=message,
            module="Kameralar",
            status="ogohlantirish",
            ip="internal",
        )
    )
    await notify_camera_status(camera, online=False, offline_since=offline_since)


async def _restore_state_once(db: AsyncSession, now: datetime) -> None:
    """Qayta ishga tushgandan keyin holatni camera_outages'dan tiklaydi.

    Holat faqat xotirada edi: har deploy/restartda allaqachon xabar
    berilgan oflayn kameralar uchun Telegram ogohlantirishi QAYTA ketardi,
    tiklangan kamera uchun esa "yana ishlayapti" xabari umuman ketmasdi."""
    global _state_restored
    if _state_restored:
        return
    alert_after = timedelta(minutes=max(settings.camera_offline_alert_minutes, 0))
    rows = (await db.execute(select(CameraOutage).where(CameraOutage.ended_at.is_(None)))).scalars().all()
    for outage in rows:
        camera_id = str(outage.camera_id)
        started = outage.started_at
        if camera_id not in _offline_since or started < _offline_since[camera_id]:
            _offline_since[camera_id] = started
        if now - started >= alert_after:
            _alerted.add(camera_id)
    # Faqat muvaffaqiyatdan keyin: so'rov yiqilsa keyingi tekshiruvda yana urinadi.
    _state_restored = True


def _track_offline_camera(camera: Camera, now: datetime) -> datetime:
    camera_id = str(camera.id)
    if camera_id not in _offline_since:
        _offline_since[camera_id] = now
    return _offline_since[camera_id]


def _mark_camera_online(camera: Camera) -> bool:
    """True — kamera ilgari "o'chdi" deb ogohlantirilgan edi (endi tiklandi)."""
    camera_id = str(camera.id)
    _offline_since.pop(camera_id, None)
    was_alerted = camera_id in _alerted
    _alerted.discard(camera_id)
    return was_alerted


def reset_camera_health_state_for_tests() -> None:
    """Tests only — clears in-memory offline streak tracking between cases."""
    _offline_since.clear()
    _alerted.clear()
    global _state_restored
    _state_restored = False


async def _sync_outages(
    db: AsyncSession,
    cameras: list[Camera],
    failures: dict[str, str],
    now: datetime,
) -> None:
    """camera_outages jadvalini shu tekshiruv natijasiga moslaydi.

    Uzilish faqat kamera haqiqatan "oflayn" bo'lganda ochiladi — ya'ni
    is_reachable() ham False qaytarganda. Bitta yo'qolgan TCP javob
    (tarmoqdagi bir lahzalik tebranish) sahifada kamerani oflayn
    ko'rsatmaydi, demak uzilish sifatida ham hisoblanmasligi kerak —
    aks holda uptime foizi ko'rinib turgan holatga zid bo'lardi.

    Idempotent: ochiq uzilish bor bo'lsa, yangisi ochilmaydi. Shu sabab
    API qayta ishga tushganda ham to'g'ri ishlaydi — xotiradagi holat
    yo'qolsa ham, baza "ochiq uzilish bormi" degan savolga javob beradi.

    `failures` — camera_id -> sabab ("tarmoq" | "xato"); unda yo'q faol
    kamera — javob bergan kamera."""
    rows = (await db.execute(select(CameraOutage).where(CameraOutage.ended_at.is_(None)))).scalars().all()
    open_by_camera: dict[str, list[CameraOutage]] = {}
    for outage in rows:
        open_by_camera.setdefault(str(outage.camera_id), []).append(outage)

    checked: set[str] = set()
    for camera in cameras:
        camera_id = str(camera.id)
        checked.add(camera_id)
        open_rows = open_by_camera.get(camera_id, [])
        reason = failures.get(camera_id)
        if reason is None:
            for outage in open_rows:
                outage.ended_at = now
        elif not open_rows and not is_reachable(camera.last_seen_at):
            # Boshlanish — kamera oxirgi marta ko'rilgan payt: tekshiruv
            # oralig'i 30s, ya'ni aniqlik shu darajada. Hech ko'rilmagan
            # bo'lsa — hozir.
            started = camera.last_seen_at or now
            db.add(CameraOutage(camera_id=camera.id, started_at=min(started, now), reason=reason))

    # Faol bo'lmay qolgan (nofaol/tamirda) yoki o'chirilgan kameralar
    # endi tekshirilmaydi — ularning uzilishi abadiy "davom etmasin".
    for camera_id, open_rows in open_by_camera.items():
        if camera_id not in checked:
            for outage in open_rows:
                outage.ended_at = now


def _latest_frame_moment(camera: Camera, seen_at: dict[str, float], now: datetime) -> datetime | None:
    """Kameradan oxirgi yaroqli kadr qachon kelgan — bilsak.

    Faqat shu jarayondagi o'quvchiga qarash yetmas edi: miniatyurani
    ikkinchi worker oladi, kirish kamerasini esa AI asosiy oqimdan
    o'qiydi (bu yerdagi manzil boshqa). Productionda "TASVIRSIZ" deb
    ko'rsatilgan 8 kameradan 7 tasi aslida rasm berayotgan edi."""
    source = camera_video_source(camera)
    if source and peek_cached_frame(source) is not None:
        return now
    moment = seen_at.get(str(camera.id))
    if moment is None:
        return None
    return min(now, datetime.fromtimestamp(moment, tz=timezone.utc))


async def run_camera_health_sweep_once(db: AsyncSession) -> int:
    """Checks every 'faol' camera CONCURRENTLY (bounded by
    _health_semaphore), stamps last_seen_at on the reachable ones. Returns
    how many were reachable this sweep (for logging)."""
    started = time.monotonic()
    result = await db.execute(select(Camera).where(Camera.status == "faol"))
    cameras = result.scalars().all()

    now = datetime.now(timezone.utc)
    try:
        await _restore_state_once(db, now)
    except Exception:
        logger.exception("camera health state restore failed")
        await db.rollback()
    results = await asyncio.gather(*(_check_one(camera) for camera in cameras), return_exceptions=True)
    seen_at = await frames_seen_at([str(camera.id) for camera in cameras])

    reachable_count = 0
    frames_count = 0
    failures: dict[str, str] = {}
    for camera, outcome in zip(cameras, results, strict=True):
        if isinstance(outcome, BaseException):
            logger.exception("camera health check failed", extra={"camera_id": str(camera.id)}, exc_info=outcome)
            failures[str(camera.id)] = "xato"
            offline_since = _track_offline_camera(camera, now)
            await _maybe_raise_offline_alert(db, camera, offline_since)
            continue
        ok, _latency_ms = outcome
        if ok:
            camera.last_seen_at = now
            if _mark_camera_online(camera):
                await notify_camera_status(camera, online=True)
            reachable_count += 1
            # Tasvir kelayotganini ham shu yerda belgilaymiz. Bu deyarli
            # tekin: kadr allaqachon xotirada turadi, peek esa o'quvchi
            # ochmaydi va uni "so'ralgan" deb belgilamaydi — ya'ni bu
            # tekshiruv hech qanday ffmpeg jarayonini tirik ushlab
            # turmaydi.
            frame_at = _latest_frame_moment(camera, seen_at, now)
            if frame_at is not None and (camera.last_frame_at is None or frame_at > camera.last_frame_at):
                camera.last_frame_at = frame_at
            if is_video_flowing(camera.last_frame_at):
                frames_count += 1
        else:
            failures[str(camera.id)] = "tarmoq"
            offline_since = _track_offline_camera(camera, now)
            await _maybe_raise_offline_alert(db, camera, offline_since)
    try:
        # Savepoint: yiqilsa faqat uzilishlar qismi bekor bo'ladi.
        async with db.begin_nested():
            await _sync_outages(db, list(cameras), failures, now)
    except Exception:
        # Uzilishlar tarixi — qo'shimcha ma'lumot; u yiqilsa ham
        # last_seen_at yozilishi (asosiy vazifa) to'xtamasligi kerak.
        logger.exception("camera outage bookkeeping failed")
    await db.commit()
    record_camera_health_sweep(
        duration_seconds=time.monotonic() - started,
        faol_checked=len(cameras),
        reachable=reachable_count,
    )
    blind = reachable_count - frames_count
    if blind > 0:
        # Erishiladigan, lekin tasvirsiz kameralar. Bu jimgina o'tib
        # ketadigan holat edi: devorda ular "JONLI" ko'rinadi, AI esa
        # ulardan hech narsa ololmaydi.
        logger.warning(
            "cameras answer on the network but produce no picture",
            extra={"reachable": reachable_count, "with_video": frames_count, "blind": blind},
        )
    return reachable_count


async def camera_health_loop() -> None:
    """Runs forever. An immediate first pass at startup (rather than waiting
    a full interval) means genuinely-live cameras don't read as "offline"
    for up to camera_health_interval_seconds right after a restart."""
    while True:
        try:

            async def _tick() -> int:
                async with SessionLocal() as db:
                    return await run_camera_health_sweep_once(db)

            count = await _sweep_guard.run(_tick)
            if count is None:
                record_camera_health_skip()
            else:
                logger.info("camera health sweep complete", extra={"reachable": count})
        except Exception:
            logger.exception("camera health sweep failed")
        await asyncio.sleep(settings.camera_health_interval_seconds)
