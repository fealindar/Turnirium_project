"""Остановка незавершённых поединков и восстановление категории из архива."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Category, Match


def cancel_unfinished_matches(db: Session, category: Category) -> int:
    """Отменяет несостоявшиеся бои, сохраняя историю и результаты завершённых."""
    matches = db.scalars(select(Match).where(
        Match.category_id == category.id, Match.status.not_in(["finished", "cancelled"])
    )).all()
    for match in matches:
        for cp, warnings in ((match.red_cp, match.red_warnings), (match.blue_cp, match.blue_warnings)):
            if cp and warnings:
                cp.cumulative_warnings = max(0, cp.cumulative_warnings - warnings)
                limit = category.cumulative_warning_limit
                cp.disqualified = bool(limit > 0 and cp.cumulative_warnings >= limit)
        # Отмечаем как отменённые, чтобы при повторном открытии они не применились.
        for event in match.events:
            if not event.undone:
                event.undone = True
        match.status = "cancelled"
        match.red_score = match.blue_score = 0
        match.red_warnings = match.blue_warnings = 0
        match.timer_running = False
        match.timer_started_at = None
        match.timer_revision += 1
        match.started_at = None
        match.remaining_ms = match.duration_ms
        match.area_id = None
        match.queue_order = 0
        match.version += 1
    db.flush()
    return len(matches)


def reopen_cancelled_matches(db: Session, category: Category) -> int:
    """Возвращает в работу отменённые бои без их старых предварительных санкций."""
    matches = db.scalars(select(Match).where(
        Match.category_id == category.id, Match.status == "cancelled"
    )).all()
    for match in matches:
        if match.stage in {"group", "swiss"} and not category.bracket_locked:
            match.status = "staged"
        elif match.red_cp_id and match.blue_cp_id:
            match.status = "ready"
        else:
            match.status = "blocked"
        match.version += 1
    db.flush()
    return len(matches)
