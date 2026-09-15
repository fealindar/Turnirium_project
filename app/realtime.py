"""Соединения WebSocket и обслуживание жизненного цикла приложения."""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ClientInfo:
    """Краткое описание подключённого веб-экрана."""

    id: str
    ip: str
    port: int | None
    screen: str
    area_id: int | None
    tournament_id: int | None
    connected_at: str
    user_agent: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ip": self.ip,
            "port": self.port,
            "screen": self.screen,
            "area_id": self.area_id,
            "tournament_id": self.tournament_id,
            "connected_at": self.connected_at,
            "user_agent": self.user_agent,
        }


class WebSocketManager:
    """Хранит активные WebSocket-клиенты и рассылает им события."""

    def __init__(self) -> None:
        self._connections: dict[WebSocket, ClientInfo] = {}

    async def connect(self, websocket: WebSocket, metadata: ClientInfo) -> None:
        await websocket.accept()
        self._connections[websocket] = metadata

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.pop(websocket, None)

    def snapshot(self) -> list[dict[str, Any]]:
        return [item.as_dict() for item in self._connections.values()]

    async def broadcast(self, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for websocket in tuple(self._connections):
            try:
                await websocket.send_json(payload)
            except (ConnectionResetError, BrokenPipeError, RuntimeError):
                stale.append(websocket)
            except Exception:
                logger.exception("Ошибка отправки WebSocket-события")
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)


def parse_optional_int(value: str | None) -> int | None:
    """Преобразует необязательный параметр URL в целое число."""

    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def client_info(websocket: WebSocket) -> ClientInfo:
    """Собирает метаданные нового WebSocket-клиента."""

    params = websocket.query_params
    return ClientInfo(
        id=uuid4().hex[:10],
        ip=websocket.client.host if websocket.client else "",
        port=websocket.client.port if websocket.client else None,
        screen=(params.get("screen") or "unknown")[:32],
        area_id=parse_optional_int(params.get("area_id")),
        tournament_id=parse_optional_int(params.get("tournament_id")),
        connected_at=datetime.now(timezone.utc).isoformat(),
        user_agent=(websocket.headers.get("user-agent") or "")[:240],
    )


def install_windows_disconnect_handler(loop: asyncio.AbstractEventLoop):
    """Подавляет только ожидаемые WinError 10053/10054 при закрытии вкладки."""

    previous_handler = loop.get_exception_handler()

    def handler(event_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        winerror = getattr(exc, "winerror", None)
        expected = (
            sys.platform == "win32"
            and isinstance(exc, (ConnectionResetError, BrokenPipeError))
            and winerror in (10053, 10054)
        )
        if expected:
            return
        if previous_handler:
            previous_handler(event_loop, context)
        else:
            event_loop.default_exception_handler(context)

    loop.set_exception_handler(handler)
    return previous_handler
