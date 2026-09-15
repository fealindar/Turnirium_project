"""Системная информация, брендинг и переключение рабочей БД."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..branding import load_branding
from ..db import current_db_path, database_catalog, switch_database
from ..network import network_interfaces
from ..version import APP_VERSION
from .common import _broadcast
from .schemas import DatabaseSelectIn

router = APIRouter()


@router.get("/system")
def system_info():
    return {
        "db_path": str(current_db_path()),
        "version": APP_VERSION,
        "branding": load_branding(),
    }


@router.get("/system/runtime")
async def system_runtime(request: Request):
    port = int(getattr(request.app.state, "server_port", 8000) or 8000)
    manager = getattr(request.app.state, "ws_manager", None)
    clients = manager.snapshot() if manager else []
    return {
        "version": APP_VERSION,
        "started_at": getattr(request.app.state, "server_started_at", None),
        "local_url": f"http://127.0.0.1:{port}",
        "interfaces": network_interfaces(port),
        "clients": clients,
        "client_count": len(clients),
    }


@router.get("/databases")
def databases_info():
    return database_catalog()


@router.post("/databases/select")
async def select_database(data: DatabaseSelectIn, request: Request):
    path = data.path.strip()
    if not path:
        raise HTTPException(400, "Укажите путь к базе данных")

    before = current_db_path()
    try:
        selected = switch_database(path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Не удалось подключить базу данных: {exc}") from exc

    if selected != before:
        await _broadcast(
            request,
            {"type": "database_switched", "db_path": str(selected)},
        )
    return {
        "ok": True,
        "db_path": str(selected),
        "catalog": database_catalog(),
    }


@router.get("/branding")
def branding_info():
    return load_branding()
