"""HTTP-операции резервного копирования, аудита и очистки БД."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..engine import backup_database, clear_tournament_data
from ..models import AuditEvent
from .common import _broadcast
from .schemas import ClearDatabaseIn

router = APIRouter()


def _audit_event_dict(event: AuditEvent) -> dict:
    """Сериализует запись аудита для административного интерфейса."""

    try:
        payload = json.loads(event.payload_json or "{}")
    except json.JSONDecodeError:
        # Повреждённая старая запись аудита не должна ломать весь журнал.
        payload = {"raw": event.payload_json or ""}

    return {
        "id": event.id,
        "time": event.created_at.isoformat(),
        "event": event.event_type,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "area_id": event.area_id,
        "payload": payload,
    }


@router.post("/maintenance/clear-database")
async def clear_database(
    data: ClearDatabaseIn,
    request: Request,
    db: Session = Depends(get_db),
):
    if data.confirmation.strip().upper() != "ОЧИСТИТЬ":
        raise HTTPException(400, "Для подтверждения введите ОЧИСТИТЬ")

    try:
        backup_path = backup_database()
        clear_tournament_data(db, preserve_templates=data.preserve_templates)
    except Exception as exc:
        raise HTTPException(500, f"Не удалось очистить БД: {exc}") from exc

    await _broadcast(request, {"type": "database_cleared"})
    return {"ok": True, "backup_path": str(backup_path)}


@router.get("/tournaments/{tournament_id}/audit")
def audit_log(
    tournament_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    safe_limit = min(max(limit, 1), 500)
    rows = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.tournament_id == tournament_id)
        .order_by(AuditEvent.id.desc())
        .limit(safe_limit)
    ).all()
    return [_audit_event_dict(event) for event in rows]


@router.post("/backup")
def backup():
    try:
        path = backup_database()
    except Exception as exc:
        raise HTTPException(500, f"Не удалось создать резервную копию: {exc}") from exc
    return {"path": str(path)}
