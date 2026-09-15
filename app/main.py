from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .branding import load_branding
from .db import init_db
from .network import network_interfaces
from .realtime import WebSocketManager, client_info, install_windows_disconnect_handler
from .version import APP_VERSION

logger = logging.getLogger(__name__)
BRANDING = load_branding()


def resource_dir() -> Path:
    """Возвращает каталог статических ресурсов в исходниках и PyInstaller-сборке."""

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "app" / "static"
    return Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Инициализирует БД и системные обработчики на время работы сервера."""

    init_db()
    application.state.server_started_at = datetime.now(timezone.utc).isoformat()
    loop = asyncio.get_running_loop()
    previous_handler = install_windows_disconnect_handler(loop)
    try:
        yield
    finally:
        loop.set_exception_handler(previous_handler)


app = FastAPI(title=BRANDING["app_name"], version=APP_VERSION, lifespan=lifespan)
app.state.ws_manager = WebSocketManager()
app.state.server_port = 8000
app.state.server_started_at = None
app.include_router(router)

STATIC_DIR = resource_dir()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    manager: WebSocketManager = app.state.ws_manager
    await manager.connect(websocket, client_info(websocket))
    await manager.broadcast({"type": "clients_changed"})
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, ConnectionResetError, BrokenPipeError):
        pass
    except Exception:
        logger.exception("Неожиданная ошибка WebSocket-клиента")
    finally:
        manager.disconnect(websocket)
        await manager.broadcast({"type": "clients_changed"})
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect):
            pass


@app.get("/{path:path}")
def spa(path: str):
    """Возвращает SPA для всех клиентских маршрутов."""

    return FileResponse(STATIC_DIR / "index.html")


def open_browser_later(port: int) -> None:
    """Открывает интерфейс организатора после запуска локального сервера."""

    time.sleep(1.2)
    webbrowser.open(f"http://127.0.0.1:{port}/admin")


def existing_server(port: int) -> bool:
    """Проверяет, запущен ли уже Turnirium на указанном локальном порту."""

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/system", timeout=0.6) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def safe_print(message: str) -> None:
    """Печатает сообщение только при наличии консольного stdout."""

    if sys.stdout is not None:
        print(message)


def _run_server_only(host: str, port: int, no_browser: bool) -> None:
    app.state.server_port = port
    init_db()
    safe_print(f"{BRANDING['app_name']} {APP_VERSION}")
    safe_print(f"Локально: http://127.0.0.1:{port}/admin")
    for row in network_interfaces(port):
        safe_print(f"В локальной сети ({row['name']}): {row['base_url']}/admin")
    if not no_browser:
        threading.Thread(target=open_browser_later, args=(port,), daemon=True).start()
    if sys.stdout is None or sys.stderr is None:
        uvicorn.run(app, host=host, port=port, log_config=None, access_log=False)
    else:
        uvicorn.run(app, host=host, port=port, log_level="info")


def _run_desktop(host: str, port: int) -> None:
    from .desktop import DesktopController

    app.state.server_port = port
    init_db()
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_config=None,
        access_log=False,
        log_level="warning",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="turnirium-server")
    thread.start()

    def shutdown() -> None:
        server.should_exit = True

    ui = DesktopController(port=port, app_name=BRANDING["app_name"], request_shutdown=shutdown)
    ui.run()
    server.should_exit = True
    thread.join(timeout=4)


def run() -> None:
    """Разбирает параметры запуска и выбирает desktop- или серверный режим."""

    parser = argparse.ArgumentParser(description=BRANDING["app_name"])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--server-only", action="store_true", help="Запустить без desktop-окна и трея")
    args = parser.parse_args()

    if existing_server(args.port):
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{args.port}/admin")
        return

    desktop_available = sys.platform == "win32" or bool(os.environ.get("DISPLAY"))
    if not args.server_only and desktop_available:
        try:
            _run_desktop(args.host, args.port)
            return
        except Exception as exc:
            logger.exception("Не удалось запустить desktop-оболочку")
            safe_print(f"Desktop-интерфейс недоступен: {exc}. Запуск в серверном режиме.")
    _run_server_only(args.host, args.port, args.no_browser)


if __name__ == "__main__":
    run()
