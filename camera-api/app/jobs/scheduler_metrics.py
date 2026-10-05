"""AI rejalashtiruvchi ko'rsatkichlari — /api/system/ai-status o'qiydi.

Ilgari bu "oxirgi tick" edi: bitta tick barcha modullarni kutardi va
oldingisi tugamagan bo'lsa keyingisi "0 modul, 0 s (overlap skip)" deb
yozilardi — boshqaruv panelida doimiy "Oxirgi tick: 0 modul" shundan edi.
Endi har bir sweep o'z tsiklida ishlaydi, shuning uchun har biri alohida
qayd etiladi va panel uchun oxirgi daqiqa bo'yicha yig'indi hisoblanadi.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

WINDOW_SECONDS = 60


@dataclass
class SchedulerTickStats:
    finished_at: datetime | None = None
    duration_seconds: float = 0.0
    modules_ran: int = 0
    critical_ran: int = 0
    standard_ran: int = 0
    skipped_overlap: bool = False


@dataclass
class SweepRunStats:
    name: str
    tier: str
    interval_seconds: int
    runs: int = 0
    failures: int = 0
    running: bool = False
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_duration_seconds: float = 0.0
    last_result: int = 0
    last_error: str | None = None
    # Tirband soatda davomat uchun ataylab to'xtatilgan (xato emas).
    paused: bool = False

    def is_lagging(self, now: datetime) -> bool:
        """Sweep o'z intervalidan ancha kechikayaptimi (osilib qolgan yoki
        server yuklamasi ko'tara olmayapti)."""
        if self.paused:
            return False
        # Surunkali sekinlik ham kechikish: productionda yuz tekshiruvi 30 s
        # o'rniga 296 s davom etgan, lekin "kechikmayapti" deb ko'rsatilgan —
        # pastdagi tekshiruv faqat butunlay osilib qolgan sweepni ko'radi.
        if self.last_duration_seconds > max(self.interval_seconds * 3, 60):
            return True
        reference = self.last_finished_at or self.last_started_at
        if reference is None:
            return False
        allowed = max(self.interval_seconds * 3, 60) + (self.last_duration_seconds if self.running else 0)
        return (now - reference).total_seconds() > allowed


_sweeps: dict[str, SweepRunStats] = {}


def register_sweep(name: str, tier: str, interval_seconds: int) -> None:
    _sweeps[name] = SweepRunStats(name=name, tier=tier, interval_seconds=interval_seconds)


def record_sweep_started(name: str) -> None:
    stats = _sweeps.get(name)
    if stats is None:
        return
    stats.running = True
    stats.last_started_at = datetime.now(timezone.utc)


def record_sweep_paused(name: str, paused: bool) -> None:
    stats = _sweeps.get(name)
    if stats is not None:
        stats.paused = paused


def record_sweep_finished(name: str, *, duration_seconds: float, result: int, error: str | None = None) -> None:
    stats = _sweeps.get(name)
    if stats is None:
        return
    stats.running = False
    stats.runs += 1
    stats.last_finished_at = datetime.now(timezone.utc)
    stats.last_duration_seconds = round(duration_seconds, 2)
    stats.last_result = result
    stats.last_error = error
    if error is not None:
        stats.failures += 1


def get_sweep_stats() -> list[SweepRunStats]:
    return list(_sweeps.values())


def export_sweeps() -> list[dict]:
    """JSON'ga yaroqli ko'rinish — boshqa API jarayoniga uzatish uchun
    (app/services/runtime_snapshot.py)."""
    return [
        {
            "name": s.name,
            "tier": s.tier,
            "interval_seconds": s.interval_seconds,
            "runs": s.runs,
            "failures": s.failures,
            "running": s.running,
            "last_started_at": s.last_started_at.isoformat() if s.last_started_at else None,
            "last_finished_at": s.last_finished_at.isoformat() if s.last_finished_at else None,
            "last_duration_seconds": s.last_duration_seconds,
            "last_result": s.last_result,
            "last_error": s.last_error,
            "paused": s.paused,
        }
        for s in _sweeps.values()
    ]


def sweeps_from_dicts(rows: list[dict]) -> list[SweepRunStats]:
    out: list[SweepRunStats] = []
    for row in rows:
        try:
            out.append(
                SweepRunStats(
                    name=str(row["name"]),
                    tier=str(row["tier"]),
                    interval_seconds=int(row["interval_seconds"]),
                    runs=int(row.get("runs", 0)),
                    failures=int(row.get("failures", 0)),
                    running=bool(row.get("running", False)),
                    last_started_at=datetime.fromisoformat(row["last_started_at"]) if row.get("last_started_at") else None,
                    last_finished_at=datetime.fromisoformat(row["last_finished_at"]) if row.get("last_finished_at") else None,
                    last_duration_seconds=float(row.get("last_duration_seconds", 0.0)),
                    last_result=int(row.get("last_result", 0)),
                    last_error=row.get("last_error"),
                    paused=bool(row.get("paused", False)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def get_scheduler_tick_stats() -> SchedulerTickStats:
    return tick_from_sweeps(list(_sweeps.values()))


def tick_from_sweeps(sweeps: list[SweepRunStats]) -> SchedulerTickStats:
    """Oxirgi WINDOW_SECONDS ichida kamida bir marta tugagan sweeplar."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(seconds=WINDOW_SECONDS)
    recent = [s for s in sweeps if s.last_finished_at is not None and s.last_finished_at >= since]
    if not recent:
        return SchedulerTickStats()
    return SchedulerTickStats(
        finished_at=max(s.last_finished_at for s in recent if s.last_finished_at is not None),
        duration_seconds=round(max(s.last_duration_seconds for s in recent), 2),
        modules_ran=len(recent),
        critical_ran=sum(1 for s in recent if s.tier == "critical"),
        standard_ran=sum(1 for s in recent if s.tier == "standard"),
        skipped_overlap=False,
    )


def reset_for_tests() -> None:
    _sweeps.clear()
