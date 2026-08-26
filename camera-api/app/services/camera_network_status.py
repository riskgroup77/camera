"""Camera network reachability snapshot for the admin dashboard."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.jobs.camera_health import is_reachable
from app.jobs.camera_health_metrics import get_camera_health_sweep_stats
from app.models import AuditLog, Camera


def _is_link_local_ip(ip: str) -> bool:
    return ip.startswith("169.254.") or ip.startswith("fe80:")


async def build_camera_network_status(db: AsyncSession) -> dict[str, object]:
    result = await db.execute(select(Camera).where(Camera.status == "faol"))
    cameras = result.scalars().all()

    reachable = sum(1 for c in cameras if is_reachable(c.last_seen_at))
    faol = len(cameras)
    offline = faol - reachable
    link_local = sum(1 for c in cameras if _is_link_local_ip(c.ip))

    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.camera_offline_alert_minutes)
    chronic_offline = sum(
        1
        for c in cameras
        if not is_reachable(c.last_seen_at)
        and (c.last_seen_at is None or c.last_seen_at < stale_cutoff)
    )

    recent_alerts = int(
        await db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.module == "Kameralar",
                AuditLog.action.like("%javob bermayapti%"),
                AuditLog.occurred_at >= datetime.now(timezone.utc) - timedelta(hours=24),
            )
        )
        or 0
    )

    sweep = get_camera_health_sweep_stats()
    recommendation = _build_recommendation(
        faol=faol,
        reachable=reachable,
        link_local=link_local,
        chronic_offline=chronic_offline,
    )

    return {
        "faol_cameras": faol,
        "reachable_cameras": reachable,
        "offline_cameras": offline,
        "link_local_ip_count": link_local,
        "chronic_offline_count": chronic_offline,
        "offline_alert_minutes": settings.camera_offline_alert_minutes,
        "health_interval_seconds": settings.camera_health_interval_seconds,
        "health_freshness_seconds": settings.camera_health_freshness_seconds,
        "health_concurrency": settings.camera_health_concurrency,
        "recent_offline_alerts_24h": recent_alerts,
        "last_sweep": {
            "finished_at": sweep.finished_at.isoformat() if sweep.finished_at else None,
            "duration_seconds": sweep.duration_seconds,
            "faol_checked": sweep.faol_checked,
            "reachable": sweep.reachable,
            "skipped_overlap": sweep.skipped_overlap,
        },
        "recommendation": recommendation,
    }


def _build_recommendation(
    *,
    faol: int,
    reachable: int,
    link_local: int,
    chronic_offline: int,
) -> str:
    if faol == 0:
        return "Faol kamera yo'q — admin paneldan kameralarni 'faol' holatiga o'tkazing."

    if reachable == 0 and link_local > 0:
        return (
            f"Barcha {link_local} ta kamera 169.254.x (link-local) manzilida — "
            "server ularga yetolmaydi. Institut IT: VPN/tunnel yoki haqiqiy IP (10.x/192.168.x) bering."
        )

    if reachable == 0:
        return (
            "Hech qanday kamera javob bermayapti — serverdan kamera tarmog'iga "
            "VPN/firewall yo'lini tekshiring (TCP port 554)."
        )

    ratio = reachable / faol
    if ratio < 0.5:
        return (
            f"Kameralarning {offline_pct(faol - reachable, faol)}% offline — "
            "tarmoq yoki NVR muammosi. Audit jurnalida 'Kamera monitoring' ogohlantirishlarini ko'ring."
        )

    if chronic_offline > 0:
        return (
            f"{chronic_offline} ta kamera {settings.camera_offline_alert_minutes}+ daqiqa davomida offline — "
            "doimiy aloqa muammosi bo'lishi mumkin."
        )

    if link_local > 0:
        return (
            f"{reachable}/{faol} kamera online. {link_local} ta hali link-local IP da — "
            "uzoq muddatda haqiqiy IP ga o'tkazish tavsiya etiladi."
        )

    return f"{reachable}/{faol} kamera online — tarmoq holati yaxshi."


def offline_pct(offline: int, total: int) -> int:
    if total <= 0:
        return 0
    return round(offline * 100 / total)
