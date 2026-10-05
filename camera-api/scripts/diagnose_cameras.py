# -*- coding: utf-8 -*-
"""Kameralar va yuz tanish bo'yicha diagnostika — FAQAT O'QIYDI.

Sog'liq tekshiruvi (deploy/healthcheck.sh) ikki savolni ochiq qoldirdi:

1. "Ko'r" kameralar — tarmoqda javob beradi, lekin tasvir yo'q. Sabab
   kamerada (oqim o'chiq, kodek, parol) yoki shunchaki hozir hech bir AI
   sweep o'sha kamerani o'qimayotganida bo'lishi mumkin: cameras.last_frame_at
   faqat ochiq o'quvchi xotirasida kadr turganda yangilanadi. Bu skript
   har bir shunday kameraning ikkala oqimini (102 va asosiy) ffprobe bilan
   BEVOSITA tekshiradi.

2. Davomat — 415 kishining yuzi tasdiqlangan, bugungi yozuvlar esa bir
   nechta. Davomat ham, #1 "begona shaxs" ham bir xil chegarani
   (settings.attendance_ai_match_threshold) ishlatadi: undan past
   o'xshashlik bergan tasdiqlangan xodim davomatga yozilmaydi VA begona deb
   signal beradi. Bu skript kirish/chiqish kameralaridan hozirgi kadrlarni
   olib, har bir yuzning ro'yxatdagilarga eng yuqori o'xshashligini
   o'lchaydi — chegara muammomi yoki yo'qmi, raqam bilan ko'rinadi.

Hech narsa yozmaydi, hodisa yaratmaydi. Parollar chiqishda yashiriladi.

ISHGA TUSHIRISH (server, fonda — terminal band bo'lmaydi):

    docker compose exec -d api sh -c "python scripts/diagnose_cameras.py > /tmp/diag.txt 2>&1"
    docker compose exec -T api cat /tmp/diag.txt
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal
from app.models import AttendanceRecord, Camera
from app.services.connectivity import _rtsp_probe
from app.services.face_matching import load_candidate_matrix_for_sweep
from app.services.face_recognition import detect_faces
from app.services.frame_grabber import ai_prefers_substream, grab_frame_for_camera, rtsp_url_for_camera
from app.services.stream_cache import _redact, shutdown_stream_cache
from app.timezone import local_now

STALE_AFTER = timedelta(minutes=10)
PROBE_CONCURRENCY = 4
FRAMES_PER_CAMERA = 3
FRAME_GAP_SECONDS = 3.0
FIRST_FRAME_WAIT_SECONDS = 25.0
SIMILARITY_BINS = (0.0, 0.30, 0.40, 0.45, 0.50, 0.55, 0.60, 1.01)
SHOW_NAME_FROM = 0.40

_started = time.monotonic()

# Chiqish faylga yo'naltiriladi; konteyner yoki konsol lokali UTF-8 bo'lmasa
# "━" va o'zbekcha belgilar skriptni yiqitmasin.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def say(text: str = "") -> None:
    print(text, flush=True)


def section(title: str) -> None:
    say()
    say(f"━━ {title} ━━  (+{time.monotonic() - _started:.0f}s)")


def _age(moment: datetime | None) -> str:
    if moment is None:
        return "hech qachon"
    minutes = int((datetime.now(timezone.utc) - moment).total_seconds() // 60)
    return f"{minutes} daq oldin" if minutes < 120 else f"{minutes // 60} soat oldin"


def _role(camera: Camera) -> str:
    roles = [label for flag, label in ((camera.is_entrance, "kirish"), (camera.is_exit, "chiqish"),
                                       (camera.is_perimeter, "perimetr")) if flag]
    return "+".join(roles) or "oddiy"


async def _probe(url: str) -> str:
    ok, description = await _rtsp_probe(url)
    if ok:
        return f"OK  {description}"
    return f"YO'Q  {_redact(description or 'javob yo`q (timeout)')}"


async def overview() -> tuple[list[Camera], object]:
    section("1. Umumiy holat")
    async with SessionLocal() as db:
        cameras = (await db.execute(select(Camera).where(Camera.status == "faol").order_by(Camera.name))).scalars().all()
        candidates = await load_candidate_matrix_for_sweep(db)
        today = local_now().date()
        attendance_today = (
            await db.execute(select(func.count()).select_from(AttendanceRecord).where(AttendanceRecord.date == today))
        ).scalar_one()
    say(f"  Faol kameralar: {len(cameras)}")
    say(f"  Yuz vektori bor odamlar (tanish ro'yxati): {len(candidates.ids)}")
    say(f"  Bugungi ({today}) davomat yozuvlari: {attendance_today}")
    say(f"  Tanish chegarasi (davomat va #1 begona shaxs uchun bir xil): {settings.attendance_ai_match_threshold}")
    say(f"  Kirish/chiqish kameralari asosiy oqimdan o'qiladi: {settings.ai_entrance_use_main_stream}")
    return list(cameras), candidates


async def blind_cameras(cameras: list[Camera]) -> None:
    section("2. Tasvir bermayotgan kameralar — oqimlarni bevosita tekshirish")
    now = datetime.now(timezone.utc)
    stale = [c for c in cameras if c.last_frame_at is None or now - c.last_frame_at > STALE_AFTER]
    if not stale:
        say("  Hammasi tasvir bermoqda.")
        return
    say(f"  {len(stale)} ta kamera: oxirgi kadr 10 daqiqadan eski. Har biriga 102 va asosiy oqim sinaladi...")
    semaphore = asyncio.Semaphore(PROBE_CONCURRENCY)

    async def one(camera: Camera) -> tuple[Camera, str, str]:
        async with semaphore:
            sub = await _probe(rtsp_url_for_camera(camera, substream=True))
            main = await _probe(rtsp_url_for_camera(camera, substream=False))
            return camera, sub, main

    for camera, sub, main in await asyncio.gather(*(one(c) for c in stale)):
        ai_uses = "102" if ai_prefers_substream(camera) else (camera.rtsp_path or "101")
        say()
        say(f"  {camera.name}  [{_role(camera)}]  AI o'qiydi: {ai_uses}")
        say(f"      tarmoq: {_age(camera.last_seen_at)} | oxirgi kadr: {_age(camera.last_frame_at)}")
        say(f"      102 oqim   : {sub}")
        say(f"      asosiy oqim: {main}")


async def face_similarity(cameras: list[Camera], candidates) -> None:
    section("3. Kirish/chiqish kameralarida yuz o'xshashligi")
    targets = [c for c in cameras if c.is_entrance or c.is_exit]
    if not targets:
        say("  Kirish/chiqish kamerasi belgilanmagan.")
        return
    if candidates.is_empty:
        say("  Tanish ro'yxati bo'sh — taqqoslash imkonsiz.")
        return
    say(f"  {len(targets)} ta kameradan {FRAMES_PER_CAMERA} tadan kadr olinmoqda (1-2 daqiqa)...")

    names = await _names(candidates.ids)
    threshold = settings.attendance_ai_match_threshold

    async def one(camera: Camera) -> tuple[Camera, int, list[tuple[float, int, str]]]:
        frames = 0
        found: list[tuple[float, int, str]] = []
        for attempt in range(FRAMES_PER_CAMERA):
            if attempt:
                await asyncio.sleep(FRAME_GAP_SECONDS)
            frame = await grab_frame_for_camera(camera, wait_seconds=FIRST_FRAME_WAIT_SECONDS if attempt == 0 else 8.0)
            if frame is None:
                continue
            frames += 1
            for face in await detect_faces(frame):
                emb = np.asarray(face.embedding, dtype=np.float64)
                emb = emb / (np.linalg.norm(emb) or 1.0)
                sims = candidates.matrix @ emb
                best = int(np.argmax(sims))
                height = int(face.bbox[3] - face.bbox[1])
                found.append((float(sims[best]), height, candidates.ids[best]))
        return camera, frames, found

    all_faces: list[tuple[float, int, str]] = []
    for camera, frames, found in await asyncio.gather(*(one(c) for c in targets)):
        all_faces.extend(found)
        best = max((s for s, _, _ in found), default=None)
        best_text = f"eng yuqori o'xshashlik {best:.2f}" if best is not None else "yuz yo'q"
        say(f"  {camera.name:<38.38} [{_role(camera)}] kadr {frames}/{FRAMES_PER_CAMERA}, yuz {len(found)}, {best_text}")

    say()
    if not all_faces:
        say("  Hozir kadrlarda yuz topilmadi — kirishda odam kam paytda qayta ishga tushiring.")
        return

    say(f"  Jami {len(all_faces)} ta yuz. Eng yaqin ro'yxatdagi odamga o'xshashlik taqsimoti:")
    sims = np.array([s for s, _, _ in all_faces])
    for low, high in zip(SIMILARITY_BINS, SIMILARITY_BINS[1:]):
        count = int(((sims >= low) & (sims < high)).sum())
        mark = "  ← tanildi" if low >= threshold else ""
        upper = "1.00" if high > 1 else f"{high:.2f}"
        say(f"      {low:.2f}–{upper}: {count:>4} {'█' * min(count, 50)}{mark}")

    heights = np.array([h for _, h, _ in all_faces])
    say()
    say(f"  Yuz balandligi (piksel): median {int(np.median(heights))}, "
        f"80 dan kichik: {int((heights < 80).sum())} ta")
    say(f"  Chegaradan ({threshold}) o'tganlar: {int((sims >= threshold).sum())} ta; "
        f"{SHOW_NAME_FROM}–{threshold} oralig'ida (tanilishi mumkin bo'lganlar): "
        f"{int(((sims >= SHOW_NAME_FROM) & (sims < threshold)).sum())} ta")

    close = sorted((f for f in all_faces if f[0] >= SHOW_NAME_FROM), reverse=True)[:15]
    if close:
        say()
        say("  Eng yaqin moslar (o'xshashlik, yuz balandligi, ro'yxatdagi eng yaqin odam):")
        for similarity, height, person_id in close:
            say(f"      {similarity:.2f}  {height:>4}px  {names.get(person_id, person_id)}")


async def _names(ids: list[str]) -> dict[str, str]:
    import uuid

    from app.models import StudentStaff

    wanted = [uuid.UUID(i) for i in ids]  # ustun UUID turida, CandidateMatrix esa satr saqlaydi
    async with SessionLocal() as db:
        rows = (await db.execute(select(StudentStaff.id, StudentStaff.full_name).where(StudentStaff.id.in_(wanted)))).all()
    return {str(row.id): row.full_name for row in rows}


async def main() -> int:
    say(f"Kamera diagnostikasi — {local_now():%d.%m.%Y %H:%M:%S}")
    try:
        cameras, candidates = await overview()
        await blind_cameras(cameras)
        await face_similarity(cameras, candidates)
    finally:
        await shutdown_stream_cache()
    say()
    say("DIAGNOSTIKA TUGADI")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
