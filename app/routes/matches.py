"""HTTP-управление поединком, счётом, предупреждениями и таймером."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import SessionLocal, current_db_generation, get_db
from ..engine import (
    add_warning,
    apply_score,
    correct_finished_match,
    effective_remaining_ms,
    finish_match,
    match_dict,
    undo_last_event,
)
from ..models import Match
from .common import _broadcast, _get_or_404
from .schemas import FinishIn, MatchCorrectionIn, ScoreIn, SideIn, TimerSetIn

router = APIRouter()


def _ensure_timer_mutable(match: Match) -> None:
    """Запрещает менять таймер завершённого поединка."""

    if match.status == "finished":
        raise HTTPException(409, "Поединок уже завершен")


def _ensure_match_can_start(match: Match) -> None:
    """Проверяет, что таймер можно запустить для сформированного боя."""

    _ensure_timer_mutable(match)
    if match.status in {"staged", "blocked"}:
        raise HTTPException(409, "Поединок ещё не готов к проведению")
    if match.red_cp_id is None or match.blue_cp_id is None:
        raise HTTPException(
            409,
            "Для запуска таймера должны быть определены оба участника",
        )


async def _broadcast_match_change(request: Request, match: Match, event_type: str) -> None:
    """Отправляет типовое уведомление об изменении одного боя."""

    await _broadcast(
        request,
        {
            "type": event_type,
            "match_id": match.id,
            "area_id": match.area_id,
        },
    )


async def _broadcast_match_result(request: Request, match: Match, event_type: str) -> None:
    """Уведомляет все экраны, зависящие от результата поединка."""

    tournament_id = match.category.tournament_id
    await _broadcast(
        request,
        {
            "type": event_type,
            "match_id": match.id,
            "area_id": match.area_id,
            "category_id": match.category_id,
            "tournament_id": tournament_id,
        },
    )
    await _broadcast(
        request,
        {
            "type": "schedule_changed",
            "tournament_id": tournament_id,
            "area_id": match.area_id,
        },
    )
    await _broadcast(
        request,
        {
            "type": "bracket_changed",
            "category_id": match.category_id,
            "tournament_id": tournament_id,
        },
    )


@router.get("/matches/{match_id}")
def get_match(match_id: int, db: Session = Depends(get_db)):
    return match_dict(_get_or_404(db, Match, match_id, "Поединок"))


@router.post("/matches/{match_id}/score")
async def score(
    match_id: int,
    data: ScoreIn,
    request: Request,
    db: Session = Depends(get_db),
):
    match = _get_or_404(db, Match, match_id, "Поединок")
    try:
        apply_score(db, match, data.side, data.delta)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    await _broadcast_match_change(request, match, "match_changed")
    return match_dict(match)


@router.post("/matches/{match_id}/warning")
async def warning(
    match_id: int,
    data: SideIn,
    request: Request,
    db: Session = Depends(get_db),
):
    match = _get_or_404(db, Match, match_id, "Поединок")
    try:
        outcome = add_warning(db, match, data.side)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    await _broadcast(
        request,
        {
            "type": "match_changed",
            "match_id": match.id,
            "area_id": match.area_id,
            "warning": outcome,
        },
    )
    return {"match": match_dict(match), "outcome": outcome}


@router.post("/matches/{match_id}/undo")
async def undo(
    match_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    match = _get_or_404(db, Match, match_id, "Поединок")
    if not undo_last_event(db, match):
        raise HTTPException(409, "Нет действия, которое можно безопасно отменить")

    await _broadcast_match_change(request, match, "match_changed")
    return match_dict(match)


@router.post("/matches/{match_id}/finish")
async def finish(
    match_id: int,
    data: FinishIn,
    request: Request,
    db: Session = Depends(get_db),
):
    match = _get_or_404(db, Match, match_id, "Поединок")
    try:
        finish_match(db, match, data.winner_cp_id, data.reason)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    await _broadcast_match_result(request, match, "match_finished")
    return match_dict(match)


@router.put("/matches/{match_id}/correction")
async def correct_match(
    match_id: int,
    data: MatchCorrectionIn,
    request: Request,
    db: Session = Depends(get_db),
):
    match = _get_or_404(db, Match, match_id, "Поединок")
    try:
        result = correct_finished_match(
            db,
            match,
            red_score=data.red_score,
            blue_score=data.blue_score,
            red_warnings=data.red_warnings,
            blue_warnings=data.blue_warnings,
            winner_cp_id=data.winner_cp_id,
            reason=data.reason,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    await _broadcast_match_result(request, match, "match_corrected")
    return result


async def _timer_expiry(
    app,
    match_id: int,
    revision: int,
    delay_ms: int,
    db_generation: int,
) -> None:
    """Останавливает таймер, если отложенная задача всё ещё относится к текущей БД."""

    await asyncio.sleep(max(0, delay_ms) / 1000)

    # Фоновая задача таймера принадлежит БД, в которой была запущена. После
    # переключения БД старая задача не должна менять новый файл.
    if current_db_generation() != db_generation:
        return

    with SessionLocal() as db:
        match = db.get(Match, match_id)
        if not match or not match.timer_running or match.timer_revision != revision:
            return
        if effective_remaining_ms(match) > 50:
            return

        match.remaining_ms = 0
        match.timer_running = False
        match.timer_started_at = None
        match.version += 1
        area_id = match.area_id
        db.commit()

    manager = getattr(app.state, "ws_manager", None)
    if manager:
        await manager.broadcast(
            {
                "type": "timer_finished",
                "match_id": match_id,
                "area_id": area_id,
            }
        )


@router.post("/matches/{match_id}/timer/start")
async def timer_start(
    match_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    match = _get_or_404(db, Match, match_id, "Поединок")
    _ensure_match_can_start(match)

    remaining = effective_remaining_ms(match)
    if remaining <= 0:
        raise HTTPException(
            409,
            "Таймер на нуле — сначала сбросьте или задайте время",
        )

    now = datetime.now(timezone.utc)
    match.remaining_ms = remaining
    match.timer_running = True
    match.timer_started_at = now
    match.timer_revision += 1
    match.version += 1
    if match.status in {"ready", "pending"}:
        match.status = "in_progress"
        match.started_at = match.started_at or now
        match.category.bracket_locked = True

    revision = match.timer_revision
    generation = current_db_generation()
    db.commit()

    asyncio.create_task(
        _timer_expiry(
            request.app,
            match.id,
            revision,
            remaining,
            generation,
        )
    )
    await _broadcast_match_change(request, match, "timer_changed")
    return match_dict(match)


@router.post("/matches/{match_id}/timer/pause")
async def timer_pause(
    match_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    match = _get_or_404(db, Match, match_id, "Поединок")
    _ensure_timer_mutable(match)

    match.remaining_ms = effective_remaining_ms(match)
    match.timer_running = False
    match.timer_started_at = None
    match.timer_revision += 1
    match.version += 1
    db.commit()

    await _broadcast_match_change(request, match, "timer_changed")
    return match_dict(match)


@router.post("/matches/{match_id}/timer/reset")
async def timer_reset(
    match_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    match = _get_or_404(db, Match, match_id, "Поединок")
    _ensure_timer_mutable(match)

    match.remaining_ms = match.duration_ms
    match.timer_running = False
    match.timer_started_at = None
    match.timer_revision += 1
    match.version += 1
    db.commit()

    await _broadcast_match_change(request, match, "timer_changed")
    return match_dict(match)


@router.post("/matches/{match_id}/timer/set")
async def timer_set(
    match_id: int,
    data: TimerSetIn,
    request: Request,
    db: Session = Depends(get_db),
):
    match = _get_or_404(db, Match, match_id, "Поединок")
    _ensure_timer_mutable(match)

    match.remaining_ms = data.seconds * 1000
    match.timer_running = False
    match.timer_started_at = None
    match.timer_revision += 1
    match.version += 1
    db.commit()

    await _broadcast_match_change(request, match, "timer_changed")
    return match_dict(match)
