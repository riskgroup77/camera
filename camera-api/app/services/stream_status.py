"""MediaMTX shard observability for the admin dashboard."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Camera
from app.services.video_gateway import probe_shards, shard_count, shard_index_for


def _distribution_for_camera_ids(camera_ids: list[str]) -> list[int]:
    count = shard_count()
    buckets = [0] * count
    for camera_id in camera_ids:
        buckets[shard_index_for(camera_id)] += 1
    return buckets


def _build_recommendation(
    *,
    sharding_enabled: bool,
    faol: int,
    registered: int,
    shards: list[dict[str, object]],
    distribution: list[int],
) -> str:
    unreachable = [s for s in shards if not s["reachable"]]
    if unreachable:
        names = ", ".join(str(s["index"]) for s in unreachable)
        return f"MediaMTX shard(lar) javob bermayapti: {names} — docker ps va nginx /s0 /s1 /s2 ni tekshiring."

    if faol > 0 and registered < faol:
        return (
            f"{faol - registered} ta faol kamera MediaMTX da ro'yxatdan o'tmagan — "
            "POST /api/system/resync-streams yoki API qayta ishga tushiring."
        )

    if sharding_enabled and faol >= 30 and distribution:
        avg = faol / len(distribution)
        max_bucket = max(distribution)
        if max_bucket > avg * 1.35 + 2:
            return "Shard taqsimoti biroz nomutanosib — hash barqaror, lekin kamera ID larini tekshiring."

    if sharding_enabled:
        return f"MediaMTX {len(shards)}-shard rejimida ishlayapti — pathlar shard bo'yicha taqsimlangan."
    return "Bitta MediaMTX node — 100+ kamera uchun 3-shard (deploy/setup-scale-infra.sh) tavsiya etiladi."


async def build_stream_status(db: AsyncSession) -> dict[str, object]:
    faol = int(
        await db.scalar(select(func.count()).select_from(Camera).where(Camera.status == "faol")) or 0
    )
    registered = int(
        await db.scalar(
            select(func.count())
            .select_from(Camera)
            .where(Camera.status == "faol", Camera.stream_url.is_not(None))
        )
        or 0
    )
    camera_ids = [
        str(row[0])
        for row in (
            await db.execute(select(Camera.id).where(Camera.status == "faol"))
        ).all()
    ]
    distribution = _distribution_for_camera_ids(camera_ids)
    shards = await probe_shards()
    sharding_enabled = len(shards) > 1

    for index, shard in enumerate(shards):
        shard["assigned_cameras"] = distribution[index] if index < len(distribution) else 0

    return {
        "sharding_enabled": sharding_enabled,
        "shard_count": len(shards),
        "faol_cameras": faol,
        "registered_streams": registered,
        "shards": shards,
        "distribution": distribution,
        "recommendation": _build_recommendation(
            sharding_enabled=sharding_enabled,
            faol=faol,
            registered=registered,
            shards=shards,
            distribution=distribution,
        ),
        "hls_public_base": settings.mediamtx_hls_base_url,
    }
