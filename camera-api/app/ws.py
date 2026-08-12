import logging

from fastapi import WebSocket

logger = logging.getLogger("app.ws")


class ConnectionManager:
    """In-memory registry of connected WebSocket clients — good enough for
    a single-instance deployment. A multi-instance deployment would need
    to fan broadcasts out through Redis pub/sub (or similar) so a client
    connected to instance A gets events created via instance B."""

    def __init__(self) -> None:
        self.active: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.add(websocket)
        logger.info("ws client connected", extra={"total_connections": len(self.active)})

    def disconnect(self, websocket: WebSocket) -> None:
        self.active.discard(websocket)
        logger.info("ws client disconnected", extra={"total_connections": len(self.active)})

    async def broadcast(self, message: dict) -> None:
        dead: list[WebSocket] = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.discard(ws)


manager = ConnectionManager()
