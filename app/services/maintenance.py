"""Резервное копирование и сервисные операции с данными турнира."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import current_db_path, data_dir
from ..models import Area, AuditEvent, Category, CategoryParticipant, CategoryTemplate, Match, MatchEvent, Participant, Tournament

def clear_tournament_data(db: Session, preserve_templates: bool = True) -> None:
    """Очищает рабочие данные, сохраняя схему и при необходимости шаблоны категорий."""
    for area in db.scalars(select(Area)).all():
        area.current_match_id = None
    db.flush()
    db.execute(delete(MatchEvent))
    db.execute(delete(AuditEvent))
    db.execute(delete(Match))
    db.execute(delete(CategoryParticipant))
    db.execute(delete(Participant))
    db.execute(delete(Category))
    db.execute(delete(Area))
    db.execute(delete(Tournament))
    if not preserve_templates:
        db.execute(delete(CategoryTemplate))
    db.commit()

def backup_database() -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target = data_dir() / "backups" / f"tournament_{stamp}.db"
    # Метод sqlite3.Connection.backup создаёт согласованный снимок даже при активном WAL.
    src = sqlite3.connect(str(current_db_path()))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target
