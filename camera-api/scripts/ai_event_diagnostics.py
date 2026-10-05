"""AI hodisalari diagnostikasi — faqat o'qiydi, shaxsiy ma'lumot chiqarmaydi.

Serverda:
    docker compose -f docker-compose.yml -f docker-compose.override.yml \
        -f docker-compose.mediamtx-shard.yml exec -T api python scripts/ai_event_diagnostics.py

Ko'rsatadi:
- oxirgi 30 kunda modul bo'yicha signallar, operator bahosi (tasdiq/rad),
  aniqlik, confidence taqsimoti va eng faol soatlar;
- eng shovqinli kamera x modul juftliklari;
- oxirgi 24 soatda ishchi va sinov signallari, avtomatik to'xtatilgan juftliklar.
"""

import asyncio
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select, text  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import AIModuleConfig, Event, ModuleCameraSuppression  # noqa: E402

DAYS = 30
LOCAL_HOUR = func.extract("hour", func.timezone("Asia/Tashkent", Event.occurred_at))


def pct(part: int, whole: int) -> str:
    return f"{round(part * 100 / whole)}%" if whole else "—"


async def main() -> None:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=DAYS)
    day_ago = now - timedelta(hours=24)
    async with SessionLocal() as db:
        modules = {
            code: (name, active, threshold, mode)
            for code, name, active, threshold, mode in (
                await db.execute(
                    select(
                        AIModuleConfig.code,
                        AIModuleConfig.name,
                        AIModuleConfig.active,
                        AIModuleConfig.threshold,
                        AIModuleConfig.mode,
                    )
                )
            ).all()
        }
        per_status = (
            await db.execute(
                select(Event.module_code, Event.status, func.count())
                .where(Event.occurred_at >= since)
                .group_by(Event.module_code, Event.status)
            )
        ).all()
        confidence = (
            await db.execute(
                select(
                    Event.module_code,
                    func.min(Event.confidence),
                    func.avg(Event.confidence),
                    func.max(Event.confidence),
                    func.count(func.distinct(Event.confidence)),
                )
                .where(Event.occurred_at >= since)
                .group_by(Event.module_code)
            )
        ).all()
        hours = (
            await db.execute(
                select(Event.module_code, LOCAL_HOUR, func.count())
                .where(Event.occurred_at >= since)
                .group_by(text("1"), text("2"))
            )
        ).all()
        pairs = (
            await db.execute(
                select(Event.camera_name, Event.module_code, Event.status, func.count())
                .where(Event.occurred_at >= since)
                .group_by(Event.camera_name, Event.module_code, Event.status)
            )
        ).all()
        recent = (
            await db.execute(
                select(Event.module_code, Event.is_trial, func.count())
                .where(Event.occurred_at >= day_ago)
                .group_by(Event.module_code, Event.is_trial)
            )
        ).all()
        suppressed = (
            await db.scalar(
                select(func.count()).select_from(ModuleCameraSuppression).where(ModuleCameraSuppression.restored_at.is_(None))
            )
        ) or 0

    stats: dict[int, dict[str, int]] = defaultdict(lambda: {"yangi": 0, "tasdiqlangan": 0, "rad_etilgan": 0})
    for code, status, count in per_status:
        stats[code][status] = count
    conf_by = {code: (mn, av, mx, distinct) for code, mn, av, mx, distinct in confidence}
    hours_by: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for code, hour, count in hours:
        hours_by[code].append((count, int(hour)))

    total = sum(sum(s.values()) for s in stats.values())
    reviewed = sum(s["tasdiqlangan"] + s["rad_etilgan"] for s in stats.values())
    rejected = sum(s["rad_etilgan"] for s in stats.values())
    print(
        f"=== {DAYS} kun: jami {total} signal; ko'rib chiqilgan {reviewed} ({pct(reviewed, total)}), "
        f"shundan rad etilgan {rejected} ({pct(rejected, reviewed)})"
    )
    print("kod | nomi | faol | rejim | chegara | jami | yangi | tasdiq | rad | aniqlik | confidence min/o'rt/max, turli | soatlar")
    for code in sorted(stats, key=lambda c: -sum(stats[c].values())):
        s = stats[code]
        name, active, threshold, mode = modules.get(code, ("?", None, None, "?"))
        rev = s["tasdiqlangan"] + s["rad_etilgan"]
        mn, av, mx, distinct = conf_by.get(code, (None, None, None, None))
        top_hours = ", ".join(f"{h:02d}:00({c})" for c, h in sorted(hours_by[code], reverse=True)[:3])
        print(
            f"#{code} | {name[:32]} | {'ha' if active else 'yoq'} | {mode} | {threshold} | {sum(s.values())} | "
            f"{s['yangi']} | {s['tasdiqlangan']} | {s['rad_etilgan']} | "
            f"{pct(s['tasdiqlangan'], rev) if rev >= 5 else '—'} | "
            f"{mn}/{round(av) if av is not None else '—'}/{mx}, {distinct} xil | {top_hours}"
        )

    pair_stats: dict[tuple[str, int], dict[str, int]] = defaultdict(lambda: {"yangi": 0, "tasdiqlangan": 0, "rad_etilgan": 0})
    for camera_name, code, status, count in pairs:
        pair_stats[(camera_name, code)][status] = count
    print("\n=== Eng shovqinli 20 kamera x modul (jami | tasdiq | rad | modul | kamera)")
    for (camera_name, code), s in sorted(pair_stats.items(), key=lambda kv: -sum(kv[1].values()))[:20]:
        print(f"{sum(s.values())} | {s['tasdiqlangan']} | {s['rad_etilgan']} | #{code} | {camera_name[:40]}")

    working = sum(count for _code, is_trial, count in recent if not is_trial)
    trial = sum(count for _code, is_trial, count in recent if is_trial)
    print(f"\n=== Oxirgi 24 soat: operatorga {working} ta signal, sinov namunalariga {trial} ta")
    for code, is_trial, count in sorted(recent, key=lambda row: -row[2]):
        print(f"#{code} {modules.get(code, ('?',))[0][:32]} — {'sinov' if is_trial else 'ishchi'}: {count}")
    print(f"=== Avtomatik to'xtatilgan kamera x modul juftliklari: {suppressed}")


asyncio.run(main())
