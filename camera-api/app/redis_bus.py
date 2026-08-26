"""Optional Redis pub/sub bridge for multi-instance WebSocket fan-out.

When REDIS_URL is set, event broadcasts are published to a channel; every
API worker subscribes and forwards to its local WebSocket clients. When
Redis is unavailable or not configured, callers fall back to in-memory
broadcast only (single-instance behaviour).
"""

import asyncio
import json
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger("app.redis_bus")

EVENTS_CHANNEL = "camera:events"

_redis = None
_listener_task: asyncio.Task | None = None


def _redis_url() -> str | None:
    url = (settings.redis_url or "").strip()
    return url or None


async def _get_redis():
    global _redis
    if _redis is not None:
        return _redis
    url = _redis_url()
    if not url:
        return None
    try:
        from redis.asyncio import Redis

        _redis = Redis.from_url(url, decode_responses=True)
        await _redis.ping()
        logger.info("Redis connected", extra={"redis_url": url.split("@")[-1]})
        return _redis
    except Exception:
        logger.exception("Redis connection failed — falling back to in-memory WS only")
        _redis = None
        return None


async def publish_event(message: dict[str, Any]) -> bool:
    """Publish to Redis channel. Returns True if published via Redis."""
    client = await _get_redis()
    if client is None:
        return False
    try:
        await client.publish(EVENTS_CHANNEL, json.dumps(message, default=str))
        return True
    except Exception:
        logger.exception("Redis publish failed")
        return False


async def start_redis_listener(on_message) -> None:
    """Subscribe to EVENTS_CHANNEL and call on_message(dict) for each event."""
    global _listener_task
    if _listener_task is not None:
        return
    url = _redis_url()
    if not url:
        return

    async def _listen() -> None:
        while True:
            client = await _get_redis()
            if client is None:
                await asyncio.sleep(5)
                continue
            pubsub = client.pubsub()
            try:
                await pubsub.subscribe(EVENTS_CHANNEL)
                logger.info("Redis event listener started", extra={"channel": EVENTS_CHANNEL})
                async for raw in pubsub.listen():
                    if raw["type"] != "message":
                        continue
                    try:
                        payload = json.loads(raw["data"])
                        await on_message(payload)
                    except Exception:
                        logger.exception("Redis listener message handling failed")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Redis listener disconnected — retrying in 5s")
                await asyncio.sleep(5)
            finally:
                try:
                    await pubsub.unsubscribe(EVENTS_CHANNEL)
                    await pubsub.close()
                except Exception:
                    pass

    _listener_task = asyncio.create_task(_listen())


async def stop_redis_listener() -> None:
    global _listener_task, _redis
    if _listener_task is not None:
        _listener_task.cancel()
        try:
            await _listener_task
        except asyncio.CancelledError:
            pass
        _listener_task = None
    if _redis is not None:
        try:
            await _redis.close()
        except Exception:
            pass
        _redis = None
