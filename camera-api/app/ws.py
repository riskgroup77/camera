import logging

from fastapi import WebSocket

from app.redis_bus import publish_event

logger = logging.getLogger("app.ws")


class ConnectionManager:
    """WebSocket client registry. With REDIS_URL set, broadcasts are also
    published to Redis so every API worker forwards to its local clients."""

    def __init__(self) -> None:
        self.active: set[WebSocket] = set()
        # Bino doirasi bor ulanishlar uchun ruxsat etilgan kamera
        # identifikatorlari (app/services/access_scope.py). Ro'yxatda yo'q
        # ulanish — cheklovsiz.
        self._camera_scope: dict[WebSocket, frozenset[str]] = {}
        # Hodisalarni ko'rish huquqi yo'q (faqat davomat) ulanishlar.
        self._attendance_only: set[WebSocket] = set()
        self._local_only = False

    async def connect(
        self, websocket: WebSocket, camera_ids: frozenset[str] | None = None, *, attendance_only: bool = False
    ) -> None:
        await websocket.accept()
        self.active.add(websocket)
        if camera_ids is not None:
            self._camera_scope[websocket] = camera_ids
        if attendance_only:
            self._attendance_only.add(websocket)
        logger.info("ws client connected", extra={"total_connections": len(self.active)})

    def disconnect(self, websocket: WebSocket) -> None:
        self.active.discard(websocket)
        self._camera_scope.pop(websocket, None)
        self._attendance_only.discard(websocket)
        logger.info("ws client disconnected", extra={"total_connections": len(self.active)})

    def _allowed(self, ws: WebSocket, message: dict) -> bool:
        """Cheklangan ulanishga boshqa bino kamerasining hodisasi ketmasin.

        Hodisa xabarlari (EventOut) doim cameraId bilan keladi — kamerasiz
        hodisada u bo'sh satr, ya'ni cheklangan ulanishga bormaydi
        (access_scope bilan bir xil qoida). cameraId umuman yo'q xabarlar
        hodisa emas (davomat yozuvi, ommaviy ko'rib chiqish yig'masi) va
        bino doirasiga bog'liq emas — ular hammaga boradi."""
        if ws in self._attendance_only and message.get("kind") != "attendance_recorded":
            return False
        scope = self._camera_scope.get(ws)
        if scope is None or "cameraId" not in message:
            return True
        return str(message.get("cameraId") or "") in scope

    async def _send_local(self, message: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self.active):
            if not self._allowed(ws, message):
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.discard(ws)
            self._camera_scope.pop(ws, None)
            self._attendance_only.discard(ws)

    async def broadcast(self, message: dict) -> None:
        """Publish to Redis (multi-instance) and always fan out locally."""
        published = await publish_event(message)
        if not published or self._local_only:
            await self._send_local(message)

    async def deliver_from_redis(self, message: dict) -> None:
        """Called by Redis listener — forward to local clients only."""
        await self._send_local(message)


manager = ConnectionManager()
