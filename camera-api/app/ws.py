import logging

from fastapi import WebSocket

from app.redis_bus import publish_event

logger = logging.getLogger("app.ws")


class ConnectionManager:
    """WebSocket client registry. With REDIS_URL set, broadcasts are also
    published to Redis so every API worker forwards to its local clients."""

    def __init__(self) -> None:
        self.active: set[WebSocket] = set()
        self._local_only = False

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.add(websocket)
        logger.info("ws client connected", extra={"total_connections": len(self.active)})

    def disconnect(self, websocket: WebSocket) -> None:
        self.active.discard(websocket)
        logger.info("ws client disconnected", extra={"total_connections": len(self.active)})

    async def _send_local(self, message: dict) -> None:
        dead: list[WebSocket] = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.discard(ws)

    async def broadcast(self, message: dict) -> None:
        """Publish to Redis (multi-instance) and always fan out locally."""
        published = await publish_event(message)
        if not published or self._local_only:
            await self._send_local(message)

    async def deliver_from_redis(self, message: dict) -> None:
        """Called by Redis listener — forward to local clients only."""
        await self._send_local(message)


manager = ConnectionManager()
