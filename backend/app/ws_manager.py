"""
WebSocket connection manager for real-time push notifications.
Used to notify frontend clients when background jobs (e.g. insight runs) complete.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._active: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._active.append(websocket)
        logger.info(f"WS client connected. Total: {len(self._active)}")

    def disconnect(self, websocket: WebSocket) -> None:
        self._active = [ws for ws in self._active if ws is not websocket]
        logger.info(f"WS client disconnected. Total: {len(self._active)}")

    async def broadcast(self, message: Dict[str, Any]) -> None:
        payload = json.dumps(message)
        dead: list[WebSocket] = []
        for ws in list(self._active):
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
