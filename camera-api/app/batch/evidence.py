"""Video dalil: har aniqlangan holat uchun yozuvdan 2 daqiqalik klip.

Agregatsiya (app/batch/aggregate.py) har odamning holatlarini — payt,
kamera, sabab — DailyPersonCriteria.details["dalillar"] ga yozadi va
hodisalar (xalat, chekish, o'qituvchi) yaratadi. Bu modul ularning har biri
uchun holatdan `video_evidence_clip_seconds / 2` oldin va keyin video kesadi
(rasm dalilidan tashqari ikkinchi dalil: odam nima qilayotgani ko'rinadi),
MinIO'ga saqlaydi va "klip" (yoki hodisaning clip_key) ga yozadi.

Bir kamerada bir-biriga yaqin (30 s ichida) holatlar bitta klipni
bo'lishadi — masalan, darsga kelmagan butun guruh uchun xonaning bitta
klipi. Kunlik chegara (video_evidence_clips_max) oshsa, eng muhim holatlar
(chekish, o'qituvchi, xalat, kechikish...) birinchi kesiladi.

Takror ishga tushirish xavfsiz: klipi bor holat qayta kesilmaydi.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models import Camera, DailyPersonCriteria, Event, NvrDevice, VideoAnalysisRun
from app.services.nvr.sources import VideoReadError, source_for

logger = logging.getLogger("app.batch.evidence")

# Kesish tartibi (chegara yetsa — avval shular).
PRIORITY = {15: 0, 22: 1, 10: 2, 8: 3, 9: 4, 7: 5, 19: 6, 21: 7, 6: 8}
MERGE_SECONDS = 30
EVIDENCE_PREFIX = "video-tahlil/dalil"


@dataclass
class ClipRequest:
    camera_id: str
    center: datetime
    priority: int
    # ("qator", qator_id, indeks) yoki ("hodisa", hodisa_id)
    targets: list[tuple] = field(default_factory=list)


def group_requests(items: list[tuple[str, datetime, int, tuple]]) -> list[ClipRequest]:
    """(kamera, payt, kod, nishon) -> kliplar. Bir kamerada birinchi holatdan
    MERGE_SECONDS ichidagilar bitta klipga."""
    by_camera: dict[str, list[tuple[datetime, int, tuple]]] = {}
    for camera_id, at, code, target in items:
        by_camera.setdefault(camera_id, []).append((at, code, target))
    requests: list[ClipRequest] = []
    for camera_id, entries in by_camera.items():
        current: ClipRequest | None = None
        for at, code, target in sorted(entries, key=lambda entry: entry[0]):
            priority = PRIORITY.get(code, 9)
            if current is not None and (at - current.center).total_seconds() <= MERGE_SECONDS:
                current.targets.append(target)
                current.priority = min(current.priority, priority)
                continue
            current = ClipRequest(camera_id=camera_id, center=at, priority=priority, targets=[target])
            requests.append(current)
    requests.sort(key=lambda request: (request.priority, request.center))
    return requests


async def _upload(data: bytes) -> str:
    from app.storage import upload_file

    _file_id, key = await asyncio.to_thread(upload_file, data, "dalil.mp4", "video/mp4", EVIDENCE_PREFIX)
    return key


async def cut_evidence_clips(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    *,
    source_factory=source_for,
    uploader=_upload,
) -> dict[str, int]:
    """Kun holatlari uchun kliplarni kesadi. Qaytaradi — statistika."""
    if not settings.video_evidence_clips:
        return {}
    half = timedelta(seconds=settings.video_evidence_clip_seconds / 2)
    async with session_factory() as db:
        run = await db.get(VideoAnalysisRun, run_id)
        if run is None:
            return {}
        rows = (
            await db.execute(select(DailyPersonCriteria).where(DailyPersonCriteria.day == run.day))
        ).scalars().all()
        events = (
            await db.execute(
                select(Event).where(
                    Event.details["run_id"].astext == str(run.id),
                    Event.clip_key.is_(None),
                    Event.camera_id.is_not(None),
                )
            )
        ).scalars().all()
        items: list[tuple[str, datetime, int, tuple]] = []
        for row in rows:
            for index, item in enumerate((row.details or {}).get("dalillar") or []):
                if item.get("klip") or not item.get("kamera_id") or not item.get("vaqt"):
                    continue
                items.append((item["kamera_id"], datetime.fromisoformat(item["vaqt"]), int(item["kod"]), ("qator", row.id, index)))
        for event in events:
            items.append((str(event.camera_id), event.occurred_at, event.module_code, ("hodisa", event.id)))
        requests = group_requests(items)
        skipped = max(0, len(requests) - settings.video_evidence_clips_max)
        requests = requests[: settings.video_evidence_clips_max]
        camera_ids = {uuid.UUID(request.camera_id) for request in requests}
        cameras = {
            str(camera.id): camera
            for camera in (await db.execute(select(Camera).where(Camera.id.in_(camera_ids)))).scalars().unique()
        } if camera_ids else {}
        nvr_ids = {camera.nvr_id for camera in cameras.values() if camera.nvr_id}
        nvrs = {
            nvr.id: nvr for nvr in (await db.execute(select(NvrDevice).where(NvrDevice.id.in_(nvr_ids)))).scalars()
        } if nvr_ids else {}

    if not requests:
        return {"dalil_kliplari": 0}
    logger.info("cutting evidence clips", extra={"run_id": str(run_id), "clips": len(requests), "skipped": skipped})
    slot = asyncio.Semaphore(max(1, settings.video_evidence_concurrency))
    results: dict[int, str | None] = {}
    errors: dict[int, str] = {}

    async def one(index: int, request: ClipRequest) -> None:
        camera = cameras.get(request.camera_id)
        nvr = nvrs.get(camera.nvr_id) if camera is not None and camera.nvr_id else None
        if camera is None or nvr is None or camera.nvr_channel is None:
            errors[index] = "kamera NVR'ga bog'lanmagan"
            return
        async with slot:
            with tempfile.TemporaryDirectory(prefix="dalil-") as tmp:
                out = Path(tmp) / "dalil.mp4"
                try:
                    source = source_factory(nvr, camera)
                    await source.export(
                        request.center - half,
                        request.center + half,
                        out,
                        height=settings.video_evidence_clip_height,
                        timeout=max(180.0, 3 * settings.video_evidence_clip_seconds),
                    )
                    results[index] = await uploader(await asyncio.to_thread(out.read_bytes))
                except (VideoReadError, ValueError, OSError) as exc:
                    errors[index] = str(exc)[:200]
                except Exception as exc:  # noqa: BLE001 — bitta klip qolganlarini to'xtatmasin
                    logger.warning("evidence clip failed", exc_info=True)
                    errors[index] = str(exc)[:200]

    await asyncio.gather(*(one(index, request) for index, request in enumerate(requests)))

    now = datetime.now(timezone.utc)
    async with session_factory() as db:
        row_updates: dict[uuid.UUID, dict[int, dict]] = {}
        for index, request in enumerate(requests):
            key = results.get(index)
            for target in request.targets:
                if target[0] == "qator":
                    row_updates.setdefault(target[1], {})[target[2]] = (
                        {"klip": key} if key else {"klip_xato": errors.get(index, "kesilmadi")}
                    )
                else:
                    event = await db.get(Event, target[1])
                    if event is not None:
                        event.clip_key = key
                        event.clip_status = "ok" if key else "none"
                        event.clip_saved_at = now if key else None
        for row_id, changes in row_updates.items():
            row = await db.get(DailyPersonCriteria, row_id)
            if row is None:
                continue
            found = list((row.details or {}).get("dalillar") or [])
            for item_index, change in changes.items():
                if item_index < len(found):
                    found[item_index] = {**found[item_index], **change}
            # JSONB o'zgarishi sezilishi uchun yangi lug'at.
            row.details = {**(row.details or {}), "dalillar": found}
        await db.commit()
    stats = {"dalil_kliplari": len(results), "dalil_xato": len(errors), "dalil_chegaradan_tashqari": skipped}
    logger.info("evidence clips done", extra={"run_id": str(run_id), **stats})
    return stats
